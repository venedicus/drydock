"""Режим «по кругу»: повторяет проходы и слушается «стоп».

Режим вечный по замыслу, поэтому главное здесь -- не то, что он качает, а
то, что он ОСТАНАВЛИВАЕТСЯ. Задача без выхода, которую нельзя прервать, --
это ровно та беда, что случилась с 7z: он пережил отмену и работал
пятнадцать часов.

Второе по важности -- очередь пересобирается каждый круг. Иначе режим
молотил бы по уже спасённому до скончания века.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

try:
    import pytest
except ImportError:
    pytest = None

ROOT = Path(tempfile.mkdtemp(prefix="cr-loop-"))
os.environ["DRYDOCK_ROOT"] = str(ROOT)
os.environ["DRYDOCK_SECRETS"] = str(ROOT / "secrets.bin")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from drydock import config, db, download

if pytest is not None:

    @pytest.fixture(autouse=True, scope="module")
    def _own_root():
        config.set_root(ROOT)
        yield


class FakeDisk:
    """Диск, который ничего не отдаёт: круги идут вхолостую."""

    def __init__(self) -> None:
        self.calls = 0

    async def aclose(self) -> None:
        return None

    async def open_stream(self, path: str, *, start: int = 0):
        # Изображаем раненое хранилище: ссылку не даёт. Именно так ведут
        # себя мёртвые файлы, ради которых режим и существует.
        self.calls += 1
        raise OSError("нет ссылки: HTTP 500 (заглушка)")


def seed(conn, n: int = 5) -> None:
    for i in range(n):
        db.upsert_resource(conn, {"path": f"disk:/book{i}.pdf",
                                  "name": f"book{i}.pdf", "type": "file",
                                  "size": 100, "md5": "m", "sha256": "s"})


def test_targets_exclude_what_is_done(tmp_conn) -> None:
    conn = tmp_conn
    seed(conn, 4)
    assert len(download.pending_targets(conn)) == 4

    # Спасённое выпадает из очереди...
    conn.execute(
        """INSERT INTO local(path,local_path,bytes,sha256,md5,verify,
                             downloaded_at,released,missing)
           VALUES('disk:/book0.pdf','x',100,'s','m','ok',1,0,0)""")
    # ...исчезнувшее из облака тоже...
    conn.execute("UPDATE resources SET vanished_at=1 WHERE path='disk:/book1.pdf'")
    # ...и удалённое нами самими.
    conn.execute("""INSERT INTO cloud_deleted(path,deleted_at,permanently)
                    VALUES('disk:/book2.pdf',1,1)""")
    left = download.pending_targets(conn)
    assert left == ["disk:/book3.pdf"], left
    print("очередь круга: спасённое, пропавшее и удалённое выпадают")


def test_loop_stops_when_asked(tmp_conn) -> None:
    """Вечный режим обязан прерываться, и быстро."""
    conn = tmp_conn
    seed(conn, 3)
    job = db.job_start(conn, "download-loop", 3)

    async def scenario() -> float:
        async def ask_stop() -> None:
            await asyncio.sleep(1.0)
            conn.execute("UPDATE jobs SET cancel=1 WHERE id=?", (job,))

        started = time.monotonic()
        asyncio.create_task(ask_stop())
        # pause_s большой нарочно: если «стоп» не прерывает паузу, проверка
        # провалится по времени, а не повиснет навсегда.
        await asyncio.wait_for(
            download.run_rounds(conn, FakeDisk(), None, job_id=job,
                                pause_s=600),
            timeout=30)
        return time.monotonic() - started

    spent = asyncio.run(scenario())
    assert spent < 25, f"остановка заняла {spent:.1f}с"
    row = conn.execute("SELECT cancel FROM jobs WHERE id=?", (job,)).fetchone()
    assert row["cancel"] == 1
    print(f"круговой режим остановился за {spent:.1f}с, а не завис навсегда")


def test_loop_ends_when_nothing_left(tmp_conn) -> None:
    """Пустая очередь не крутится вхолостую без ограничения кругов."""
    conn = tmp_conn
    res = asyncio.run(download.run_rounds(
        conn, FakeDisk(), None, job_id=None, pause_s=5, max_rounds=1))
    assert res["rounds"] == 1, res
    assert res["saved"] == 0, res
    print("пустая очередь: круг отработал и не зациклился")


def test_loop_stops_on_full_disk(tmp_conn) -> None:
    """Полный диск останавливает режим, а не крутит его вхолостую.

    Раньше no_space терялся внутри run(): круг видел «спасено 0» и уходил
    в паузу, повторяя то же самое каждую минуту. Диск сам не освободится.
    """
    conn = tmp_conn
    seed(conn, 2)
    job = db.job_start(conn, "download-loop", 2)
    real_run = download.run

    async def fake_run(*_args, **_kwargs) -> dict:
        return {"ok": 0, "failed": 2, "no_space": 1}

    download.run = fake_run
    try:
        res = asyncio.run(asyncio.wait_for(
            download.run_rounds(conn, FakeDisk(), None, job_id=job,
                                pause_s=600),
            timeout=30))
    finally:
        download.run = real_run
    assert res["no_space"] is True, res
    assert res["rounds"] == 1, res
    assert res["failed"] == 2, res
    print("полный диск: круг остановился на первом проходе")


def test_failures_are_counted_by_state() -> None:
    """Провал выгрузки -- это её состояния, а не чужой ключ failed."""
    counters = {"ok": 5, "salvaged": 2, "skipped": 3, "failed": 4,
                "truncated": 1, "mismatch": 2, "unknown_resource": 1,
                "no_space": 1}
    assert download.count_failures(counters) == 8, download.count_failures(counters)
    assert download.count_failures({"ok": 3}) == 0
    print("провалы считаются по состояниям выгрузки")


def _fresh_conn():
    import uuid
    path = ROOT / f"t{uuid.uuid4().hex[:8]}.db"
    return db.connect(path)


if pytest is not None:
    @pytest.fixture
    def tmp_conn():
        return _fresh_conn()


def main() -> int:
    config.set_root(ROOT)
    config.PATHS.ensure()
    test_targets_exclude_what_is_done(_fresh_conn())
    test_loop_stops_when_asked(_fresh_conn())
    test_loop_ends_when_nothing_left(_fresh_conn())
    test_loop_stops_on_full_disk(_fresh_conn())
    test_failures_are_counted_by_state()
    print("\nрежим по кругу: все проверки прошли")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
