"""Локальный web UI: дерево коллекции, выбор, прогресс.

Сервер держит одно соединение с базой и запускает длинные операции
asyncio-задачами: всё, что мы делаем, упирается в сеть, а не в процессор.
Прогресс пишется в таблицу jobs, интерфейс его опрашивает -- так состояние
переживает перезагрузку страницы и даже перезапуск сервера.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import csv
import hashlib
import io
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import archive as archive_mod
from . import cloud, config, db, download, logging_setup, oauth, probe, scan, secretstore, tree
from . import health as health_mod
from .localpath import extended, local_for
from .msg import job_msg
from .yandex import Disk

app = FastAPI(title="Drydock")
WEB = Path(__file__).resolve().parent.parent / "web"

# Порт, на котором нас запустили: от него зависит redirect URI, который
# Яндекс должен знать заранее. Меняется в cli.serve.
SERVE_PORT = oauth.DEFAULT_PORT

_conn = None
_tasks: dict[int, concurrent.futures.Future] = {}
# Петля, в которой крутится сервер. Ловится при старте: обработчики-`def`
# живут в потоках пула, и дотянуться до неё иначе неоткуда.
MAIN_LOOP: asyncio.AbstractEventLoop | None = None


log = logging.getLogger("drydock.server")


def conn():
    global _conn
    if _conn is None:
        config.PATHS.ensure()
        _conn = db.connect(config.PATHS.db)
    return _conn


def _repair_deleted_probe(conn) -> int:
    """Файлы, удаленные из облака программой, не должны выглядеть живыми.

    Момент удаления пишет вердикт сразу (cloud.delete), но пока этой
    правки не было, удаление оставляло пробу как была: к 18 октября
    427 файлов показывались «доступными», хотя в облаке их уже не было.
    Разовый проход при старте доворачивает исторический хвост.
    """
    cur = conn.execute(
        "UPDATE probe SET state='gone', http_status=404, "
        "detail='удалено нами из облака', checked_at=? "
        "WHERE path IN (SELECT path FROM cloud_deleted) "
        "AND state IS NOT 'gone'", (db.now(),))
    if cur.rowcount:
        log.warning("своё удаление помечено в пробе gone: %s", cur.rowcount)
    return cur.rowcount


@app.post("/api/local/sync")
def local_sync() -> dict:
    """Сверить зеркало с диском прямо сейчас (обход -- секунды).

    Нужно, когда человек только что переложил файлы в папку спасения и
    хочет сразу видеть правду, не дожидаясь фоновой сверки.
    """
    from . import localwatch
    # Своё соединение: сверка держит транзакцию, и на общем соединении в
    # неё попадали бы записи из петли событий (пробы, прогресс задач).
    c = db.connect(config.PATHS.db)
    try:
        return localwatch.sync(c)
    finally:
        c.close()


class AutopilotBody(BaseModel):
    on: bool


@app.post("/api/autopilot")
def set_autopilot(body: AutopilotBody) -> dict:
    """Включить или выключить автопилот: перепроверку недоступного и забор
    ожившего. Круг идёт раз в несколько часов и только когда программа
    простаивает."""
    c = conn()
    db.kv_set(c, "autopilot", bool(body.on))
    # Время последнего круга сбрасываем: выключение и включение не должно
    # запускать круг немедленно.
    db.kv_set(c, "autopilot_last", int(time.time()))
    return {"on": bool(body.on), "hours": config.AUTOPILOT_INTERVAL_H,
            "batch": config.AUTOPILOT_BATCH}


@app.get("/api/settings")
def get_settings() -> dict:
    """Куда программа спасает сейчас -- и откуда это взялось."""
    from_env = bool(os.environ.get("DRYDOCK_ROOT"))
    chosen = config.settings().get("save_root")
    return {
        # Действующий корень этого запуска.
        "save_root": str(config.PATHS.root),
        # Что выбрано на следующий запуск (если выбирали).
        "chosen_root": str(chosen) if chosen else None,
        "default_root": str(config.DEFAULT_SAVE_ROOT),
        # Переменная окружения сильнее выбора в окне: если она задана,
        # смена в интерфейсе не применится -- и человек должен это видеть.
        "locked_by_env": from_env,
        "chosen_in_ui": bool(chosen),
        # Порт: действующий, выбранный на следующий запуск и признак того,
        # что его задала переменная окружения (тогда окно не переспорит).
        "port": config.port(),
        "port_from_env": bool(os.environ.get("DRYDOCK_PORT")),
        "db": str(config.PATHS.db),
    }


class SettingsBody(BaseModel):
    save_root: str
    port: int | None = None


@app.post("/api/settings")
def set_settings(body: SettingsBody) -> dict:
    """Выбрать корень спасения и порт окна. Применяются при следующем запуске.

    Переноса данных нет намеренно: 22 ГБ файлов и 278 МБ базы -- это
    осознанное действие человека, а не счастливая случайность при клике.
    """
    raw = body.save_root.strip()
    if not raw:
        raise HTTPException(400, {"code": "err.emptyPath"})
    p = Path(raw)
    if not p.is_absolute():
        raise HTTPException(400, {"code": "err.fullPath"})
    data = config.settings()
    data["save_root"] = str(p)
    if body.port is not None:
        # Порт проверяем здесь: 80 и 70000 одинаково не годятся.
        if not 1024 <= body.port <= 65535:
            raise HTTPException(400, {"code": "err.badPort"})
        data["port"] = int(body.port)
    config.save_settings(data)
    log.info("выбран новый корень спасения: %s (применится при перезапуске)", p)
    out = get_settings()
    # Отдельно и явно: что применится при следующем запуске, чтобы
    # интерфейс не показывал старый действующий корень как сохранённый.
    out["chosen_root"] = str(p)
    out["restart_required"] = True
    return out


@app.on_event("startup")
async def _startup() -> None:
    global MAIN_LOOP
    logging_setup.setup()
    logging_setup.install_asyncio_handler()
    MAIN_LOOP = asyncio.get_running_loop()
    # uvicorn ставит своим логгерам propagate=False и пишет трейсбеки в
    # собственный stderr. Под pythonw стандартного вывода нет вовсе, и
    # ошибка 500 исчезала бесследно -- включаем передачу в наш файл.
    logging_setup.capture_uvicorn()
    # Задачи, пережившие прошлый запуск: процесс убит, а в базе они всё ещё
    # "running". Без этого интерфейс показывает вечную полоску, по которой
    # не понять, работает что-то или давно умерло.
    #
    # Но только если рядом не работает ДРУГОЙ экземпляр: второй сервер на
    # другом порту (`cr.bat serve` при открытом окне) иначе пометил бы
    # чужую живую выгрузку прерванной -- на многочасовой задаче это выглядит
    # как потеря работы. Живость определяем по отметке, которую сервер
    # обновляет раз в 10 секунд.
    beat = db.kv_get(conn(), "server_heartbeat") or 0
    if db.now() - int(beat) < 30:
        log.warning("рядом работает другой экземпляр -- чужие задачи не трогаю")
    else:
        cur = conn().execute(
            "UPDATE jobs SET state='interrupted', finished_at=?, "
            "message=COALESCE(message, ?) "
            "WHERE state='running'", (job_msg("interrupted"), db.now()))
        if cur.rowcount:
            log.warning("помечено прерванными задач: %s", cur.rowcount)
        # Файлы, удаленные из облака программой, не должны выглядеть
        # живыми (см. _repair_deleted_probe).
        _repair_deleted_probe(conn())
        # Папки для файлов, учтённых вручную: без них дерево рисует папку
        # файлом, и она всегда видна в режиме «только нескачанное».
        from . import localwatch
        localwatch.backfill_dirs(conn())
        # История проб растёт на 26 тыс. строк за проход: без чистки это
        # миллионы строк в год, и отчёт «Здоровье» снова начнёт ползти.
        dropped = db.prune_history(conn(), config.HISTORY_KEEP_DAYS)
        if dropped:
            log.info("история проб: удалено %s записей старше %s дней",
                     dropped, config.HISTORY_KEEP_DAYS)

    async def totals_watch() -> None:
        """Держать итоги тёплыми.

        Пересчёт -- около 370 мс по 26 тыс. строк. Пока он жил в
        обработчике, каждый опрос раз в 20 секунд упирался в него. Пусть
        платит фон, а интерфейс читает готовое.
        """
        while True:
            try:
                await asyncio.to_thread(cached_totals, True)
                await asyncio.to_thread(cached_remaining, True)
            except Exception:
                log.debug("пересчёт итогов не удался", exc_info=True)
            await asyncio.sleep(config.TOTALS_REFRESH_S)

    MAIN_LOOP.create_task(totals_watch())

    async def heartbeat() -> None:
        while True:
            try:
                db.kv_set(conn(), "server_heartbeat", db.now())
            except sqlite3.Error:
                pass
            await asyncio.sleep(10)

    MAIN_LOOP.create_task(heartbeat())

    async def token_watch() -> None:
        """Живая проверка токена -- раз в пять минут.

        Чип «нет токена» показывал только ОТСУТСТВИЕ токена: истёкший
        выглядел здоровым, пока задача не упадёт с 401. Теперь состояние
        проверяется само, а сетевые сбои не выдаются за мёртвый токен.
        """
        while True:
            try:
                if not config.token():
                    db.kv_del(conn(), "token_check")
                else:
                    await _refresh_account()
            except OSError as exc:
                text = str(exc)
                dead = "401" in text or "403" in text
                db.kv_set(conn(), "token_check", {
                    "ok": False if dead else None,
                    "ts": db.now(), "detail": text[:200]})
                if dead:
                    log.warning("токен не принимается: %s", text[:120])
            except Exception:
                log.debug("проверка токена не удалась", exc_info=True)
            await asyncio.sleep(300)

    MAIN_LOOP.create_task(token_watch())

    async def autopilot_watch() -> None:
        """Круги автопилота: перепроба недоступного и забор ожившего.

        Запускается изнутри цикла, поэтому задачу ведёт сам (через _spawn
        нельзя -- тот ждёт будущего результата и повесит петлю). Круг не
        начинается, пока идёт любая другая работа: две выгрузки испортят
        .part, гонка с пробой сожжёт квоту.
        """
        from . import autopilot

        while True:
            try:
                await asyncio.sleep(60)
                c = conn()
                if not db.kv_get(c, "autopilot"):
                    continue
                last = float(db.kv_get(c, "autopilot_last", 0) or 0)
                if time.time() < last + config.AUTOPILOT_INTERVAL_H * 3600:
                    continue
                if c.execute("SELECT 1 FROM jobs WHERE state='running' "
                             "LIMIT 1").fetchone():
                    continue
                job_id = db.job_start(c, "autopilot", 0)
                log.info("job %s (autopilot): круг", job_id)
                try:
                    async with _disk() as disk:
                        result = await autopilot.round_once(c, disk,
                                                            job_id=job_id)
                except BaseException as exc:
                    log.exception("job %s (autopilot) упал", job_id)
                    result = {"failed": 1, "error": f"{type(exc).__name__}: {exc}"}
                state = _job_state(result, db.job_cancelled(c, job_id))
                db.job_finish(c, job_id, state, str(result)[:900])
                db.kv_set(c, "autopilot_last", int(time.time()))
                log.info("job %s (autopilot): %s -- %s", job_id, state,
                         str(result)[:300])
            except Exception:
                log.debug("круг автопилота не удался", exc_info=True)

    MAIN_LOOP.create_task(autopilot_watch())

    async def local_watch() -> None:
        """Сверка зеркала с диском в фоне.

        Файлы появляются и исчезают мимо программы: ручной перенос,
        чистка, переименование в проводнике. Пока сверка не пройдёт,
        «есть на диске» врёт -- и переключатель «только нескачанное»
        показывает уже сохранённое. Обход дешёвый, поэтому просто часто.
        """
        from . import localwatch
        while True:
            try:
                c = db.connect(config.PATHS.db)
                try:
                    await asyncio.to_thread(localwatch.sync, c)
                finally:
                    c.close()
            except Exception:
                log.debug("сверка зеркала не удалась", exc_info=True)
            await asyncio.sleep(config.LOCAL_SYNC_SECONDS)

    MAIN_LOOP.create_task(local_watch())
    log.info("сервер готов, порт %s, корень %s", SERVE_PORT, config.PATHS.root)


def _disk(concurrency: int | None = None) -> Disk:
    return Disk(config.require_token(), concurrency=concurrency)


def _failed_count(result: Any) -> int:
    """Сколько провалов в итоговом словаре задачи.

    У разных работ счётчики называются по-своему (failed у выгрузки,
    cloud_failed у переноса, linked_failed у доделки ссылок), а смысл
    один: часть работы не сделана -- значит «готово» писать нельзя.
    """
    if not isinstance(result, dict):
        return 0
    total = 0
    # no_space: круг останавливается, когда свободного места осталось
    # меньше запаса (download.py), и без этого счётчика задача
    # отчитывалась «готово» -- хотя не спасла ничего, потому что диск
    # полон. 21 октября диск дошёл до 97%, и это не гипотетика.
    for key in ("failed", "cloud_failed", "linked_failed", "no_space"):
        try:
            total += int(result.get(key, 0) or 0)
        except (TypeError, ValueError):
            pass
    return total


def _success_count(result: Any) -> int:
    """Сколько работы реально сделано (для отличия «частично» от «провал»)."""
    if not isinstance(result, dict):
        return 0
    total = 0
    for key in ("ok", "skipped", "unlinked", "deleted", "already", "added",
                "restored", "verified", "packed", "released",
                # выгрузка: файл с дырками и файл без хеша в описи -- это
                # тоже спасённые файлы, иначе задача с пятью такими
                # выглядела бы полностью провалившейся
                "salvaged", "unverified"):
        try:
            total += int(result.get(key, 0) or 0)
        except (TypeError, ValueError):
            pass
    return total


def _summary(result: Any) -> str:
    """Короткий итог задачи: «ok 5 · failed 102», а не repr словаря.

    Раньше в подвал и в карточку «Сейчас» уходил str(result) -- человек
    видел {'ok': 5, 'unavailable': 102, 'gone': 3}. Это не текст: его
    нельзя ни прочитать, ни перевести. Латиница и числа одинаково
    понятны на любом языке интерфейса.
    """
    if not isinstance(result, dict):
        return str(result)[:200]
    parts = [f"{k} {v}" for k, v in sorted(result.items())
             if isinstance(v, int) and not isinstance(v, bool) and v]
    return " · ".join(parts)[:300]


def _job_state(result: Any, cancelled: bool) -> str:
    """Честное состояние по итогу работы.

    «Готово» при сотне провалов -- ложное подтверждение: задача #46
    отчиталась done с failed=140 и выглядела зелёной галочкой. Частичный
    итог называется своим именем, полный провал -- ошибкой.
    """
    if cancelled:
        return "cancelled"
    if not _failed_count(result):
        return "done"
    return "failed" if _success_count(result) == 0 else "partial"


def _spawn(kind: str, coro_factory, total: int = 0,
           concurrency: int | None = None, *,
           needs_disk: bool = True) -> int:
    """Запустить фоновую работу и вернуть её номер.

    Обработчики здесь -- обычные `def`, и FastAPI выполняет их в потоке из
    пула, где запущенного event loop НЕТ. asyncio.create_task() в таком
    потоке падает с "no running event loop": каждое нажатие кнопки давало
    500, а строка задачи, созданная строкой выше, навсегда оставалась в
    "running" с нулевым прогрессом.

    Поэтому корутина отдаётся петле, пойманной при старте сервера, через
    run_coroutine_threadsafe -- он для того и существует, чтобы передавать
    работу в петлю из чужого потока.

    Повторный запуск того же вида запрещён: две выгрузки одного файла
    писали ОДИН .part (файл выходил mismatch), а две описи затирали общий
    чекпоинт в kv. Пусть лучше будет отказ с объяснением.
    """
    busy = conn().execute(
        "SELECT id FROM jobs WHERE kind=? AND state='running' LIMIT 1",
        (kind,)).fetchone()
    if busy is not None:
        raise HTTPException(409, {"code": "err.busy", "kind": kind,
                                  "id": busy["id"]})
    job_id = db.job_start(conn(), kind, total)

    async def wrapper() -> None:
        # Клиент создаётся ВНУТРИ try. Снаружи его создание однажды уже
        # уронило задачу молча: job навсегда остался "running" с пустым
        # сообщением, а в UI -- висящая полоска без объяснений.
        disk = None
        try:
            log.info("job %s (%s): старт", job_id, kind)
            # needs_disk=False -- работа целиком на локальном диске
            # (adopt): клиент Диска не создаём и токен не требуем.
            if needs_disk:
                disk = _disk(concurrency)
            result = await coro_factory(disk, job_id)
            state = _job_state(result, db.job_cancelled(conn(), job_id))
            db.job_finish(conn(), job_id, state, _summary(result))
            log.info("job %s (%s): %s -- %s", job_id, kind, state, str(result)[:300])
        except (KeyboardInterrupt, asyncio.CancelledError):
            # Это не поломка: так выглядит закрытие приложения или кнопка
            # «стоп». Раньше такое писалось как "failed" с трейсбеком на
            # полэкрана -- и в списке работ выглядело аварией, которой не
            # было. Сделанное до остановки уже записано в базу пофайлово.
            log.info("job %s (%s): остановлен", job_id, kind)
            db.job_finish(conn(), job_id, "cancelled",
                          "остановлено: приложение закрыто или нажат стоп")
            raise
        except BaseException as exc:
            log.exception("job %s (%s) упал", job_id, kind)
            db.job_finish(conn(), job_id, "failed", f"{type(exc).__name__}: {exc}"[:900])
        finally:
            if disk is not None:
                await disk.aclose()
            _tasks.pop(job_id, None)

    loop = MAIN_LOOP
    if loop is None or loop.is_closed():
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
    if loop is None:
        # Запустить нечем. Задача не должна остаться "running" навсегда --
        # лучше честная ошибка в строке работы, чем вечная полоска.
        msg = "некуда запустить задачу: событийный цикл сервера не найден"
        log.error("job %s (%s): %s", job_id, kind, msg)
        db.job_finish(conn(), job_id, "failed", msg)
        raise HTTPException(500, msg)

    _tasks[job_id] = asyncio.run_coroutine_threadsafe(wrapper(), loop)
    return job_id


# ── состояние ────────────────────────────────────────────────────────


# Итоги по всей коллекции считаются полным проходом по 24 тысячам строк с
# четырьмя соединениями -- 200 мс. Интерфейс опрашивает состояние, пока идёт
# работа, и без кэша сервер тратил бы пятую часть секунды каждые полторы
# секунды на одни только цифры в шапке, отнимая их у самой выгрузки.
# Несколько секунд задержки в счётчиках не значат ничего, а нагрузка падает.
_totals_cache: dict = {"at": 0.0, "value": None}
TOTALS_TTL = 20.0


def cached_totals(force: bool = False) -> dict:
    """Итоги из кэша; пересчёт -- по force или когда кэша ещё нет.

    Раньше по истечении TTL пересчёт делался прямо в обработчике: каждые
    20 секунд кто-то из опросов платил 370 мс. Теперь свежесть держит
    фоновая задача, а запрос всегда читает готовое.
    """
    if not force and _totals_cache["value"] is not None:
        return _totals_cache["value"]
    value = tree.totals(conn())
    _totals_cache.update(at=time.monotonic(), value=value)
    return value


_remaining_cache: dict = {"at": 0.0, "value": None}


def cached_remaining(force: bool = False) -> dict:
    """Остаток по последнему известному состоянию облака.

    Свежесть держит та же фоновая задача, что и итоги: запрос идёт по
    тем же 26 тыс. строк и стоит десятки миллисекунд.
    """
    if not force and _remaining_cache["value"] is not None:
        return _remaining_cache["value"]
    value = tree.remaining(conn())
    # Сколько файлов возьмёт круг -- по его собственным правилам (отлёжка
    # после провала, свежий gone). Кнопка должна показывать именно это
    # число, а не «сколько недоступных вообще»: они расходятся.
    from . import download
    value["loop_queue"] = download.pending_count(conn())
    _remaining_cache.update(at=time.monotonic(), value=value)
    return value


def _seconds_per_file(c) -> float:
    """Сколько в среднем уходит на файл -- по последним проходам выгрузки.

    Раньше здесь стояло 20 секунд на файл. Замеры давали и 2, и 23.5:
    хранилище меняется, и оценка «прогон займёт N часов» врала тем сильнее,
    чем дальше оно уходит от константы. Считаем по факту, константа --
    только запасной вариант, когда проходов ещё не было.
    """
    row = c.execute(
        """SELECT SUM(done) AS files,
                  SUM(finished_at - started_at) AS spent
             FROM jobs
            WHERE kind='download' AND finished_at IS NOT NULL
              AND done > 0 AND started_at > ?""",
        (db.now() - 14 * 86400,)).fetchone()
    try:
        files = int(row["files"] or 0)
        spent = float(row["spent"] or 0)
    except (TypeError, ValueError):
        return 20.0
    if files < 20 or spent <= 0:
        return 20.0
    return max(0.5, spent / files)


def next_step(c, totals: dict, running: int | None = None,
              left: dict | None = None) -> dict:
    """Какой шаг программа советует следуюшим -- и почему.

    Порядок продиктован тем, что мы узнали о хранилище: доступность
    гниёт за часы (18 октября пятая часть «доступных» выпала за два
    часа, 71 файл умер между пробой и скачиванием). Поэтому живое
    важно забрать раньше, чем проверять мёртвое.
    """
    if running is None:
        running = c.execute("SELECT id, kind FROM jobs WHERE state='running' "
                            "LIMIT 1").fetchone()
    if running is not None:
        return {"kind": "busy", "job": running["id"], "work": running["kind"]}

    pending = len((db.kv_get(c, "scan_queue") or {}).get("stack") or [])
    if pending:
        return {"kind": "scan", "n": pending}
    # Пустая опись -- это не «всё сделано», а «ещё не начинали». Без этой
    # ветки первый запуск показывал «Пока делать нечего»: человек видел
    # совет отдыхать, хотя программа ещё ничего не знала о его облаке.
    if not totals.get("files"):
        return {"kind": "start"}
    if totals.get("dl_ready"):
        return {"kind": "download", "n": totals["dl_ready"]}
    # Недоступное -- единственный класс, который возвращается (21 октября:
    # 1371 возврат против 6 у gone). Если оно есть, честнее прогнать
    # остаток выгрузкой, чем ещё раз спрашивать первый байт.
    left = left or {}
    by = left.get("by_state") or {}
    # Очередь круга -- его собственное число (отлёжка, свежий gone).
    # «Недоступных вообще» больше, и обещать их в шаге неправильно.
    unavail = int(left.get("loop_queue")
                  or (by.get("unavailable") or {}).get("files") or 0)
    if unavail:
        return {"kind": "loop", "n": unavail,
                "bytes": (by.get("unavailable") or {}).get("bytes") or 0,
                "hours": round(unavail * _seconds_per_file(c) / 3600, 1)}
    if totals.get("unchecked"):
        return {"kind": "probe", "n": totals["unchecked"]}
    if totals.get("stale"):
        return {"kind": "stale", "n": totals["stale"]}
    if totals.get("saved") and totals.get("free_pct", 100) < 15:
        return {"kind": "archive", "n": totals["saved"]}
    if totals.get("unavailable") and not db.kv_get(c, "autopilot"):
        return {"kind": "autopilot", "n": totals["unavailable"]}
    return {"kind": "done"}


@app.get("/api/state")
def state(fresh: bool = False) -> dict:
    from . import autopilot

    c = conn()
    free = {}
    for label, p in (("save_root", config.PATHS.root), ("archives", config.PATHS.archives)):
        probe_path = Path(p)
        while not probe_path.exists() and probe_path.parent != probe_path:
            probe_path = probe_path.parent
        try:
            usage = shutil.disk_usage(probe_path)
            free[label] = {"free": usage.free, "total": usage.total,
                           "drive": str(Path(p).anchor)}
        except OSError:
            free[label] = None
    # Копия: ниже в словарь добавляется free_pct, а в кэше лежит тот же
    # объект -- иначе признак «мало места» застывал бы вместе с кэшем.
    totals = dict(cached_totals(force=fresh))
    left = cached_remaining(force=fresh)
    # Доля свободного места -- для совета «пора архивировать».
    if free.get("save_root"):
        totals["free_pct"] = round(100 * free["save_root"]["free"]
                                   / max(1, free["save_root"]["total"]), 1)
    return {
        "token": bool(config.token()),
        # Живая проверка токена (обновляется раз в 5 минут): наличие
        # токена и его работоспособность -- разные вещи.
        "token_check": db.kv_get(c, "token_check"),
        # Кто авторизован и сколько места -- для кнопки в шапке.
        "account": db.kv_get(c, "account"),
        # Автопилот и статистика узлов хранения.
        "autopilot": bool(db.kv_get(c, "autopilot")),
        "autopilot_last_at": db.kv_get(c, "autopilot_last"),
        "autopilot_config": {"hours": config.AUTOPILOT_INTERVAL_H,
                             "batch": config.AUTOPILOT_BATCH},
        "hosts": autopilot.host_liveness(c),
        "auth": secretstore.status(),
        "redirect_uri": oauth.redirect_uri(SERVE_PORT),
        "seven_zip": str(archive_mod.seven_zip() or ""),
        "root": str(config.PATHS.root),
        "volume": config.VOLUME,
        "compression": config.COMPRESSION,
        "reserve": config.RESERVE,
        "concurrency": config.CONCURRENCY,
        "probe_concurrency": config.PROBE_CONCURRENCY,
        "probe_ttl_hours": config.PROBE_TTL_HOURS,
        "assets_version": assets_version(),
        "now": db.now(),
        "totals": totals,
        # Сколько осталось взять -- по последнему известному состоянию
        # облака, с разбивкой: «осталось 791 ГБ» без этого читается как
        # «столько ещё можно взять», хотя 738 ГБ из них облако уже не
        # отдаёт.
        "remaining": left,
        # Следующий шаг: программа сама считает, что важнее сделать.
        "next_step": next_step(c, totals, left=left),
        "last_scan": db.kv_get(c, "last_scan"),
        # Сколько папок осталось в очереди прерванной описи: по этому числу
        # в интерфейсе видно, что обход продолжится, а не начнётся заново.
        "scan_pending": len((db.kv_get(c, "scan_queue") or {}).get("stack") or []),
        "free": free,
    }


@app.get("/api/tree")
def get_tree(path: str = "disk:/") -> dict:
    return {"path": path, "children": tree.children(conn(), path, use_cache=True)}


def _like(text: str) -> str:
    """Экранировать шаблоны LIKE: % и _ в имени файла -- это символы.

    Без этого запрос «%» возвращал всю коллекцию, а «_» совпадал с любым
    символом: поиск вёл себя не так, как выглядит.
    """
    return (text.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_"))


@app.get("/api/search")
def search(q: str, limit: int = 300) -> dict:
    rows = conn().execute(
        """SELECT r.path, r.name, r.size, COALESCE(p.state,'unchecked') AS state,
                  l.verify, l.released
           FROM resources r
           LEFT JOIN probe p ON p.path=r.path
           LEFT JOIN local l ON l.path=r.path
           WHERE r.type='file' AND fold(r.name) LIKE fold(?)
                 ESCAPE '\\'
           ORDER BY r.size DESC LIMIT ?""",
        (f"%{_like(q)}%", limit)).fetchall()
    return {"items": [dict(r) for r in rows]}


@app.get("/api/file")
def file_detail(path: str) -> dict:
    row = conn().execute(
        """SELECT r.*, COALESCE(p.state,'unchecked') AS probe_state, p.http_status,
                  p.storage_host, p.detail, p.checked_at, p.attempts,
                  l.verify, l.local_path, l.bytes AS local_bytes, l.holes, l.released,
                  COALESCE(l.missing,0) AS local_missing,
                  m.preview_state
           FROM resources r
           LEFT JOIN probe p ON p.path=r.path
           LEFT JOIN local l ON l.path=r.path
           LEFT JOIN meta_saved m ON m.path=r.path
           WHERE r.path=?""", (path,)).fetchone()
    if row is None:
        raise HTTPException(404, {"code": "err.noFile"})
    return dict(row)


@app.get("/api/preview")
def preview(path: str):
    dest = scan.preview_dest(path)
    if not Path(extended(dest)).is_file():
        raise HTTPException(404, {"code": "err.noPreview"})
    return FileResponse(extended(dest), media_type="image/jpeg")


# ── выбор ────────────────────────────────────────────────────────────


class Selection(BaseModel):
    paths: list[str] = []
    folders: list[str] = []
    states: list[str] | None = None
    exclude_saved: bool = False
    only_saved: bool = False


def _resolve(sel: Selection) -> list[str]:
    """Раскрыть выбор папок в список файлов, сохранив порядок и уникальность."""
    out: list[str] = []
    seen: set[str] = set()
    for p in sel.paths:
        if p not in seen:
            seen.add(p)
            out.append(p)
    for folder in sel.folders:
        for p in tree.subtree_files(conn(), folder, states=sel.states,
                                    only_saved=sel.only_saved,
                                    exclude_saved=sel.exclude_saved):
            if p not in seen:
                seen.add(p)
                out.append(p)
    return out


@app.post("/api/plan")
def plan(sel: Selection) -> dict:
    paths = _resolve(sel)
    return {"paths": len(paths), "plan": download.plan(conn(), paths)}


# ── работы ───────────────────────────────────────────────────────────


class ScanBody(BaseModel):
    root: str = "disk:/"
    previews: bool = True
    # По умолчанию опись продолжается с чекпоинта: прерванный обход
    # встаёт на ту же очередь папок, а не начинает облако с корня.
    resume: bool = True


@app.post("/api/scan")
def start_scan(body: ScanBody) -> dict:
    async def work(disk: Disk, job_id: int) -> Any:
        result = await scan.scan(conn(), disk, body.root, job_id=job_id,
                                 resume=body.resume)
        if body.previews and not db.job_cancelled(conn(), job_id):
            result["previews"] = await scan.harvest_previews(conn(), disk, job_id=job_id)
        # Выгрузка описи в файл -- удобство, а не сама работа: каталог уже
        # лежит в базе. Часовой обход не должен числиться провалившимся
        # из-за того, что не удалось записать один вспомогательный файл.
        try:
            scan.export_manifest(conn())
        except OSError as exc:
            log.warning("опись собрана, но файл не записан: %s", exc)
            result["manifest_error"] = str(exc)[:200]
        return result
    return {"job": _spawn("scan", work)}


@app.post("/api/previews")
def start_previews(refresh: bool = False) -> dict:
    async def work(disk: Disk, job_id: int) -> Any:
        return await scan.harvest_previews(conn(), disk, job_id=job_id, refresh=refresh)
    return {"job": _spawn("previews", work)}


class AdoptBody(BaseModel):
    # Где лежит папка клиента. Пусто -- %USERPROFILE%\Yandex.Disk.
    source: str | None = None
    # move -- перенос (файл уходит из папки клиента в нашу), link -- жёсткая
    # ссылка, copy -- копия. Перенос по умолчанию: клиент Диска видит
    # пропажу и убирает файл из облака, то есть вещь переезжает целиком.
    mode: str = "move"
    # После сверки хеша удалить облачную копию. Только для файлов, чей
    # хеш сошёлся с сообщённым Яндексом: непроверенное не удаляется.
    delete_cloud: bool = True
    # Сверять хеши с теми, что сообщил Яндекс.
    verify: bool = True


@app.post("/api/adopt/survey")
def adopt_survey(body: AdoptBody) -> dict:
    """Сколько возьмётся из локальной папки -- ни одного изменения на диске."""
    from . import adopt
    source = Path(body.source) if body.source else adopt.DEFAULT_SOURCE
    return adopt.survey(conn(), source)


@app.post("/api/adopt")
def start_adopt(body: AdoptBody) -> dict:
    from . import adopt
    source = Path(body.source) if body.source else adopt.DEFAULT_SOURCE
    if not source.is_dir():
        raise HTTPException(400, {"code": "err.folderMissing",
                                  "source": str(source)})

    async def work(disk: Disk | None, job_id: int) -> Any:
        # Сеть нужна только для удаления облачных копий: сам перенос
        # локальный. Если удалять не просили, клиент Диска не создаётся.
        return await adopt.run(conn(), source, mode=body.mode,
                               verify=body.verify,
                               delete_cloud=body.delete_cloud,
                               disk=disk, job_id=job_id)

    survey = adopt.survey(conn(), source)
    return {"job": _spawn("adopt", work,
                          survey["files"] + survey.get("linked", 0),
                          needs_disk=body.delete_cloud),
            "files": survey["files"], "bytes": survey["bytes"],
            "linked": survey.get("linked", 0)}


@app.post("/api/mirror/survey")
def mirror_survey_endpoint() -> dict:
    """Что лежит в зеркале мимо программы -- без единого изменения."""
    from . import adopt
    return adopt.mirror_survey(conn())


@app.post("/api/mirror")
def start_mirror() -> dict:
    """Учесть перенесённое в зеркало вручную: файлы уже на диске,
    регистрируем ресурс (если облако о нём молчит) и локальную запись."""
    from . import adopt

    async def work(_disk: Disk | None, job_id: int) -> Any:
        # Сеть не нужна: файл уже в зеркале, читаем только диск.
        return await adopt.run_mirror(conn(), verify=True, job_id=job_id)

    survey = adopt.mirror_survey(conn())
    return {"job": _spawn("mirror", work, survey["files"], needs_disk=False),
            "files": survey["files"]}


class ProbeBody(Selection):
    limit: int | None = None
    stale_hours: float | None = None
    recheck_all: bool = False


@app.post("/api/probe")
def start_probe(body: ProbeBody) -> dict:
    paths = _resolve(body)
    if not paths:
        paths = probe.select_paths(
            conn(), states=body.states, limit=body.limit,
            stale_hours=body.stale_hours,
            skip_downloaded=not body.recheck_all)
    elif body.limit:
        paths = paths[:body.limit]

    async def work(disk: Disk, job_id: int) -> Any:
        return await probe.run(conn(), disk, paths, job_id=job_id)
    # Проба идёт на своём лимите: это запросы по одному байту, и держать их
    # на восьми потоках, как мегабайтную выгрузку, нет причины -- именно
    # из-за этого полный проход занимал час и успевал протухнуть.
    return {"job": _spawn("probe", work, len(paths),
                          concurrency=config.PROBE_CONCURRENCY),
            "files": len(paths)}


class DownloadBody(Selection):
    salvage: bool = False
    available_only: bool = True


@app.post("/api/download")
def start_download(body: DownloadBody) -> dict:
    paths = _resolve(body)
    if body.available_only and paths:
        qs = ",".join("?" * len(paths))
        allowed = {r["path"] for r in conn().execute(
            f"""SELECT r.path FROM resources r LEFT JOIN probe p ON p.path=r.path
                WHERE r.path IN ({qs}) AND (p.state='ok' OR p.state IS NULL)""", paths)}
        paths = [p for p in paths if p in allowed]
    if paths:
        # Уже лежащее на диске в очередь не ставим: 'ok' пропустится сам,
        # а 'unverified' (файл перенесён вручную, облако о нём молчит)
        # провалится «нет ссылки» -- 18 октября так зря сгорело 140 файлов
        # за один заход.
        qs = ",".join("?" * len(paths))
        have = {r["path"] for r in conn().execute(
            f"SELECT path FROM local WHERE path IN ({qs}) "
            f"AND verify IN ('ok','unverified') AND released=0", paths)}
        paths = [p for p in paths if p not in have]
    if not paths:
        raise HTTPException(400, {"code": "err.nothingToDownload"})

    async def work(disk: Disk, job_id: int) -> Any:
        return await download.run(conn(), disk, paths, salvage=body.salvage,
                                  job_id=job_id)
    return {"job": _spawn("download", work, len(paths)), "files": len(paths)}


class HostsTryBody(BaseModel):
    # Либо узел целиком, либо кластер (klg, vla...). Узел выбрать при
    # выгрузке нельзя -- ссылку выдаёт API Яндекса, -- но повторный
    # запрос иногда отдаёт другую машину, и это единственный способ
    # «попробовать с другого узла», который у нас есть.
    host: str | None = None
    cluster: str | None = None


@app.get("/api/health")
def health(days: int = 7) -> dict:
    """Здоровье: по дням, по причинам отказов, по узлам, по задачам.

    Считается по базе, а не по логу: лог в 50 МБ читать в интерфейсе
    нельзя, а всё нужное уже лежит в probe, probe_history, local,
    cloud_deleted и jobs.
    """
    return health_mod.report(conn(), days=max(1, min(30, days)))


@app.get("/api/hosts")
def hosts() -> dict:
    """Узлы и кластеры: где висит остаток и что они отвечали."""
    return tree.hosts_report(conn())


@app.post("/api/hosts/try")
def hosts_try(body: HostsTryBody) -> dict:
    """Попросить ссылки заново для файлов узла или кластера."""
    if not body.host and not body.cluster:
        raise HTTPException(400, {"code": "err.needNode"})
    c = conn()
    rows = c.execute(
        """SELECT r.path, p.storage_host AS host FROM resources r
             JOIN probe p ON p.path = r.path
             LEFT JOIN local l ON l.path = r.path
             LEFT JOIN cloud_deleted cd ON cd.path = r.path
            WHERE r.type='file' AND p.storage_host IS NOT NULL
              AND r.vanished_at IS NULL AND cd.path IS NULL
              AND (l.path IS NULL OR l.missing=1)""").fetchall()
    if body.host:
        paths = [r["path"] for r in rows if r["host"] == body.host]
        what = {"host": body.host}
    else:
        paths = [r["path"] for r in rows if tree._cluster_of(r["host"]) == body.cluster]
        what = {"cluster": body.cluster}
    if not paths:
        raise HTTPException(400, {"code": "err.nothingToProbe", **what})
    job_id = _spawn("download-loop", lambda disk, jid: download.run_rounds(
        c, disk, paths, salvage=False, job_id=jid,
        pause_s=60), total=len(paths))
    return {"job": job_id, "files": len(paths), **what}


class LoopBody(Selection):
    salvage: bool = False
    # Пауза между кругами, в которых не удалось вытащить ничего. Нужна,
    # чтобы безнадёжный круг не превращался в долбёжку по раненому
    # хранилищу: он пройдёт мгновенно и начнётся снова.
    pause_s: int = 60


@app.post("/api/download/loop/plan")
def loop_plan(body: LoopBody) -> dict:
    """Сколько файлов попадёт в круг -- до запуска."""
    chosen = _resolve(body) or None
    targets = download.pending_targets(conn(), chosen)
    rows = conn().execute(
        f"""SELECT COALESCE(SUM(size),0) b FROM resources
            WHERE path IN ({','.join('?' * len(targets))})""", targets
    ).fetchone() if targets else None
    return {"files": len(targets), "bytes": (rows["b"] if rows else 0),
            "selected": bool(body.paths or body.folders)}


class SelectionPlanBody(Selection):
    """Выбор плюс настройки, от которых зависят планы."""
    volume: str | None = None
    compression: str | None = None
    level: str = "downloaded"


@app.post("/api/selection/plan")
def selection_plan(body: SelectionPlanBody) -> dict:
    """Всё, что интерфейсу нужно знать о выборе, -- одним запросом.

    Раньше на каждое изменение выбора уходило четыре запроса: план
    выгрузки, план круга, план архива и предпросмотр удаления. Каждый
    заново разрешал пути по поддереву -- самая дорогая часть. Здесь
    пути разрешаются один раз.
    """
    paths = _resolve(body)
    chosen = paths or None
    targets = download.pending_targets(conn(), chosen)
    loop_bytes = 0
    if targets:
        row = conn().execute(
            f"""SELECT COALESCE(SUM(size),0) AS b FROM resources
                WHERE path IN ({','.join('?' * len(targets))})""",
            targets).fetchone()
        loop_bytes = int(row["b"] or 0)
    return {
        "plan": download.plan(conn(), paths),
        "loop": {"files": len(targets), "bytes": loop_bytes,
                 "selected": bool(body.paths or body.folders)},
        "arch": archive_plan(ArchiveBody(
            paths=body.paths, folders=body.folders,
            volume=body.volume, compression=body.compression)),
        "del": cloud_delete_preview(DeleteBody(
            paths=body.paths, folders=body.folders, states=body.states,
            exclude_saved=body.exclude_saved, level=body.level)),
    }


@app.post("/api/download/loop")
def start_loop(body: LoopBody) -> dict:
    """Качать по кругу, пока не остановят.

    Пробу не трогаем вовсе: попытка скачать и есть проверка, причём
    честнее -- она читает файл целиком, а не первый байт. Список
    пересобирается каждый круг, поэтому спасённое выпадает само.
    """
    chosen = _resolve(body) or None
    targets = download.pending_targets(conn(), chosen)
    if not targets:
        raise HTTPException(400, {"code": "err.allOnDisk"})

    async def work(disk: Disk, job_id: int) -> Any:
        return await download.run_rounds(
            conn(), disk, chosen, salvage=body.salvage, job_id=job_id,
            pause_s=max(5, int(body.pause_s)))
    return {"job": _spawn("download-loop", work, len(targets),
                          concurrency=config.LOOP_CONCURRENCY),
            "files": len(targets)}


class ArchiveBody(BaseModel):
    paths: list[str] | None = None
    folders: list[str] = []
    # Размер тома 7z: "3900m" -- Телеграм-премиум, "1900m" -- обычный,
    # "0" -- не дробить. Раньше бралось только из переменной окружения.
    volume: str | None = None
    compression: str | None = None


def _archive_paths(body: ArchiveBody) -> list[str] | None:
    """Что паковать: выбранное в дереве или всё готовое.

    Пустой выбор означает «всё готовое» -- это и было единственным
    поведением раньше, и на коллекции в тысячи файлов нажатие кнопки
    запускало многочасовую паковку без спроса.
    """
    if body.paths:
        return list(body.paths)
    if body.folders:
        out: list[str] = []
        seen: set[str] = set()
        for folder in body.folders:
            for pth in tree.subtree_files(conn(), folder, only_saved=True):
                if pth not in seen:
                    seen.add(pth)
                    out.append(pth)
        return out
    return None


@app.post("/api/archive/plan")
def archive_plan(body: ArchiveBody) -> dict:
    """Сколько файлов и байт уйдёт в паковку -- до её запуска."""
    pend = archive_mod.pending(conn(), _archive_paths(body))
    total = sum(p["bytes"] for p in pend)
    vol = (body.volume or config.VOLUME).strip().lower()
    volumes = 0
    if vol not in ("", "0") and vol.endswith("m") and vol[:-1].isdigit():
        per = int(vol[:-1]) * 1024 * 1024
        volumes = (total + per - 1) // per if per else 0
    return {"files": len(pend), "bytes": total, "volume": vol,
            "volumes": volumes, "selected": bool(body.paths or body.folders)}


@app.post("/api/archive")
def start_archive(body: ArchiveBody) -> dict:
    chosen = _archive_paths(body)

    async def work(_disk: Disk, job_id: int) -> Any:
        return await asyncio.to_thread(
            archive_mod.build, conn(), chosen, job_id=job_id,
            volume=body.volume, compression=body.compression)
    pend = archive_mod.pending(conn(), chosen)
    return {"job": _spawn("archive", work, len(pend)), "files": len(pend),
            "bytes": sum(p["bytes"] for p in pend)}


@app.get("/api/archives")
def archives() -> dict:
    rows = conn().execute(
        """SELECT a.*, (SELECT COUNT(*) FROM archive_members m WHERE m.archive_id=a.id)
                  AS files
           FROM archives a ORDER BY a.created_at DESC""").fetchall()
    out = []
    for r in rows:
        rec = dict(r)
        rec["volumes"] = [dict(v) for v in conn().execute(
            "SELECT volume, bytes, sha256 FROM archive_volumes WHERE archive_id=?",
            (r["id"],))]
        out.append(rec)
    return {"items": out}


@app.post("/api/archives/{archive_id}/verify")
def verify_archive(archive_id: int) -> dict:
    return archive_mod.verify(conn(), archive_id)


@app.post("/api/archives/{archive_id}/release")
def release_archive(archive_id: int) -> dict:
    try:
        return archive_mod.release(conn(), archive_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


# ── удаление из облака ───────────────────────────────────────────────


class DeleteBody(Selection):
    level: str = "downloaded"
    confirm: int = -1
    permanently: bool = True


@app.post("/api/cloud-delete/preview")
def cloud_delete_preview(body: DeleteBody) -> dict:
    paths = _resolve(body) or None
    if body.level == "selected" and not paths:
        # «Выбранное» без выбора -- это была бы команда «удалить всё»,
        # то есть ровно противоположное намерению.
        raise HTTPException(400, {"code": "err.needSelection"})
    allowed, blocked = cloud.eligible(conn(), paths, level=body.level)
    reasons: dict[str, int] = {}
    for b in blocked:
        reasons[b["reason"]] = reasons.get(b["reason"], 0) + 1
    return {
        "allowed": len(allowed),
        "allowed_bytes": sum(int(a["size"] or 0) for a in allowed),
        "blocked": len(blocked),
        "reasons": reasons,
        "confirm": len(allowed),
        # Сколько из попавших под удаление не имеют проверенной копии --
        # для предупреждения при выборочном удалении.
        "unsaved": len([a for a in allowed if not a["verify"]]),
        "sample": [a["path"] for a in allowed[:20]],
    }


@app.post("/api/cloud-delete")
def cloud_delete(body: DeleteBody) -> dict:
    paths = _resolve(body) or None
    if body.level == "selected" and not paths:
        raise HTTPException(400, {"code": "err.needSelection"})
    allowed, _ = cloud.eligible(conn(), paths, level=body.level)
    if body.confirm != len(allowed):
        raise HTTPException(400, {"code": "err.confirmMismatch",
                                  "allowed": len(allowed),
                                  "got": body.confirm})

    async def work(disk: Disk, job_id: int) -> Any:
        return await cloud.delete(conn(), disk, paths or [], level=body.level,
                                  confirm=body.confirm,
                                  permanently=body.permanently, job_id=job_id)
    return {"job": _spawn("cloud-delete", work, len(allowed))}


# ── прогресс ─────────────────────────────────────────────────────────


@app.get("/api/jobs")
def jobs(limit: int = 20) -> dict:
    rows = conn().execute(
        "SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return {"items": [dict(r) for r in rows]}


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: int) -> dict:
    """Попросить задачу остановиться.

    Сообщение ставится сразу: уже начатые файлы доигрываются (обрывать
    запись на середине незачем), и без отметки это выглядело как
    проигнорированное нажатие.
    """
    conn().execute(
        "UPDATE jobs SET cancel=1, message=? "
        "WHERE id=? AND state='running'", (job_msg("stopping"), job_id))
    return {"ok": True, "stopping": True}


class RevealBody(BaseModel):
    path: str | None = None   # облачный путь файла; пусто -- корень спасения


def reveal_target(cloud_path: str | None) -> Path:
    """Что открыть в проводнике для этого облачного пути.

    Наружу выпускается только то, что лежит внутри корня спасения: путь
    приходит из браузера, и открывать по нему произвольное место на диске
    незачем. Всё, что не проходит проверку, схлопывается в корень.
    """
    root = config.PATHS.root.resolve()
    target = config.PATHS.root
    if cloud_path:
        local = local_for(cloud_path, config.PATHS.files)
        target = local if Path(extended(local)).exists() else local.parent
    try:
        target.resolve().relative_to(root)
    except (ValueError, OSError):
        return config.PATHS.root
    if not Path(extended(target)).exists():
        return config.PATHS.root
    return target


@app.post("/api/reveal")
def reveal(body: RevealBody) -> dict:
    """Открыть папку спасения в проводнике.

    Вопрос «а куда оно вообще качается» возникает ровно потому, что ответ
    нигде не показан. Путь теперь виден в шапке и открывается одним щелчком.
    """
    target = reveal_target(body.path)
    try:
        if target.is_dir():
            subprocess.Popen(["explorer", str(target)])
        else:
            subprocess.Popen(["explorer", "/select,", str(target)])
    except OSError as exc:
        raise HTTPException(500, {"code": "err.reveal",
                                  "error": str(exc)}) from exc
    return {"opened": str(target)}


# Колонки описи. Порядок и названия -- те, что человек ищет в таблице;
# `state` -- то же слово, что в интерфейсе: ok / unavailable / gone.
EXPORT_COLUMNS = ("path", "size", "state", "http_status", "checked_at",
                  "modified", "md5", "sha256", "local_path", "verify",
                  "downloaded_at", "missing")


@app.get("/api/export")
def export_inventory(format: str = "csv") -> Response:
    """Опись файлом: CSV для таблиц, JSON для скриптов.

    Отдаём строку на каждый файл: путь, размер, доступность, хеши и где
    лежит спасённая копия. Папки не выгружаем -- их место видно из пути.
    """
    rows = conn().execute(
        """SELECT r.path AS path, r.size AS size,
                  COALESCE(p.state, 'unchecked') AS state,
                  p.http_status AS http_status, p.checked_at AS checked_at,
                  r.modified AS modified, r.md5 AS md5, r.sha256 AS sha256,
                  l.local_path AS local_path, l.verify AS verify,
                  l.downloaded_at AS downloaded_at, l.missing AS missing
             FROM resources r
             LEFT JOIN probe p ON p.path = r.path
             LEFT JOIN local l ON l.path = r.path
            WHERE r.type = 'file'
            ORDER BY r.path""").fetchall()
    data = [{key: row[key] for key in EXPORT_COLUMNS} for row in rows]
    stamp = time.strftime("%Y-%m-%d")

    if format == "json":
        return Response(
            json.dumps({"exported_at": int(time.time()), "files": data},
                       ensure_ascii=False, indent=1),
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition":
                     f'attachment; filename="drydock-inventory-{stamp}.json"'})

    buffer = io.StringIO()
    # BOM: без него Excel открывает UTF-8 как кракозябры.
    buffer.write("\ufeff")
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(EXPORT_COLUMNS)
    for row in data:
        writer.writerow(["" if row[key] is None else row[key]
                         for key in EXPORT_COLUMNS])
    return Response(
        buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition":
                 f'attachment; filename="drydock-inventory-{stamp}.csv"'})


@app.get("/api/log")
def read_log(lines: int = 300, level: str | None = None) -> dict:
    """Хвост лога -- чтобы смотреть ошибки не выходя из приложения."""
    return {"file": str(logging_setup.log_file()),
            "lines": logging_setup.tail(lines, level=level)}


# ── доступ к Диску ───────────────────────────────────────────────────
#
# Значения секретов наружу не отдаются никогда: на чтение доступен только
# secretstore.status() -- признаки "есть/нет" и хвост ClientID.


class AppCreds(BaseModel):
    client_id: str
    client_secret: str


class CodeBody(BaseModel):
    code: str
    manual: bool = False
    state: str | None = None


@app.get("/api/auth/status")
def auth_status() -> dict:
    return secretstore.status() | {"redirect_uri": oauth.redirect_uri(SERVE_PORT)}


@app.post("/api/auth/app")
def auth_app(body: AppCreds) -> dict:
    try:
        return oauth.set_app(body.client_id, body.client_secret)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/auth/start")
def auth_start(manual: bool = False) -> dict:
    try:
        return oauth.start(SERVE_PORT, manual=manual)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/auth/callback")
def auth_callback(code: str | None = None, state: str | None = None,
                  error_description: str | None = None,
                  error: str | None = None):
    """Сюда Яндекс возвращает браузер после согласия."""
    def page(text: str, good: bool) -> HTMLResponse:
        color = "#4fb477" if good else "#d9534f"
        return HTMLResponse(
            "<html><head><meta charset='utf-8'><title>Drydock</title></head>"
            "<body style=\"font:16px 'Segoe UI',sans-serif;background:#15171c;"
            f"color:#e4e7ee;padding:48px\"><p style='color:{color}'>{text}</p>"
            "<p><a style='color:#5c9ded' href='/'>Вернуться в Drydock</a></p>"
            "</body></html>")

    if error or error_description:
        return page(f"Яндекс вернул ошибку: {error_description or error}", False)
    if not code:
        return page("Код не пришёл. Попробуй авторизоваться ещё раз.", False)
    try:
        oauth.exchange(code, port=SERVE_PORT, state=state)
    except ValueError as exc:
        return page(f"Не удалось получить токен: {exc}", False)
    return page("Доступ выдан. Токен сохранён в шифрованном хранилище.", True)


@app.post("/api/auth/code")
def auth_code(body: CodeBody) -> dict:
    try:
        return oauth.exchange(body.code, port=SERVE_PORT, manual=body.manual,
                              state=body.state)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/auth/refresh")
def auth_refresh() -> dict:
    try:
        return oauth.refresh()
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/auth/logout")
def auth_logout(keep_app: bool = True) -> dict:
    return oauth.logout(keep_app=keep_app)


async def _refresh_account() -> dict:
    """Кто авторизован и сколько места -- одним запросом к Диску.

    Результат кладём в kv: кнопке в шапке нужно отвечать «к какому
    аккаунту» на каждый рендер, а не ходить в сеть каждый раз.
    """
    async with _disk() as disk:
        info = await disk.about()
    user = info.get("user") or {}
    acc = {
        "login": user.get("login"),
        "name": user.get("display_name"),
        "uid": user.get("uid"),
        "used": info.get("used_space"),
        "total": info.get("total_space"),
        "ts": db.now(),
    }
    db.kv_set(conn(), "account", acc)
    db.kv_set(conn(), "token_check", {"ok": True, "ts": db.now(), "detail": ""})
    return acc


@app.post("/api/account/refresh")
async def account_refresh() -> dict:
    """Обновить сведения об аккаунте по кнопке."""
    if not config.token():
        raise HTTPException(400, {"code": "err.noToken"})
    try:
        return await _refresh_account()
    except OSError as exc:
        text = str(exc)
        if "401" in text or "403" in text:
            db.kv_set(conn(), "token_check",
                      {"ok": False, "ts": db.now(), "detail": text[:200]})
        raise HTTPException(400, text) from exc


@app.get("/api/auth/check")
async def auth_check() -> dict:
    """Живой ли доступ: спрашиваем у Диска его же квоту."""
    if not config.token():
        raise HTTPException(400, "нет токена")
    async with _disk() as disk:
        info = await disk.about()
    return {"ok": True, "used_space": info.get("used_space"),
            "total_space": info.get("total_space"),
            "login": (info.get("user") or {}).get("login")}


@app.exception_handler(ValueError)
def value_error(_request, exc: ValueError) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.middleware("http")
async def log_failures(request, call_next):
    """Любая необработанная ошибка -- в лог и в ответ словами.

    Голый "Internal Server Error" в окне не говорит ничего, а трейсбек
    uvicorn под pythonw вообще некуда писать. Теперь причина видна и в
    файле, и в самом интерфейсе.
    """
    try:
        return await call_next(request)
    except Exception as exc:
        log.exception("%s %s упал", request.method, request.url.path)
        return JSONResponse(
            {"detail": f"{type(exc).__name__}: {exc}"}, status_code=500)


_assets_memo: dict = {}


def assets_version() -> str:
    """Отпечаток файлов интерфейса: меняется при любой правке.

    Нужен, чтобы устаревший ассет стал НЕВОЗМОЖЕН, а не "маловероятен".
    В TagConveyor этой беды нет по двум причинам: фронтенд вкомпилирован в
    бинарь Tauri, и сборщик даёт файлам имена с хешем -- адрес меняется
    вместе с содержимым. Здесь файлы отдаются как есть в постоянный профиль
    браузера, поэтому отпечаток считаем сами и подставляем в адрес.
    """
    files = sorted(f for f in WEB.rglob("*")
                   if f.is_file() and f.suffix in (".js", ".css", ".html", ".json"))
    # Ключ памятки -- времена правки: пока они те же, содержимое перечитывать
    # незачем. А вот сам отпечаток берём от СОДЕРЖИМОГО: время правки меняет
    # и git checkout, и копирование, и это гнало бы окно на перезагрузку без
    # единого изменения в коде.
    stamp = tuple((str(f), f.stat().st_mtime_ns, f.stat().st_size) for f in files)
    if _assets_memo.get("stamp") == stamp:
        return _assets_memo["version"]
    digest = hashlib.sha1()
    for f in files:
        digest.update(f.name.encode())
        digest.update(f.read_bytes())
    version = digest.hexdigest()[:12]
    _assets_memo.update(stamp=stamp, version=version)
    return version


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    """Страница с версией в адресах скриптов и стилей.

    Браузер физически не может подсунуть старый app.js: при любой правке
    меняется отпечаток, а с ним -- адрес, по которому его просят.
    """
    html = (WEB / "index.html").read_text(encoding="utf-8")
    ver = assets_version()
    for name in ("app.js", "i18n.js", "style.css", "favicon.ico"):
        html = html.replace(f'"{name}"', f'"{name}?v={ver}"')
    return HTMLResponse(html, headers={"Cache-Control": "no-cache, must-revalidate"})


class FreshFiles(StaticFiles):
    """Отдаёт файлы интерфейса с обязательной перепроверкой.

    StaticFiles ставит только last-modified и etag, а без Cache-Control
    браузер применяет ЭВРИСТИЧЕСКОЕ кэширование: показывает свою копию, не
    спрашивая сервер вовсе. Окно приложения -- постоянный профиль Edge, и
    из-за этого исправленный app.js до него не доезжал: человек видел баг,
    который давно починен, а в моём браузере всё было хорошо.

    no-cache -- это не "не хранить", а "каждый раз переспроси": с etag ответ
    обычно 304 и почти ничего не стоит, зато правка видна сразу.
    """

    async def get_response(self, path: str, scope):
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
        return resp


if WEB.is_dir():
    app.mount("/", FreshFiles(directory=str(WEB), html=True), name="web")
