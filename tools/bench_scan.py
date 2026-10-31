"""Замер: опись облака с пустыми папками -- по одной папке и пачками.

Строим облако из 4000 папок, из них 3000 пустых (как в живой коллекции,
где файлы вытащили, а папки остались), и 40 файлов. Ответ "сервера" --
50 мс, как у Яндекса. Сравниваем обход по одной папке и пачками.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(tempfile.mkdtemp(prefix="cr-bench-"))
os.environ["DRYDOCK_ROOT"] = str(ROOT)
os.environ["DRYDOCK_SECRETS"] = str(ROOT / "secrets.bin")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from drydock import db
from drydock.scan import scan
from drydock.yandex import Disk

FOLDERS = 4000
EMPTY = 3000
FILES = 40
LATENCY = 0.05


def build_cloud() -> dict:
    """Облако: пустые папки и файлы рядом с ними."""
    items = []
    for i in range(FOLDERS):
        items.append({"path": f"disk:/D{i:04d}", "name": f"D{i:04d}",
                      "type": "dir", "modified": "2026-10-01T00:00:00Z"})
    for i in range(FILES):
        items.append({"path": f"disk:/file{i:02}.txt", "name": f"file{i:02}.txt",
                      "type": "file", "size": 100})
    return {"disk:/": items}


def make_disk(listings: dict) -> Disk:
    disk = Disk("bench-token")
    calls = {"n": 0}

    async def listdir(path: str, *, offset: int = 0, limit: int = 500) -> dict:
        calls["n"] += 1
        await asyncio.sleep(LATENCY)
        items = listings.get(path, [])
        return {"type": "dir", "name": path.rsplit("/", 1)[-1], "path": path,
                "modified": "2026-10-01T00:00:00Z",
                "_embedded": {"total": len(items),
                              "items": items[offset:offset + limit]}}

    disk.listdir = listdir  # type: ignore[method-assign]
    disk._calls = calls  # type: ignore[attr-defined]
    return disk


async def run(concurrency: int, label: str, with_db: bool) -> tuple[float, int]:
    listings = build_cloud()
    disk = make_disk(listings)
    conn = db.connect(ROOT / f"bench-{concurrency}-{with_db}.db")
    started = time.monotonic()
    if with_db:
        await scan(conn, disk, concurrency=concurrency)
    else:
        async for _item in disk.walk("disk:/", concurrency=concurrency):
            pass
    took = time.monotonic() - started
    print(f"  {label}: {took:6.1f} с, запросов {disk._calls['n']}")
    return took, disk._calls["n"]


async def run_twice(concurrency: int) -> tuple[float, float, int]:
    """Первый проход -- весь обход, второй -- с пропуском пустых папок."""
    listings = build_cloud()
    disk = make_disk(listings)
    conn = db.connect(ROOT / f"bench-twice-{concurrency}.db")
    started = time.monotonic()
    await scan(conn, disk, concurrency=concurrency)
    first = time.monotonic() - started
    started = time.monotonic()
    result = await scan(conn, disk, concurrency=concurrency)
    second = time.monotonic() - started
    print(f"  пачками по {concurrency}: первый проход {first:6.1f} с, "
          f"повторный {second:6.1f} с, запросов во втором "
          f"{disk._calls['n'] - FOLDERS - 1}, пропущено пустых "
          f"{result.get('skipped_empty')}")
    return first, second, disk._calls["n"]


def main() -> int:
    print(f"Облако: {FOLDERS} папок (из них {EMPTY} пустых), {FILES} файлов, "
          f"ответ сервера {int(LATENCY * 1000)} мс\n")
    print("Обход без записи в базу:")
    seq, _ = asyncio.run(run(1, "по одной папке ", False))
    par, _ = asyncio.run(run(8, "восемь сразу  ", False))
    print(f"  ускорение: {seq / par:.1f}x\n")
    print("Полная опись (обход + запись в базу):")
    seq2, _ = asyncio.run(run(1, "по одной папке ", True))
    par2, _ = asyncio.run(run(8, "восемь сразу  ", True))
    print(f"  ускорение: {seq2 / par2:.1f}x\n")
    print("Повторный проход (пустые папки уже известны):")
    asyncio.run(run_twice(8))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
