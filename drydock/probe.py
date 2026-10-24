"""Прогон проб доступности по выборке.

Отдельный модуль, потому что проба -- не однократное действие. Доступность
файлов в облаке плавает: 10 октября вечером часть того, что днём не
отдавалось, выгрузилась нормально. Значит "недоступен" -- это всегда
"недоступен на момент проверки", и по таким файлам надо ходить повторно,
желательно много раз и в разное время.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time

from . import db

log = logging.getLogger("drydock.probe")
from .msg import job_msg
from .yandex import Disk

# Порядок повторной проверки: сначала то, чего не знаем вовсе, затем
# сбойное (оно и может "ожить"), и только потом подтверждаем живое.
RECHECK_ORDER = """
    CASE
      WHEN p.state IS NULL      THEN 0
      WHEN p.state='api_error'  THEN 1
      WHEN p.state='unknown'    THEN 2
      WHEN p.state='unavailable' THEN 3
      WHEN p.state='gone'       THEN 4
      ELSE 5
    END
"""


def stale_before(hours: float | None = None) -> int:
    """Отметка времени, старше которой результат считается устаревшим."""
    from . import config
    return db.now() - int((config.PROBE_TTL_HOURS if hours is None else hours) * 3600)


def select_paths(conn: sqlite3.Connection, *, under: str | None = None,
                 states: list[str] | None = None, limit: int | None = None,
                 stale_hours: float | None = None,
                 skip_downloaded: bool = True) -> list[str]:
    """Какие файлы проверять.

    stale_hours: не трогать то, что проверено совсем недавно -- на большой
    коллекции это экономит часы.
    """
    where = ["r.type='file'"]
    args: list[object] = []
    if under:
        where.append("(r.path = ? OR r.path LIKE ?)")
        args += [under, under.rstrip("/") + "/%"]
    if states:
        # "stale" -- не состояние файла, а возраст наблюдения: проверен
        # когда-то, но давно. ЦОДы могли отключить частично, и вернуться в
        # строй они могут тоже частично, поэтому ни один вердикт не вечен:
        # всё опрошенное рано или поздно опрашивается заново.
        parts: list[str] = []
        others = [s for s in states if s not in ("unchecked", "stale")]
        if "unchecked" in states:
            parts.append("p.state IS NULL")
        if "stale" in states:
            parts.append("(p.state IS NOT NULL AND p.checked_at < ?)")
            args.append(stale_before(stale_hours))
        if others:
            parts.append(f"p.state IN ({','.join('?' * len(others))})")
            args += others
        if parts:
            where.append("(" + " OR ".join(parts) + ")")
    if stale_hours is not None:
        where.append("(p.checked_at IS NULL OR p.checked_at < ?)")
        args.append(db.now() - int(stale_hours * 3600))
    if skip_downloaded:
        where.append("(l.path IS NULL OR l.verify <> 'ok')")
    # То, что мы удалили из облака сами, спрашивать не о чем: ответ будет
    # 404, и проба запишет "нет на сервере" -- в интерфейсе это неотличимо
    # от файла, убитого аварией. Свой счётчик у таких файлов уже есть.
    where.append("cd.path IS NULL")
    sql = (f"SELECT r.path FROM resources r "
           f"LEFT JOIN probe p ON p.path=r.path "
           f"LEFT JOIN local l ON l.path=r.path "
           f"LEFT JOIN cloud_deleted cd ON cd.path=r.path "
           f"WHERE {' AND '.join(where)} "
           f"ORDER BY {RECHECK_ORDER}, r.size ASC")
    if limit:
        sql += f" LIMIT {int(limit)}"
    return [r["path"] for r in conn.execute(sql, args)]


async def run(conn: sqlite3.Connection, disk: Disk, paths: list[str], *,
              job_id: int | None = None) -> dict:
    counters: dict[str, int] = {}
    lock = asyncio.Lock()
    done = 0
    started = time.monotonic()

    def eta() -> str:
        """Сколько осталось по текущему темпу.

        Цифра «осталось 40 мин» отвечает на вопрос «оно вообще движется?»
        гораздо лучше, чем голый счётчик. Темп берётся из этого же прохода,
        а не из константы: хранилище меняется в разы.
        """
        spent = time.monotonic() - started
        if done < 5 or spent < 1:
            return ""
        rate = done / spent
        left = (len(paths) - done) / rate if rate else 0
        if left < 90:
            return f", {rate:.1f}/с, осталось {int(left)}с"
        return f", {rate:.1f}/с, осталось {int(left / 60)} мин"

    stop = db.CancelWatch(conn, job_id)

    async def one(path: str) -> None:
        nonlocal done
        if stop():
            return  # нажали «стоп»: новые файлы не начинаем
        result = await disk.probe(path)
        async with lock:
            db.record_probe(conn, path, result.state, result.http_status,
                            result.storage_host, result.detail)
            counters[result.state] = counters.get(result.state, 0) + 1
            done += 1
            if job_id is not None and done % 10 == 0:
                db.job_progress(
                    conn, job_id, done, len(paths),
                    job_msg("probe.count", ok=counters.get("ok", 0),
                            bad=(counters.get("unavailable", 0)
                                 + counters.get("gone", 0)),
                            eta=eta()))

    # Порциями, чтобы можно было отменить работу и не держать в памяти
    # десятки тысяч задач сразу. Порция небольшая: отмена проверяется между
    # ними, и на сотне файлов кнопка «стоп» отзывалась с заметной задержкой.
    batch = 25
    async with stop:
        for i in range(0, len(paths), batch):
            if stop():
                counters["cancelled"] = 1
                break
            await asyncio.gather(*(one(p) for p in paths[i:i + batch]))
            if job_id is not None:
                db.job_progress(conn, job_id, min(i + batch, len(paths)), len(paths))
        if stop():
            counters["cancelled"] = 1
    # «Недоступно» и «нет на сервере» -- это РЕЗУЛЬТАТ пробы, а не её
    # провал: задача как раз и выясняла, что отдаётся. Провал -- когда
    # состояние определить не удалось.
    counters["failed"] = (counters.get("api_error", 0)
                          + counters.get("unknown", 0))
    return counters
