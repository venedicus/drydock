"""Уборка пустых папок: кого удаляем и кого не трогаем никогда.

Удаление структуры каталога -- вещь необратимая, поэтому здесь подставной
Диск: он честно отвечает на перечисление папок и только запоминает запросы
на удаление. Главное в этих проверках -- не то, что DELETE ушёл, а то, что
он НЕ ушёл, когда в папке вдруг оказался файл или опись устарела.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

try:  # pytest есть не всегда: файл умеет запускаться и напрямую
    import pytest
except ImportError:  # pragma: no cover
    pytest = None

ROOT = Path(tempfile.mkdtemp(prefix="cr-empty-"))
os.environ["DRYDOCK_ROOT"] = str(ROOT)
os.environ["DRYDOCK_SECRETS"] = str(ROOT / "secrets.bin")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from drydock import config, db, emptydirs

if pytest is not None:

    @pytest.fixture(autouse=True, scope="module")
    def _own_root():
        """Свой корень: PATHS связывается один раз на процесс."""
        config.set_root(ROOT)
        yield

    @pytest.fixture()
    def conn(tmp):
        """Каждой проверке -- своя пустая база, чтобы они не делили опись."""
        c = db.connect(Path(tmp) / "catalog.db")
        yield c
        c.close()


class FakeDisk:
    """Облако в памяти. Ничего не удаляет по-настоящему."""

    def __init__(self, contents: dict | None = None,
                 missing: set[str] | None = None,
                 totals: dict | None = None) -> None:
        # path -> список элементов (как в ответе Яндекс.Диска)
        self.contents = contents or {}
        self.missing = missing or set()
        # Подмена total: сервер обещает элементы, но не отдаёт их.
        self.totals = totals or {}
        self.listed: list[str] = []
        self.deleted: list[tuple[str, bool]] = []

    async def listdir(self, path: str, *, offset: int = 0,
                      limit: int = 500) -> dict:
        self.listed.append(path)
        if path in self.missing:
            raise FileNotFoundError(path)
        items = self.contents.get(path, [])
        total = self.totals.get(path, len(items))
        return {"type": "dir", "path": path,
                "_embedded": {"total": total,
                              "items": items[offset:offset + limit]}}

    async def delete(self, path: str, *, permanently: bool = True):
        self.deleted.append((path, permanently))
        if path in self.missing:
            return False, 'HTTP 404: {"error":"DiskNotFoundError"}'
        return True, ""


def put_dir(conn, path: str) -> None:
    db.upsert_resource(conn, {
        "path": path, "name": path.rsplit("/", 1)[-1],
        "type": "dir", "size": 0})


def put_file(conn, path: str, *, vanished: bool = False,
             deleted: bool = False, probe_state: str | None = None) -> None:
    db.upsert_resource(conn, {
        "path": path, "name": path.rsplit("/", 1)[-1],
        "type": "file", "size": 10})
    if vanished:
        conn.execute("UPDATE resources SET vanished_at=1 WHERE path=?", (path,))
    if deleted:
        conn.execute("INSERT INTO cloud_deleted(path,deleted_at,permanently,"
                     "response) VALUES(?,?,?,?)", (path, 1, 1, ""))
    if probe_state:
        db.record_probe(conn, path, probe_state, None, None, "")


def dir_item(path: str) -> dict:
    return {"path": path, "name": path.rsplit("/", 1)[-1], "type": "dir"}


def file_item(path: str) -> dict:
    return {"path": path, "name": path.rsplit("/", 1)[-1], "type": "file"}


# ── список кандидатов ────────────────────────────────────────────────

def test_empty_tree_is_one_root(conn) -> None:
    """Целое дерево пустых папок удаляется одним запросом на корень."""
    for p in ("disk:/A", "disk:/A/B", "disk:/A/B/C"):
        put_dir(conn, p)
    cands = emptydirs.candidates(conn)
    assert cands == ["disk:/A", "disk:/A/B", "disk:/A/B/C"], cands
    assert emptydirs.tree_roots(cands) == ["disk:/A"]
    pre = emptydirs.preview(conn)
    assert pre["trees"] == 1 and pre["folders"] == 3 and pre["confirm"] == 1
    assert pre["sample"] == ["disk:/A"], pre
    print("дерево из трёх пустых папок: один корень, один DELETE")


def test_live_file_blocks_only_its_own_branch(conn) -> None:
    """Файл в A/B не защищает пустую подпапку A/B/C."""
    for p in ("disk:/A", "disk:/A/B", "disk:/A/B/C"):
        put_dir(conn, p)
    put_file(conn, "disk:/A/B/book.pdf")
    cands = emptydirs.candidates(conn)
    assert cands == ["disk:/A/B/C"], cands
    assert emptydirs.tree_roots(cands) == ["disk:/A/B/C"]
    print("живой файл защищает свою ветку, но не соседнюю пустую")


def test_probe_gone_does_not_make_folder_empty(conn) -> None:
    """`gone` -- плавающий вердикт пробы, а не доказательство пустоты.

    Файл с пробой gone может вернуться, поэтому папка НЕ должна даже
    попадать в кандидаты. Достоверны только vanished_at (полный обход
    облака) и cloud_deleted (удалили мы сами).
    """
    put_dir(conn, "disk:/V")
    put_dir(conn, "disk:/D")
    put_dir(conn, "disk:/G")
    put_file(conn, "disk:/V/a.bin", vanished=True)
    put_file(conn, "disk:/D/b.bin", deleted=True)
    put_file(conn, "disk:/G/c.bin", probe_state="gone")
    assert emptydirs.tree_roots(emptydirs.candidates(conn)) == [
        "disk:/D", "disk:/V"], "проба gone не должна защищать меньше, чем опись"
    print("probe gone: папка не кандидат (файл может вернуться)")


def test_root_itself_is_never_a_candidate(conn) -> None:
    put_dir(conn, "disk:/")
    assert emptydirs.candidates(conn) == []
    print("корень disk:/ не удаляем никогда")


def test_already_removed_folder_is_not_offered_again(conn) -> None:
    """После уборки запись остаётся в описи, но предлагать её нельзя."""
    put_dir(conn, "disk:/A")
    disk = FakeDisk({"disk:/A": []})
    assert emptydirs.tree_roots(emptydirs.candidates(conn)) == ["disk:/A"]
    asyncio.run(emptydirs.delete_empty(conn, disk, ["disk:/A"], confirm=1))
    assert emptydirs.preview(conn)["trees"] == 0, \
        "убранная папка не должна снова попадать в список"
    print("после удаления: vanished-папка больше не предлагается")


# ── живая проверка поддерева ─────────────────────────────────────────

def test_inspect_empty_tree(conn) -> None:
    disk = FakeDisk({
        "disk:/A": [dir_item("disk:/A/B")],
        "disk:/A/B": [dir_item("disk:/A/B/C")],
        "disk:/A/B/C": [],
    })
    verdict, folders, reason = asyncio.run(
        emptydirs.inspect_tree(disk, "disk:/A"))
    assert (verdict, folders, reason) == ("empty", 3, ""), (verdict, folders, reason)
    assert sorted(disk.listed) == ["disk:/A", "disk:/A/B", "disk:/A/B/C"]
    print("живая проверка обошла всё дерево и разрешила удаление")


def test_inspect_finds_a_new_file(conn) -> None:
    """Опись говорит «пусто», а в облаке за ночь появился файл."""
    disk = FakeDisk({
        "disk:/A": [dir_item("disk:/A/B")],
        "disk:/A/B": [file_item("disk:/A/B/new.pdf")],
    })
    verdict, _, reason = asyncio.run(emptydirs.inspect_tree(disk, "disk:/A"))
    assert verdict == "blocked" and "файл" in reason, (verdict, reason)
    assert disk.deleted == []
    print("свежий файл в облаке: дерево не тронуто")


def test_inspect_missing_folder(conn) -> None:
    disk = FakeDisk(missing={"disk:/A"})
    verdict, _, _ = asyncio.run(emptydirs.inspect_tree(disk, "disk:/A"))
    assert verdict == "missing", verdict
    print("папки уже нет: удалять нечего")


def test_live_file_trumps_vanished_inventory(conn) -> None:
    """Главное: файл числится vanished в базе, но реально лежит в облаке.

    Опись -- это слепок на вчера. Решение принимает только живое
    перечисление: если в текущий момент файл есть, каскад не трогаем.
    """
    put_dir(conn, "disk:/A")
    put_file(conn, "disk:/A/back.pdf", vanished=True)
    assert emptydirs.tree_roots(emptydirs.candidates(conn)) == ["disk:/A"]
    disk = FakeDisk({"disk:/A": [file_item("disk:/A/back.pdf")]})
    res = asyncio.run(emptydirs.delete_empty(
        conn, disk, ["disk:/A"], confirm=1))
    assert res["kept"] == 1 and res["deleted"] == 0, res
    assert disk.deleted == [], "vanished в описи не повод удалять живой файл"
    print("файл вернулся в облако: каскад папок оставлен, DELETE не ушёл")


def test_untrustworthy_listdir_blocks(conn) -> None:
    """Сервер обещал total=3, а items не отдал -- верить нельзя."""
    disk = FakeDisk({"disk:/A": []}, totals={"disk:/A": 3})
    verdict, _, reason = asyncio.run(emptydirs.inspect_tree(disk, "disk:/A"))
    assert verdict == "blocked" and "неполное" in reason, (verdict, reason)
    print("противоречивый ответ Диска: папка не удаляется")


def test_missing_child_does_not_block_parent(conn) -> None:
    """Подпапку уже убрали, а родитель есть и пуст -- его надо удалить."""
    disk = FakeDisk({"disk:/A": [dir_item("disk:/A/B")]},
                    missing={"disk:/A/B"})
    verdict, _, _ = asyncio.run(emptydirs.inspect_tree(disk, "disk:/A"))
    assert verdict == "empty", verdict
    res = asyncio.run(emptydirs.delete_empty(
        conn, disk, ["disk:/A"], confirm=1))
    assert res["deleted"] == 1 and ("disk:/A", False) in disk.deleted, res
    print("дочерняя папка исчезла: пустой родитель всё равно удаляется")


# ── полный живой обход облака ────────────────────────────────────────

def test_live_scan_finds_folders_absent_from_inventory(conn) -> None:
    """Главный смысл обхода: папок нет в базе, а в облаке они пустые."""
    disk = FakeDisk({
        "disk:/": [dir_item("disk:/New")],
        "disk:/New": [dir_item("disk:/New/Deep")],
        "disk:/New/Deep": [],
    })
    res = asyncio.run(emptydirs.scan_live(disk))
    assert res["complete"] is True and res["scanned"] == 3, res
    assert res["trees"] == 1 and res["folders"] == 2, res
    assert res["roots"] == ["disk:/New"], res
    assert emptydirs.candidates(conn) == [], "в описи этих папок нет"
    print("живой обход нашёл пустое дерево, которого нет в описи")


def test_live_scan_file_blocks_its_branch_only(conn) -> None:
    """Файл в облаке защищает свою ветку, но не пустую соседнюю."""
    disk = FakeDisk({
        "disk:/": [dir_item("disk:/A"), dir_item("disk:/B")],
        "disk:/A": [file_item("disk:/A/book.pdf"),
                    dir_item("disk:/A/Empty")],
        "disk:/A/Empty": [],
        "disk:/B": [],
    })
    res = asyncio.run(emptydirs.scan_live(disk))
    assert res["complete"] is True, res
    assert res["roots"] == ["disk:/A/Empty", "disk:/B"], res
    print("живой файл защитил свою ветку, пустые соседние остались в списке")


def test_live_scan_unreliable_branch_is_protected(conn) -> None:
    """Недостоверный ответ -- ветка и все предки не удаляются."""
    disk = FakeDisk({
        "disk:/": [dir_item("disk:/A"), dir_item("disk:/B")],
        "disk:/A": [dir_item("disk:/A/Deep")],
        "disk:/A/Deep": [],
        "disk:/B": [],
    }, totals={"disk:/A/Deep": 3})
    res = asyncio.run(emptydirs.scan_live(disk))
    assert res["complete"] is True and res["blocked"] == 1, res
    assert res["roots"] == ["disk:/B"], res
    print("противоречивый ответ: ветка защищена, соседняя пустая найдена")


def test_live_scan_stop_returns_no_roots(conn) -> None:
    """Стоп посреди обхода -- список неполный, удалять по нему нельзя."""
    disk = FakeDisk({
        "disk:/": [dir_item("disk:/A")],
        "disk:/A": [dir_item("disk:/A/B")],
        "disk:/A/B": [],
    })
    # Стоп после первого же запроса к Диску: обход не должен выдать
    # «готово» и отдать корни по обрывку дерева.
    res = asyncio.run(emptydirs.scan_live(
        disk, should_stop=lambda: len(disk.listed) >= 1))
    assert res["complete"] is False and res["roots"] == [], res
    print("обход прерван: ни одного корня не отдано")


def test_live_scan_folder_limit_is_honest(conn) -> None:
    """Лимит папок -- тоже обрыв, а не «готово»."""
    disk = FakeDisk({
        "disk:/": [dir_item("disk:/A")],
        "disk:/A": [dir_item("disk:/A/B")],
        "disk:/A/B": [],
    })
    res = asyncio.run(emptydirs.scan_live(disk, max_folders=2))
    assert res["complete"] is False and res["roots"] == [], res
    assert res["scanned"] == 2, res
    print("лимит папок: обход честно помечен незавершённым")


def test_live_scan_root_itself_never_deleted(conn) -> None:
    disk = FakeDisk({"disk:/": []})
    res = asyncio.run(emptydirs.scan_live(disk))
    assert res["roots"] == [], res
    print("корень disk:/ не предлагается к удалению")


# ── собственно удаление ──────────────────────────────────────────────

def test_delete_uses_trash_by_default(conn) -> None:
    for p in ("disk:/A", "disk:/A/B"):
        put_dir(conn, p)
    db.mark_empty(conn, "disk:/A/B", True)
    disk = FakeDisk({"disk:/A": [dir_item("disk:/A/B")], "disk:/A/B": []})
    res = asyncio.run(emptydirs.delete_empty(
        conn, disk, ["disk:/A"], confirm=1))
    assert res["deleted"] == 1 and res["failed"] == 0, res
    # Пустые папки не занимают квоту -- Корзина безопаснее.
    assert disk.deleted == [("disk:/A", False)], disk.deleted
    # Опись больше не показывает убранную структуру в линзе «Сейчас».
    gone = conn.execute("SELECT COUNT(*) FROM resources "
                        "WHERE vanished_at IS NOT NULL").fetchone()[0]
    assert gone == 2, gone
    assert db.known_empty_dirs(conn) == {}, db.known_empty_dirs(conn)
    print("удаление: один DELETE в Корзину, опись помечена, кэш пустых снят")


def test_delete_blocked_when_cloud_changed(conn) -> None:
    put_dir(conn, "disk:/A")
    disk = FakeDisk({"disk:/A": [file_item("disk:/A/surprise.pdf")]})
    res = asyncio.run(emptydirs.delete_empty(
        conn, disk, ["disk:/A"], confirm=1))
    assert res["kept"] == 1 and res["deleted"] == 0, res
    assert disk.deleted == [], "устаревшая опись не должна приводить к удалению"
    assert conn.execute("SELECT vanished_at FROM resources WHERE path=?",
                        ("disk:/A",)).fetchone()[0] is None
    print("расхождение описи с облаком: папка пропущена, DELETE не ушёл")


def test_delete_404_counts_as_already(conn) -> None:
    put_dir(conn, "disk:/A")
    disk = FakeDisk(missing={"disk:/A"})
    res = asyncio.run(emptydirs.delete_empty(
        conn, disk, ["disk:/A"], confirm=1))
    assert res["already"] == 1 and res["failed"] == 0, res
    assert disk.deleted == [], "404 от listdir -- удаление не отправляем"
    print("папку убрал клиент Диска: честно «уже нет», не ошибка")


def test_confirm_mismatch_is_refused(conn) -> None:
    disk = FakeDisk()
    try:
        asyncio.run(emptydirs.delete_empty(
            conn, disk, ["disk:/A", "disk:/B"], confirm=1))
    except ValueError as exc:
        assert "confirm" in str(exc)
    else:
        raise AssertionError("разное число не должно подтверждаться")
    assert disk.deleted == []
    print("confirm не совпал: удаление не началось")


def test_permanent_is_explicit(conn) -> None:
    put_dir(conn, "disk:/A")
    disk = FakeDisk({"disk:/A": []})
    res = asyncio.run(emptydirs.delete_empty(
        conn, disk, ["disk:/A"], confirm=1, permanently=True))
    assert res["deleted"] == 1 and disk.deleted == [("disk:/A", True)]
    # Аудит необратимых действий: строка с признаком permanently.
    lines = config.PATHS.audit.read_text(encoding="utf-8").splitlines()
    rec = [json.loads(x) for x in lines
           if json.loads(x).get("action") == "empty_dir_delete"]
    assert rec and rec[-1]["permanently"] is True, rec[-1:]
    print("безвозвратное удаление -- только по явному выбору, в аудите")


def test_empty_roots_do_nothing(conn) -> None:
    disk = FakeDisk()
    res = asyncio.run(emptydirs.delete_empty(conn, disk, [], confirm=0))
    assert res["deleted"] == 0 and disk.deleted == []
    print("пустой список: ни запросов, ни задачи")


# ── прямой запуск без pytest ─────────────────────────────────────────

CHECKS = (
    test_empty_tree_is_one_root, test_live_file_blocks_only_its_own_branch,
    test_probe_gone_does_not_make_folder_empty,
    test_root_itself_is_never_a_candidate,
    test_already_removed_folder_is_not_offered_again,
    test_inspect_empty_tree, test_inspect_finds_a_new_file,
    test_inspect_missing_folder, test_live_file_trumps_vanished_inventory,
    test_untrustworthy_listdir_blocks,
    test_missing_child_does_not_block_parent,
    test_delete_uses_trash_by_default,
    test_delete_blocked_when_cloud_changed, test_delete_404_counts_as_already,
    test_confirm_mismatch_is_refused, test_permanent_is_explicit,
    test_empty_roots_do_nothing,
    test_live_scan_finds_folders_absent_from_inventory,
    test_live_scan_file_blocks_its_branch_only,
    test_live_scan_unreliable_branch_is_protected,
    test_live_scan_stop_returns_no_roots,
    test_live_scan_folder_limit_is_honest,
    test_live_scan_root_itself_never_deleted,
)


def main() -> int:
    config.set_root(ROOT)
    for check in CHECKS:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            c = db.connect(Path(d) / "catalog.db")
            try:
                check(c)
            finally:
                c.close()
    print("\nпустые папки: все проверки прошли")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
