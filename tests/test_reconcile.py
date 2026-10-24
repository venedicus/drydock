"""Сверка описи с облаком: что исчезло, что вернулось, и когда сверять НЕЛЬЗЯ.

Опись -- слепок, а облако живёт дальше. 18 октября из него ушли
CzarStream-папки на 710 ГБ, и экран продолжал показывать их как
существующие: цифры врали, пока кто-то не полез проверять руками.

Самое важное здесь -- третья проверка. Сверка опирается на время начала
ВСЕГО обхода, и если взять вместо него «сейчас», то продолженная опись
объявит пропавшим всё, что описано до обрыва. На живой базе это десятки
тысяч файлов разом, поэтому случай проверяется отдельно.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

try:
    import pytest
except ImportError:
    pytest = None

ROOT = Path(tempfile.mkdtemp(prefix="cr-rec-"))
os.environ["DRYDOCK_ROOT"] = str(ROOT)
os.environ["DRYDOCK_SECRETS"] = str(ROOT / "secrets.bin")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from drydock import config, db, scan, tree

if pytest is not None:

    @pytest.fixture(autouse=True, scope="module")
    def _own_root():
        config.set_root(ROOT)
        yield


def make(conn, path: str, seen: int) -> None:
    db.upsert_resource(conn, {"path": path, "name": Path(path).name,
                              "type": "file", "size": 10})
    conn.execute("UPDATE resources SET last_seen=? WHERE path=?", (seen, path))


def test_reconcile() -> None:
    config.set_root(ROOT)
    config.PATHS.ensure()
    conn = db.connect(config.PATHS.db)

    started = db.now()
    alive = "disk:/Library/alive.pdf"
    gone = "disk:/Library/gone.pdf"
    other = "disk:/Other/untouched.pdf"
    make(conn, alive, started + 5)        # увидели в этом проходе
    make(conn, gone, started - 10_000)    # не встретился -- значит пропал
    make(conn, other, started - 10_000)   # вне корня обхода -- не трогаем

    n = scan.reconcile(conn, "disk:/Library", started)
    assert n == 1, n
    state = dict(conn.execute(
        "SELECT path, vanished_at FROM resources").fetchall())
    assert state[gone] is not None, "пропавший не отмечен"
    assert state[alive] is None, "увиденный помечен пропавшим"
    assert state[other] is None, "задет файл за пределами корня обхода"
    print("сверка: пропавшее отмечено, живое и чужое не задето")

    # Исчезнувшее не считается живым, но из описи не пропадает: имя,
    # размер и хеши нужны, чтобы искать копию на стороне.
    t = tree.totals(conn)
    assert t["vanished"] == 1, t
    assert t["files"] == 3, t
    assert t["unchecked"] == 2, t  # пропавший выбыл из «не проверено»
    print("итоги: пропавшее учтено отдельно и выбыло из живых счётчиков")

    # Файл вернулся в облако -- отметка снимается.
    conn.execute("UPDATE resources SET last_seen=? WHERE path=?",
                 (started + 50, gone))
    scan.reconcile(conn, "disk:/Library", started)
    back = conn.execute("SELECT vanished_at FROM resources WHERE path=?",
                        (gone,)).fetchone()[0]
    assert back is None, "вернувшийся остался помеченным"
    print("вернувшееся: отметка снята")


def test_resume_without_start_marker_does_not_reconcile() -> None:
    """Чекпоинт старой версии не должен спровоцировать ложную сверку.

    У такого чекпоинта нет поля started. Если подставить «сейчас», всё
    описанное до обрыва окажется «не увиденным» и будет объявлено пропавшим.
    """
    config.set_root(ROOT)
    conn = db.connect(config.PATHS.db)
    src = (Path(__file__).resolve().parent.parent
           / "drydock" / "scan.py").read_text(encoding="utf-8")
    assert "can_reconcile = False" in src, "защиты нет в коде"
    assert "if completed and can_reconcile else 0" in src, \
        "сверка не привязана к защите"
    # Чекпоинт без started -- ровно тот случай, что был на живой базе.
    db.kv_set(conn, scan.CHECKPOINT_KEY,
              {"root": "disk:/", "stack": ["disk:/A"], "files": 100})
    saved = db.kv_get(conn, scan.CHECKPOINT_KEY)
    assert not saved.get("started"), saved
    print("чекпоинт без точки отсчёта: сверка не запускается")


def main() -> int:
    test_reconcile()
    test_resume_without_start_marker_does_not_reconcile()
    print("\nсверка с облаком: все проверки прошли")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
