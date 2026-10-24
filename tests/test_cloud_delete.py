"""Удаление из облака: работает ли оно и кого НЕ трогает.

Настоящее удаление необратимо, поэтому здесь подставной клиент Диска: он
записывает, что у него просили удалить, и ничего никуда не посылает.
Проверяем ровно две вещи -- что подходящие файлы действительно уходят в
удаление (архив при этом не требуется), и что защиты держат.
"""

from __future__ import annotations

try:  # pytest не нужен файлу для работы напрямую
    import pytest
except ImportError:  # pragma: no cover
    pytest = None

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(tempfile.mkdtemp(prefix="cr-del-"))
os.environ["DRYDOCK_ROOT"] = str(ROOT)
os.environ["DRYDOCK_SECRETS"] = str(ROOT / "secrets.bin")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from drydock import cloud, config, db

if pytest is not None:

    @pytest.fixture(autouse=True, scope="module")
    def _own_root():
        """Свой корень спасения для этого файла тестов.

        Файл задаёт DRYDOCK_ROOT при импорте, а PATHS связывается
        один раз на процесс. Если в одном воркере оказалось несколько
        файлов, они бы поделили корень и писали в чужую базу.
        """
        config.set_root(ROOT)
        yield


class FakeDisk:
    """Запоминает запросы на удаление вместо того, чтобы их выполнять."""

    def __init__(self, missing: set[str] | None = None) -> None:
        self.deleted: list[tuple[str, bool]] = []
        # Пути, которых в облаке уже нет: клиент Диска мог удалить их
        # сам, увидев пропажу файла из своей папки.
        self.missing = missing or set()

    async def delete(self, path: str, *, permanently: bool = True):
        self.deleted.append((path, permanently))
        if path in self.missing:
            return False, ('HTTP 404: {"error":"DiskNotFoundError",'
                           '"description":"Resource not found."}')
        return True, ""


def make(conn, path: str, *, verify: str, size: int = 100,
         holes=None, released: int = 0, on_disk: bool = True) -> Path:
    db.upsert_resource(conn, {"path": path, "name": Path(path).name,
                              "type": "file", "size": size,
                              "md5": "m", "sha256": "s"})
    local = config.PATHS.files / Path(path).name
    local.parent.mkdir(parents=True, exist_ok=True)
    if on_disk:
        local.write_bytes(b"x" * size)
    conn.execute(
        """INSERT INTO local(path,local_path,bytes,sha256,md5,verify,holes,
                             downloaded_at,released)
           VALUES(?,?,?,'s','m',?,?,1,?)""",
        (path, str(local), size, verify, json.dumps(holes) if holes else None,
         released))
    return local


