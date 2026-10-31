"""Выгрузка файлов в локальное зеркало.

Три правила, которые тут важнее скорости:

1. Структура один в один. Файл ложится по тому же пути, что в облаке.
2. Докачка. Соединение рвётся на раненом хранилище постоянно, поэтому
   пишем в .part и продолжаем с той позиции, где встали.
3. Проверка. API отдаёт md5 и sha256 файла, и мы их сверяем. Это не
   формальность: Яндекс на повреждённых файлах умеет отдать "успешный"
   усечённый ответ, и без сверки в архив уедет огрызок, считающийся спасённым.

Отдельно есть salvage-режим для файлов, которые отдаются частично: читаем
блоками, непрочитанные помечаем дырками и записываем нулями. Из книги на
40 МБ так спасается та часть, которая ещё лежит на живых машинах -- для
PDF и djvu это обычно означает, что часть страниц открывается.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import time
from collections import deque
from pathlib import Path
from threading import Lock

import httpx

from . import config, db
from .msg import job_msg

log = logging.getLogger("drydock.download")
from .localpath import ensure_parent, extended, local_for
from .yandex import Disk


def _hashes(path: Path) -> tuple[str, str]:
    md5, sha = hashlib.md5(), hashlib.sha256()
    with open(extended(path), "rb") as fh:
        while chunk := fh.read(config.BLOCK):
            md5.update(chunk)
            sha.update(chunk)
    return md5.hexdigest(), sha.hexdigest()



# Сколько байт уже занято начатыми выгрузками. Проверка «на файл» при 48
# потоках не работает: каждый видит один и тот же запас в 5 ГБ, все
# проходят проверку и вместе пишут куда больше. 22 октября в 21:30 это и
# случилось -- диск кончился, SQLite упал с «database or disk is full»,
# задача #138 умерла вместе с очередью.
_inflight = 0
_SPACE_LOCK = Lock()


class SpaceClaim:
    """Динамический резерв дискового пространства с защитой от двойного вычитания.

    Раньше резервировался expect_size на весь период выгрузки. Пока файл
    качался, записанные чанки физически уменьшали свободное место на диске,
    а _inflight продолжал держать полный expect_size. При параллельных потоках
    это приводило к ложным 'no_space'. Теперь _inflight держит только
    ЕЩЁ НЕ ЗАПИСАННЫЙ остаток резерва, а существующий .part учитывается сразу.
    """

    def __init__(self, size: int) -> None:
        self.remaining = max(0, size)
        self.claimed = False

    def claim(self) -> bool:
        global _inflight
        with _SPACE_LOCK:
            if self.remaining == 0:
                self.claimed = True
                return True
            if free_space(config.PATHS.files) - self.remaining - _inflight < config.RESERVE:
                return False
            _inflight += self.remaining
            self.claimed = True
            return True

    def on_bytes_written(self, n: int) -> None:
        global _inflight
        with _SPACE_LOCK:
            if not self.claimed or n <= 0 or self.remaining <= 0:
                return
            delta = min(self.remaining, n)
            self.remaining -= delta
            _inflight = max(0, _inflight - delta)

    def release(self) -> None:
        global _inflight
        with _SPACE_LOCK:
            if self.claimed and self.remaining > 0:
                _inflight = max(0, _inflight - self.remaining)
                self.remaining = 0
            self.claimed = False




class SpeedMeter:
    """Измерение мгновенной скорости выгрузки и расчёт ETA."""

    def __init__(self, window_s: float = 3.0) -> None:
        self.window_s = window_s
        self.samples: deque[tuple[float, int]] = deque()
        self.lock = Lock()
        self.bytes_total: int = 0
        self.bytes_done: int = 0

    def record(self, nbytes: int) -> None:
        now = time.monotonic()
        with self.lock:
            self.samples.append((now, nbytes))
            self.bytes_done += nbytes
            cutoff = now - self.window_s
            while self.samples and self.samples[0][0] < cutoff:
                self.samples.popleft()

    def speed(self) -> float:
        now = time.monotonic()
        with self.lock:
            cutoff = now - self.window_s
            while self.samples and self.samples[0][0] < cutoff:
                self.samples.popleft()
            if not self.samples:
                return 0.0
            total = sum(b for _, b in self.samples)
            dt = max(0.2, now - self.samples[0][0])
            return total / dt

    def reset(self, total_bytes: int = 0) -> None:
        with self.lock:
            self.samples.clear()
            self.bytes_total = total_bytes
            self.bytes_done = 0

    def stats(self) -> dict:
        spd = self.speed()
        with self.lock:
            left = max(0, self.bytes_total - self.bytes_done)
            eta = (left / spd) if spd > 1024 and self.bytes_total > 0 else None
            return {
                "speed_bps": round(spd, 1),
                "eta_s": round(eta, 1) if eta is not None else None,
                "bytes_done": self.bytes_done,
                "bytes_total": self.bytes_total,
            }

_GLOBAL_SPEED = SpeedMeter()


def current_stats() -> dict:
    """Текущие метрики скорости и остатка байт для задач выгрузки."""
    return _GLOBAL_SPEED.stats()

def _claim_space(size: int) -> bool:
    """Зарезервировать место под файл с учётом уже начатых выгрузок."""
    global _inflight
    needed = max(0, size)
    with _SPACE_LOCK:
        if free_space(config.PATHS.files) - needed - _inflight < config.RESERVE:
            return False
        _inflight += needed
        return True


def _release_space(size: int) -> None:
    global _inflight
    with _SPACE_LOCK:
        _inflight = max(0, _inflight - size)

def free_space(path: Path) -> int:
    probe = Path(path)
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    return shutil.disk_usage(probe).free


def plan(conn: sqlite3.Connection, paths: list[str]) -> dict:
    """Сколько весит выбранное и что из него реально можно взять."""
    if not paths:
        return {"count": 0, "bytes": 0, "available": 0, "available_bytes": 0,
                "already": 0, "already_bytes": 0, "unavailable": 0}
    qs = ",".join("?" * len(paths))
    rows = conn.execute(
        f"""SELECT r.path, r.size, COALESCE(p.state,'unchecked') AS state,
                   l.verify, l.released
            FROM resources r
            LEFT JOIN probe p ON p.path=r.path
            LEFT JOIN local l ON l.path=r.path
            WHERE r.type='file' AND r.path IN ({qs})""", paths).fetchall()
    out = {"count": 0, "bytes": 0, "available": 0, "available_bytes": 0,
           "already": 0, "already_bytes": 0, "unavailable": 0, "unchecked": 0,
           "unchecked_bytes": 0, "will_try": 0, "will_try_bytes": 0}
    for r in rows:
        size = int(r["size"] or 0)
        out["count"] += 1
        out["bytes"] += size
        if r["verify"] in ("ok", "unverified") and not r["released"]:
            # 'unverified' -- файл перенесён вручную, облако о нём молчит.
            # Он уже на диске: качать нечего, и попытка кончится «нет
            # ссылки» (140 таких файлов зря жгли время 18 октября).
            out["already"] += 1
            out["already_bytes"] += size
        elif r["state"] == "ok":
            out["available"] += 1
            out["available_bytes"] += size
        elif r["state"] in ("unavailable", "gone"):
            out["unavailable"] += 1
        else:
            out["unchecked"] += 1
            out["unchecked_bytes"] += size
    # Сколько файлов РЕАЛЬНО уйдёт в очередь: непроверенные тоже берутся
    # (их состояние неизвестно, а не «недоступно»). Раньше окно обещало
    # только «доступные», и очередь выходила больше обещанного.
    out["will_try"] = out["available"] + out["unchecked"]
    out["will_try_bytes"] = out["available_bytes"] + out["unchecked_bytes"]
    return out


def _record_failure(conn: sqlite3.Connection, path: str,
                    exc: BaseException) -> None:
    """Провал выгрузки -- тоже наблюдение о доступности.

    «Нет ссылки» (404) значит, что файла в облаке нет: пишем gone, чтобы
    интерфейс перестал предлагать его скачивать. «Обрезан» -- хранилище
    отдаёт только начало: unavailable. Сетевые таймауты о самом файле
    ничего не говорят -- их не записываем, этим займётся проба.
    """
    text = f"{exc}"
    try:
        if "нет ссылки" in text or "404" in text:
            db.record_probe(conn, path, "gone", 404, None, text[:200])
        elif "обрезан" in text:
            db.record_probe(conn, path, "unavailable", 500, None, text[:200])
    except Exception:  # noqa: BLE001 - вердикт не должен ронять выгрузку
        log.debug("не записал вердикт пробы для %s", path)


async def download_one(conn: sqlite3.Connection, disk: Disk, path: str, *,
                       attempts: int | None = None,
                       salvage: bool = False, lock: asyncio.Lock | None = None) -> dict:
    row = conn.execute(
        "SELECT size, md5, sha256 FROM resources WHERE path=? AND type='file'",
        (path,)).fetchone()
    if row is None:
        return {"path": path, "state": "unknown_resource"}
    expect_size = int(row["size"] or 0)
    target = local_for(path, config.PATHS.files)
    part = target.with_name(target.name + ".part")

    done = conn.execute("SELECT verify, released FROM local WHERE path=?", (path,)).fetchone()
    # Уже есть на диске -- качать нечего. 'unverified' тоже сюда: это
    # файл, перенесённый вручную, облако о нём молчит, и попытка выгрузки
    # кончается «нет ссылки» (18 октября так зря сгорело 140 файлов).
    if done and done["verify"] in ("ok", "unverified") and not done["released"] \
            and Path(extended(target)).exists():
        return {"path": path, "state": "skipped"}

    part_p = Path(extended(part))
    existing_part = part_p.stat().st_size if part_p.exists() else 0
    needed = max(0, expect_size - existing_part)
    claim = SpaceClaim(needed)
    if not claim.claim():
        return {"path": path, "state": "no_space"}

    try:
        try:
            # ensure_parent внутри try: имя папки тоже под лимитом 255 на
            # компонент, и mkdir на таком имени падает -- файл должен уйти
            # в счётчик failed, а не уронить порцию.
            ensure_parent(target)
            if salvage:
                written, holes = await _salvage(disk, path, part, expect_size,
                                                 claim=claim)
            else:
                written, holes = await _straight(disk, path, part, expect_size,
                                                 attempts, claim=claim)
        except Exception as exc:  # noqa: BLE001 - один файл не роняет порцию
            # Хост в сообщении: без него «getaddrinfo failed» не говорит, кто
            # именно не разрешился -- узел хранилища, которого уже нет в DNS,
            # или локальный резолвер. 22 октября таких строк в логе 452, и
            # разобрать их было нечем.
            host = ""
            req = getattr(exc, "request", None)
            url = getattr(req, "url", None) if req is not None else None
            if url is not None and getattr(url, "host", None):
                host = f" [{url.host}]"
            log.warning("выгрузка %s не удалась: %s: %s%s", path,
                        type(exc).__name__, exc, host)
            _record_failure(conn, path, exc)
            return {"path": path, "state": "failed",
                    "error": f"{type(exc).__name__}: {exc}"}

        md5, sha = await asyncio.to_thread(_hashes, part)
        if holes:
            verify = "salvaged"
        elif ((row["sha256"] and sha.lower() == str(row["sha256"]).lower())
              or (row["md5"] and md5.lower() == str(row["md5"]).lower())):
            verify = "ok"
        elif not row["sha256"] and not row["md5"]:
            verify = "unverified"
        else:
            verify = "mismatch"

        if verify != "ok":
            log.warning("%s: проверка %s (получено %s из %s, дырок %s)",
                        path, verify, written, expect_size, len(holes))
        else:
            log.info("спасён %s (%s байт)", path, written)

        if verify == "mismatch" and written != expect_size:
            # Усечённый ответ: оставляем .part, чтобы докачать, а не выдавать
            # огрызок за спасённый файл.
            return {"path": path, "state": "truncated", "bytes": written,
                    "expected": expect_size}

        os.replace(extended(part), extended(target))
        record = {
            "path": path, "state": verify, "bytes": written,
            "holes": len(holes) if holes else 0,
        }
        async with (lock or asyncio.Lock()):
            save_local(conn, path, target, written, sha, md5, verify, holes)
        return record

    finally:
        claim.release()


def save_local(conn: sqlite3.Connection, path: str, target: Path, written: int,
               sha: str, md5: str, verify: str, holes: list) -> None:
    """Записать спасённую копию. Вынесено ради теста: правило про
    salvaged_at (отметку полная докачка не стирает) должно быть
    проверяемым, а не зашитым в середину выгрузки."""
    conn.execute(
        """INSERT INTO local(path,local_path,bytes,sha256,md5,verify,holes,
                             salvaged_at,downloaded_at,released)
           VALUES(?,?,?,?,?,?,?,?,?,0)
           ON CONFLICT(path) DO UPDATE SET
             local_path=excluded.local_path, bytes=excluded.bytes,
             sha256=excluded.sha256, md5=excluded.md5, verify=excluded.verify,
             holes=excluded.holes, downloaded_at=excluded.downloaded_at, released=0,
             -- Полная докачка отметку не стирает: именно она и говорит,
             -- что файл когда-то был с дырками и его вылечили.
             salvaged_at=CASE WHEN excluded.salvaged_at > 0
                              THEN excluded.salvaged_at ELSE local.salvaged_at END""",
        (path, str(target), written, sha, md5, verify,
         json.dumps(holes) if holes else None,
         db.now() if holes else 0, db.now()))


async def _straight(disk: Disk, path: str, part: Path, expect: int,
                    attempts: int | None = None, *,
                    claim: SpaceClaim | None = None) -> tuple[int, list]:
    """Обычная выгрузка: докачка и повторы ВНУТРИ задачи.

    Хранилище рвёт передачу на середине (ReadTimeout, «peer closed
    connection without sending complete message body»). До этой правки
    каждая такая смерть означала «файл не скачался», и лечилось это
    только перезапуском задачи целиком: 18 октября так потерялось 67
    файлов из 250 за один сеанс.

    Теперь попытка повторяется до DOWNLOAD_ATTEMPTS раз, каждая берёт
    СВЕЖУЮ ссылку (open_stream делает это сам -- возможно, другая машина
    хранилища) и продолжает с текущего размера .part. Прогресс между
    попытками накапливается, поэтому даже три обрыва на 200 МБ оставляют
    600 МБ на диске, а не ноль.
    """
    start = 0
    if Path(extended(part)).exists():
        start = Path(extended(part)).stat().st_size
        if expect and start >= expect:
            start = 0  # недоверенный остаток прошлой попытки -- начинаем заново
    written = start
    last_exc: BaseException | None = None
    stalled = 0  # попыток подряд без прироста
    tries = attempts or config.DOWNLOAD_ATTEMPTS
    for attempt in range(tries):
        if expect and written >= expect:
            break
        before = written
        try:
            written = await _pull(disk, path, part, written, expect, claim=claim)
        except (httpx.TimeoutException, httpx.TransportError, OSError) as exc:
            last_exc = exc
            text = f"{exc}"
            if "нет ссылки" in text or "404" in text:
                # Файла в облаке нет. Повтор ссылку не создаст, и
                # превращать это в «обрезан» нельзя: причина другая.
                raise
            # Размер .part перечитываем: _pull писал на диск по кускам, и
            # на обрыве там уже лежит больше, чем мы знали. Взять старый
            # счётчик -- значит на повторе начать с нуля и потерять всё,
            # что успело скачаться.
            p = Path(extended(part))
            written = p.stat().st_size if p.exists() else 0
            stalled = 0 if written > before else stalled + 1
            log.info("докачка %s: попытка %s/%s оборвалась (%s: %s), "
                     "продолжаю с %s байт", path, attempt + 1,
                     tries, type(exc).__name__,
                     str(exc)[:80], written)
            # Молчание с самого начала: не отдано ни байта, и это ReadTimeout
            # (узел принял соединение и замер). Второй такой же таймаут --
            # чистая потеря времени: 22 октября так горело по 12-40 с на
            # файл в режиме «скачать выбранное». Отказ соединения
            # (ConnectTimeout/ConnectError) по-прежнему повторяем: он часто
            # транзиентный.
            if written == 0 and before == 0 and isinstance(exc, httpx.ReadTimeout):
                raise OSError(
                    f"хранилище молчит, не отдав ни байта из {expect}") from exc
            if stalled >= 2:
                # Хранилище рвёт на ОДНОМ И ТОМ ЖЕ смещении: Range оно
                # уважает, но дальше не отдаёт (проверено 18 октября:
                # 51910 из 1244840 при любом старте). Ещё три попытки --
                # это две минуты простоя на файл, который ими не спасётся.
                raise OSError(
                    f"хранилище отдаёт только первые {written} из {expect} "
                    f"байт -- файл обрезан на машине хранилища") from exc
            await asyncio.sleep(min(2 ** attempt, 10))
            continue
        if expect and written < expect:
            # Сервер закрыл поток раньше конца без ошибки -- это тот же
            # обрыв, только тихий. Дотягиваем.
            stalled = 0 if written > before else stalled + 1
            log.info("докачка %s: поток закрылся на %s из %s байт, "
                     "продолжаю", path, written, expect)
            if stalled >= 2:
                raise OSError(
                    f"хранилище отдаёт только первые {written} из {expect} "
                    f"байт -- файл обрезан на машине хранилища")
            await asyncio.sleep(min(2 ** attempt, 10))
            continue
        break
    else:
        # Попытки кончились. .part остаётся с накопленным прогрессом --
        # следующий запуск задачи продолжит, а не начнёт с нуля.
        if last_exc is not None:
            raise last_exc
        raise OSError(f"не докачалось: {written} из {expect} байт")
    return written, []


async def _pull(disk: Disk, path: str, part: Path, written: int,
                expect: int, *, claim: SpaceClaim | None = None) -> int:
    """Один заход: свежая ссылка, продолжение с written."""
    stream = await disk.open_stream(path, start=written)
    async with stream as resp:
        if resp.status_code not in (200, 206):
            body = (await resp.aread()).decode("utf-8", "replace")[:200]
            raise OSError(f"HTTP {resp.status_code}: {body}")
        # 200 в ответ на Range значит, что хранилище проигнорировало
        # смещение и шлёт файл с начала. Обрезать .part в ноль нельзя:
        # если поток умрёт на первом байте, потеряется всё накопленное
        # (так и случилось 18 октября -- 51910 байт стали нулём).
        # Вместо этого пропускаем уже скачанную часть в потоке.
        skip = written if (written and resp.status_code == 200) else 0
        mode = "ab" if written else "wb"
        with open(extended(part), mode) as fh:  # noqa: ASYNC230 - буферизованная запись на локальный диск
            seen = 0
            # Предел на МОЛЧАНИЕ, а не на весь запрос. Мёртвая машина
            # хранилища отдаёт кусок и замирает; без этого предела мы
            # досиживали до общего таймаута -- десятки секунд на файл,
            # который всё равно не придёт.
            chunks = resp.aiter_bytes(config.BLOCK)
            while True:
                limit = (config.DOWNLOAD_FIRST_BYTE_S if written == 0
                         else config.DOWNLOAD_STALL_S)
                try:
                    chunk = await asyncio.wait_for(anext(chunks), timeout=limit)
                except StopAsyncIteration:
                    break
                except TimeoutError as exc:
                    raise OSError(
                        f"хранилище молчит {limit:.0f}с после {written} из "
                        f"{expect} байт") from exc
                if skip:
                    if seen + len(chunk) <= skip:
                        seen += len(chunk)
                        continue
                    chunk = chunk[skip - seen:]
                    skip = 0
                fh.write(chunk)
                written += len(chunk)
                _GLOBAL_SPEED.record(len(chunk))
                if claim is not None:
                    claim.on_bytes_written(len(chunk))
    return written


async def _salvage(disk: Disk, path: str, part: Path, expect: int, *,
                     claim: SpaceClaim | None = None) -> tuple[int, list]:
    """Поблочное чтение с пропуском мёртвых участков.

    Повторяет приём из yandexdl: блок, который не отдаётся, пропускается,
    остальные пишутся на свои места. Файл выходит с дырками, но читаемая
    часть содержимого спасена -- это лучше, чем ничего.
    """
    if not expect:
        return await _straight(disk, path, part, expect)
    href, status, detail = await disk.download_href(path)
    if href is None:
        raise OSError(f"нет ссылки: HTTP {status} {detail}")
    holes: list[list[int]] = []
    written = 0
    with open(extended(part), "wb") as fh:  # noqa: ASYNC230 - буферизованная запись на локальный диск
        fh.truncate(expect)
        if claim is not None:
            claim.on_bytes_written(expect)
        for start in range(0, expect, config.BLOCK):
            end = min(start + config.BLOCK, expect) - 1
            try:
                async with disk.open_range(href, start, end) as resp:
                    if resp.status_code not in (200, 206):
                        await resp.aread()
                        holes.append([start, end])
                        continue
                    fh.seek(start)
                    got = 0
                    async for chunk in resp.aiter_bytes(config.BLOCK):
                        fh.write(chunk)
                        got += len(chunk)
                        _GLOBAL_SPEED.record(len(chunk))
                    written += got
            except (httpx.TimeoutException, httpx.TransportError):
                holes.append([start, end])
    return written, holes


def _pending_where(paths: list[str] | None,
                   cooldown_min: float) -> tuple[list[str], list[object]]:
    """Условия очереди круга: одно место для списка и для счётчика."""
    where = [
        "r.type='file'",
        "r.vanished_at IS NULL",
        "cd.path IS NULL",
        ("(l.path IS NULL OR l.missing=1 OR l.released=1"
         " OR l.verify NOT IN ('ok','unverified'))"),
    ]
    args: list[object] = []
    if cooldown_min:
        # К файлу, провалившемуся минуту назад, возвращаться в следующем же
        # круге незачем: за минуту раненое хранилище не чинится, а круг на
        # этом буксует. Пусть отлежится -- следующие круги станут короче и
        # пойдут по тем, у кого есть шанс.
        where.append("(p.checked_at IS NULL OR p.state='ok' OR p.checked_at < ?)")
        args.append(db.now() - int(cooldown_min * 60))
    if paths:
        where.append(f"r.path IN ({','.join('?' * len(paths))})")
        args += paths
    # «Gone» -- это 404 GoneError: облако отвечает, что ресурса нет. Это не
    # больная машина хранилища, которую стоит попробовать снова через
    # минуту, а прямой ответ API. 20 октября из 26 785 файлов 20 418
    # стояли в состоянии gone, и круг перебирал их круг за кругом: 404
    # отдаётся мгновенно, но на десяти тысячах файлов это лишние полчаса
    # каждого раунда, потраченные на уже известное. Gone перепроверяется
    # раз в сутки -- на случай, если Яндекс ресурсы вернёт.
    where.append("(p.state IS NULL OR p.state<>'gone' OR p.checked_at < ?)")
    args.append(db.now() - config.GONE_RECHECK_S)
    return where, args


def pending_count(conn: sqlite3.Connection,
                  paths: list[str] | None = None, *,
                  cooldown_min: float = 0) -> int:
    """Сколько файлов возьмёт круг -- не выгружая сами пути."""
    where, args = _pending_where(paths, cooldown_min)
    row = conn.execute(
        f"""SELECT COUNT(*) AS n FROM resources r
            LEFT JOIN local l ON l.path=r.path
            LEFT JOIN cloud_deleted cd ON cd.path=r.path
            LEFT JOIN probe p ON p.path=r.path
            WHERE {' AND '.join(where)}""", args).fetchone()
    return int(row["n"] or 0)


def pending_targets(conn: sqlite3.Connection,
                    paths: list[str] | None = None, *,
                    cooldown_min: float = 0) -> list[str]:
    """Что ещё не спасено -- БЕЗ оглядки на пробу.

    В этом и смысл кругового режима: попытка скачать сама по себе и есть
    проверка доступности, причём честнее пробы -- она читает файл целиком,
    а не первый байт. 19 октября замер показал, что хранилище охотно
    отдаёт первые мегабайты и обрывается на середине; проба такое
    пропускает, выгрузка -- нет.

    Из очереди выпадает только то, что брать неоткуда или незачем: уже
    лежащее на диске, исчезнувшее из облака и удалённое нами самими.
    """
    where, args = _pending_where(paths, cooldown_min)
    return [r["path"] for r in conn.execute(
        f"""SELECT r.path FROM resources r
            LEFT JOIN local l ON l.path=r.path
            LEFT JOIN cloud_deleted cd ON cd.path=r.path
            LEFT JOIN probe p ON p.path=r.path
            WHERE {' AND '.join(where)}
            ORDER BY r.size ASC""", args)]


async def run_rounds(conn: sqlite3.Connection, disk: Disk,
                     paths: list[str] | None = None, *, salvage: bool = False,
                     job_id: int | None = None,
                     pause_s: int = 60, max_rounds: int = 0) -> dict:
    """Круг за кругом, пока не нажмут «стоп».

    Зачем так. Доступность в этом облаке гниёт и возвращается: из 60
    перепроверенных записей 14 перешли из «недоступно» в «доступно», а
    обратный переход за часы измеряли в ~20%. Значит один проход ничего не
    решает, а проба перед каждым проходом -- это лишний час на коллекцию,
    потраченный ровно на то, что выгрузка выяснит и так.

    Очередь пересобирается КАЖДЫЙ круг: спасённое в прошлом круге выпадает
    само, исчезнувшее из облака тоже. Поэтому круги укорачиваются, а не
    молотят одно и то же.
    """
    stop = db.CancelWatch(conn, job_id)
    rounds = 0
    saved_total = 0
    failed_total = 0
    no_space = False
    history: list[int] = []

    async def nap(seconds: int) -> None:
        """Пауза между кругами, прерываемая «стопом»."""
        for _ in range(max(1, seconds * 2)):
            if stop():
                return
            await asyncio.sleep(0.5)

    async with stop:
        while not stop():
            targets = pending_targets(conn, paths,
                                      cooldown_min=config.LOOP_COOLDOWN_MIN)
            rounds += 1
            if not targets:
                # Брать нечего -- но режим вечный: ждём и смотрим снова.
                # Что-то могло вернуться в облако или освободиться место.
                if job_id is not None:
                    db.job_progress(conn, job_id, 0, 0,
                                    job_msg("loop.empty", n=rounds))
                if max_rounds and rounds >= max_rounds:
                    break
                await nap(pause_s)
                continue

            log.info("круг %s: в очереди %s файлов", rounds, len(targets))
            if job_id is not None:
                db.job_progress(conn, job_id, 0, len(targets),
                                job_msg("loop.queue", n=rounds,
                                        k=len(targets)))
            res = await run(conn, disk, targets, salvage=salvage,
                            job_id=job_id, attempts=config.LOOP_ATTEMPTS)
            got = int(res.get("ok", 0) or 0)
            saved_total += got
            failed_total += int(res.get("failed", 0) or 0)
            # Диск полон: следующий круг упрётся в то же место через
            # минуту. Молча крутиться вхолостую -- хуже, чем остановиться
            # и сказать, что случилось.
            no_space = bool(res.get("no_space"))
            history.append(got)
            log.info("круг %s: спасено %s (всего за режим %s)",
                     rounds, got, saved_total)
            if job_id is not None:
                db.job_progress(
                    conn, job_id, len(targets), len(targets),
                    job_msg("loop.saved", n=rounds, got=got,
                            total=saved_total, full=bool(no_space)))
            if no_space:
                log.warning("круг %s остановлен: свободного места меньше "
                            "запаса", rounds)
                break
            if res.get("cancelled") or stop():
                break
            if max_rounds and rounds >= max_rounds:
                break
            # Пауза нужна: без неё круг, в котором всё провалилось, начнётся
            # мгновенно и превратится в долбёжку по раненому хранилищу.
            if got == 0:
                await nap(pause_s)

    return {"rounds": rounds, "saved": saved_total, "failed": failed_total,
            "no_space": no_space, "per_round": history[-20:],
            "stopped": bool(stop())}


# Что считается провалом выгрузки. «skipped» -- не провал (файл уже на
# диске), «no_space» считается отдельно: у него своя причина и своё
# сообщение. Раньше наружу уходили только счётчики по состояниям, а
# _job_state искал ключ failed -- и задача с нулём спасённых отчитывалась
# «готово».
DOWNLOAD_FAILURES = ("failed", "truncated", "mismatch", "unknown_resource")


async def run(conn: sqlite3.Connection, disk: Disk, paths: list[str], *,
              salvage: bool = False, job_id: int | None = None,
              attempts: int | None = None) -> dict:
    counters: dict[str, int] = {}
    lock = asyncio.Lock()
    done = 0
    # Мелкие вперёд: при нехватке места успеваем спасти больше штук.
    qs = ",".join("?" * len(paths))
    ordered = [r["path"] for r in conn.execute(
        f"SELECT path FROM resources WHERE path IN ({qs}) AND type='file' "
        f"ORDER BY size ASC", paths)] if paths else []

    stop = db.CancelWatch(conn, job_id)

    async def one(path: str) -> None:
        nonlocal done
        if stop():
            return  # нажали «стоп»: новые файлы не начинаем
        try:
            result = await download_one(conn, disk, path, salvage=salvage,
                                        lock=lock, attempts=attempts)
        except Exception as exc:  # noqa: BLE001 - один файл не роняет порцию
            log.warning("выгрузка %s не удалась: %s: %s", path,
                        type(exc).__name__, exc)
            result = {"path": path, "state": "failed",
                      "error": f"{type(exc).__name__}: {exc}"}
        async with lock:
            counters[result["state"]] = counters.get(result["state"], 0) + 1
            done += 1
            if job_id is not None and done % 5 == 0:
                db.job_progress(conn, job_id, done, len(ordered),
                                f"спасено {counters.get('ok', 0)}")

    total_bytes = 0
    if ordered:
        try:
            total_bytes = sum(int(r["size"] or 0) for r in conn.execute(
                f"SELECT size FROM resources WHERE path IN ({qs}) AND type='file'", paths))
        except Exception:  # noqa: BLE001
            total_bytes = 0
    _GLOBAL_SPEED.reset(total_bytes=total_bytes)

    try:
        async with stop:
            # Порция -- это ширина параллельности: gather ждёт ВСЮ порцию, и
            # порция в 20 сводила на нет лимит в 48 (замер 19 октября: 48
            # потоков не дали ничего, потому что работало всё равно 20).
            # Берём по размеру лимита, но не меньше 20 -- иначе остановка
            # ждала бы самый медленный файл слишком долго.
            batch = max(20, getattr(disk, "limit", 0) or config.CONCURRENCY)
            for i in range(0, len(ordered), batch):
                if stop():
                    counters["cancelled"] = 1
                    break
                await asyncio.gather(*(one(p) for p in ordered[i:i + batch]))
                if job_id is not None:
                    db.job_progress(conn, job_id, min(i + batch, len(ordered)),
                                    len(ordered))
                if counters.get("no_space"):
                    break
            if stop():
                counters["cancelled"] = 1
        counters["failed"] = count_failures(counters)
        return counters
    finally:
        _GLOBAL_SPEED.reset()


def count_failures(counters: dict) -> int:
    """Сколько файлов выгрузка не взяла -- по её же словарю состояний."""
    return sum(int(counters.get(st, 0) or 0) for st in DOWNLOAD_FAILURES)