def main() -> int:
    config.PATHS.ensure()
    conn = db.connect(config.PATHS.db)

    good = "disk:/book.pdf"          # скачан, хеш сошёлся -- можно
    gaps = "disk:/holes.pdf"         # собран с дырками -- нельзя никогда
    gone = "disk:/missing.pdf"       # в базе есть, на диске нет -- нельзя
    freed = "disk:/released.pdf"     # локальный оригинал убран -- нельзя
    make(conn, good, verify="ok")
    make(conn, gaps, verify="salvaged", holes=[[0, 10]])
    make(conn, gone, verify="ok", on_disk=False)
    make(conn, freed, verify="ok", released=1)

    ok, blocked = cloud.eligible(conn, None)          # умолчание -- downloaded
    names = {Path(r["path"]).name for r in ok}
    assert names == {"book.pdf"}, names
    reasons = {Path(b["path"]).name: b["reason"] for b in blocked}
    assert "дырками" in reasons["holes.pdf"], reasons
    assert "нет на диске" in reasons["missing.pdf"], reasons
    assert "убран" in reasons["released.pdf"], reasons
    print("умолчание -- проверенная локальная копия, архив не требуется")

    # Архив не нужен ни одному из них: архивов в базе нет вовсе.
    assert conn.execute("SELECT COUNT(*) FROM archives").fetchone()[0] == 0

    # Неверное подтверждение не удаляет ничего.
    disk = FakeDisk()
    try:
        asyncio.run(cloud.delete(conn, disk, [], confirm=999))
    except ValueError as exc:
        assert "не подтверждено" in str(exc), exc
    else:
        raise AssertionError("удалило без совпадения подтверждения!")
    assert disk.deleted == [], disk.deleted
    print("без точного подтверждения не удаляет")

    # А с верным -- удаляет, и ровно то, что подходит.
    disk = FakeDisk()
    result = asyncio.run(cloud.delete(conn, disk, [], confirm=len(ok)))
    assert [p for p, _ in disk.deleted] == [good], disk.deleted
    assert all(perm for _, perm in disk.deleted), "должно идти мимо Корзины"
    assert result["deleted"] == 1, result
    row = conn.execute("SELECT * FROM cloud_deleted WHERE path=?", (good,)).fetchone()
    assert row and row["permanently"] == 1, "удаление не записано в журнал"
    assert config.PATHS.audit.is_file(), "нет файла аудита"
    print(f"удалено {result['deleted']}, записано в журнал и аудит")

    # И тут же -- вердикт пробы. До этой правки удаление оставляло пробу
    # «ok»: к 18 октября накопилось 427 файлов, которым интерфейс обещал
    # доступность, хотя в облаке их уже не было.
    probe = conn.execute("SELECT state FROM probe WHERE path=?", (good,)).fetchone()
    assert probe and probe["state"] == "gone", f"удаление не пометило пробу: {dict(probe or {})}"
    print("своё удаление сразу видно в пробе как gone, а не «доступно»")

    # Повторно тот же файл уже не предлагается.
    ok2, _ = cloud.eligible(conn, None)
    assert ok2 == [], "удалённый файл снова предложен к удалению"

    # Строгий уровень по-прежнему доступен и требует архива.
    strict, blocked2 = cloud.eligible(conn, None, level="archived")
    assert strict == []
    assert any("архив" in b["reason"] for b in blocked2)
    print("строгий уровень на месте и требует архива")

    # ── уровень «мусор» ──────────────────────────────────────────────
    # Удалять можно то, что уже не спасётся и локально отсутствует.
    # Всё доступное, непроверенное и уже отсутствующее в облаке -- нет.
    def probe_only(path: str, state: str) -> None:
        db.upsert_resource(conn, {"path": path, "name": Path(path).name,
                                  "type": "file", "size": 50})
        db.record_probe(conn, path, state, 504 if state != "ok" else 200)

    junk_bad = "disk:/junk/bad.bin"       # недоступен, локально нет -- мусор
    probe_only(junk_bad, "unavailable")
    probe_only("disk:/junk/ok.bin", "ok")          # доступен -- ещё скачаем
    # Не проверяли вовсе -- строки пробы нет.
    db.upsert_resource(conn, {"path": "disk:/junk/u.bin", "name": "u.bin",
                              "type": "file", "size": 50})
    probe_only("disk:/junk/gone.bin", "gone")      # объекта уже нет
    make(conn, "disk:/junk/saved.bin", verify="ok")  # спасён -- другой уровень

    ok_junk, blocked_junk = cloud.eligible(conn, None, level="junk")
    names = {Path(r["path"]).name for r in ok_junk}
    assert names == {"bad.bin"}, names
    reasons = {Path(b["path"]).name: b["reason"] for b in blocked_junk}
    assert "скачать" in reasons["ok.bin"], reasons
    assert "не проверено" in reasons["u.bin"], reasons
    assert "нет" in reasons["gone.bin"], reasons
    assert "уже спасено" in reasons["saved.bin"], reasons
    print("уровень «мусор»: только недоступное и неспасённое")

    disk = FakeDisk()
    result = asyncio.run(cloud.delete(conn, disk, [], level="junk",
                                      confirm=len(ok_junk)))
    assert [p for p, _ in disk.deleted] == [junk_bad], disk.deleted
    assert result["deleted"] == 1, result
    assert conn.execute("SELECT COUNT(*) FROM cloud_deleted WHERE path=?",
                        (junk_bad,)).fetchone()[0] == 1
    print("мусор удалён и записан в журнал")

    # ── 404 -- это не ошибка ────────────────────────────────────────
    # Клиент Диска, увидев пропажу файла из своей папки, удаляет
    # облачную копию сам. Наша явная попытка приходит второй и получает
    # 404. Цель достигнута: копии в облаке нет.
    vanished = "disk:/vanished.pdf"
    make(conn, vanished, verify="ok")
    disk = FakeDisk(missing={vanished})
    result = asyncio.run(cloud.delete(conn, disk, [vanished],
                                      confirm=1))
    assert result["deleted"] == 0 and result.get("already") == 1, result
    assert result["failed"] == 0, result
    assert conn.execute("SELECT COUNT(*) FROM cloud_deleted WHERE path=?",
                        (vanished,)).fetchone()[0] == 1
    probe = conn.execute("SELECT state FROM probe WHERE path=?", (vanished,)).fetchone()
    assert probe and probe["state"] == "gone", dict(probe or {})
    print("404 при удалении: «уже нет» записано, в ошибки не пошло")

    print("\nудаление из облака: все проверки прошли")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
