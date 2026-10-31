"""Опись облака и спасение метаданных.

Это самая срочная часть всей затеи. Данные файла либо есть, либо уже нет --
тут мы ничего не решаем. Но имя, путь, размер, md5, sha256, дата, mime и
превью живут в другом месте и отдаются даже для файлов, чьё содержимое
потеряно. Этого хватает, чтобы потом узнать книгу, найти её в другом месте
и понять, что именно пропало. Поэтому опись снимаем со ВСЕГО и сразу, не
дожидаясь решений о выгрузке.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import time
import uuid
from pathlib import Path

from . import config, db
from .msg import job_msg

log = logging.getLogger("drydock.scan")
from .localpath import ensure_parent, extended, local_for, shorten
from .yandex import Disk

# Чекпоинт описи: очередь папок и счётчики. Прерванный обход продолжается
# с места, а не с корня -- облако огромно, и каждый перезапуск с нуля
# стоил часов. Записи идемпотентны (upsert), повторный проход папки
# безопасен, но это пустая трата времени.
CHECKPOINT_KEY = "scan_queue"
# Как часто чекпоинт попадает в базу, секунд. Чаще -- лишние записи,
# реже -- длиннее повтор после обрыва.
CHECKPOINT_SECONDS = 10.0
# Пульс: строчка в лог во время работы, чтобы «замершая» полоска
# объяснялась последним известным состоянием, а не молчала.
HEARTBEAT_SECONDS = 20.0


def _totals(conn: sqlite3.Connection, root: str) -> tuple[int, int, int]:
    """Сколько в описи под этим корнем: файлов, папок, байт.

    Считаем по базе, а не по счётчикам прохода: продолженный с чекпоинта
    обход заново перечисляет папки, которые уже видел, и любой счётчик
    «за этот запуск» на continuation съезжает. База -- источник правды.
    """
    prefix = root if root.endswith("/") else root + "/"
    row = conn.execute(
        "SELECT COUNT(*) n, COALESCE(SUM(size),0) b FROM resources "
        "WHERE type='file' AND (path=? OR path LIKE ?)",
        (root, f"{prefix}%")).fetchone()
    dirs = conn.execute(
        "SELECT COUNT(*) n FROM resources "
        "WHERE type='dir' AND (path=? OR path LIKE ?)",
        (root, f"{prefix}%")).fetchone()["n"]
    return int(row["n"]), int(dirs), int(row["b"])


async def scan(conn: sqlite3.Connection, disk: Disk, root: str = "disk:/", *,
               job_id: int | None = None,
               make_dirs: bool = True,
               resume: bool = True,
               skip_empty: bool = True,
               concurrency: int | None = None) -> dict:
    """Пройти облако и записать опись.

    make_dirs: сразу создаём локальное дерево папок -- структура должна
    повторять облако один в один, включая папки, из которых не удастся
    вытащить ни одного файла.

    resume: продолжить прерванный обход с сохранённой очереди папок.
    Прерванным считается любое завершение без полного прохода: закрыли
    окно, убили процесс, сеть сдалась -- в finally очередь остаётся в
    базе, и следующий запуск встаёт на то же место.

    skip_empty: не перечислять заново папки, которые в прошлый раз
    оказались пустыми и с тех пор не менялись. Пустая папка стоит
    ровно один запрос и не даёт ничего, а таких папок в коллекции
    тысячи -- именно они съедали время описи. Выключается полной
    перепроверкой (--full в CLI, галочка в интерфейсе).
    """
    paths = config.PATHS
    paths.ensure()
    stack = [root]
    files = 0
    dirs = 0
    base_dirs = 0
    total_bytes = 0
    seen_dirs: set[str] = set()
    # Папки, которые в прошлый раз оказались пустыми: путь -> дата
    # изменения на тот момент. Пока сервер отдаёт ту же дату, внутрь
    # смотреть незачем. Список нужен всегда: по нему видно, какие
    # пометки пора снять, а пропускать по нему -- только когда включено.
    known_empty: dict[str, str] = db.known_empty_dirs(conn)
    skipped_dirs = 0

    def _skip_dir(item: dict) -> bool:
        """Эту папку перечислять не нужно?"""
        nonlocal skipped_dirs
        if not skip_empty:
            return False
        path = item.get("path") or ""
        was = known_empty.get(path)
        if was is None:
            return False
        if was != (item.get("modified") or ""):
            # Папку меняли -- смотрим внутрь.
            return False
        skipped_dirs += 1
        return True

    def _folder_done(path: str, empty: bool) -> None:
        """Папку перечислили: запомнить, пустая ли она."""
        if empty:
            db.mark_empty(conn, path, True)
        elif path in known_empty:
            # Папка перестала быть пустой -- пометку снимаем, иначе
            # следующая опись пропустит её и не увидит файл.
            db.mark_empty(conn, path, False)

    # Точка отсчёта для сверки «что исчезло из облака». У ПРОДОЛЖЕННОЙ описи
    # она наследуется из чекпоинта: иначе всё, описанное до обрыва, не
    # попало бы в этот проход и было бы объявлено пропавшим.
    started = db.now()
    # Сверять можно только зная, когда начался ВЕСЬ обход. У чекпоинта,
    # записанного старой версией, этого поля нет: взяв вместо него «сейчас»,
    # сверка объявила бы пропавшим всё, что описано до обрыва, -- десятки
    # тысяч файлов разом. В таком случае сверку просто пропускаем.
    can_reconcile = True
    if resume:
        saved = db.kv_get(conn, CHECKPOINT_KEY)
        if saved and saved.get("root") == root and saved.get("stack"):
            if saved.get("started"):
                started = int(saved["started"])
            else:
                can_reconcile = False
                log.info("чекпоинт без точки отсчёта -- сверка с облаком "
                         "пропускается, она пройдёт на следующей полной описи")
            stack = [str(p) for p in saved["stack"]]
            files = int(saved.get("files") or 0)
            base_dirs = int(saved.get("dirs") or 0)
            total_bytes = int(saved.get("bytes") or 0)
            dirs = base_dirs
            log.info("опись продолжается с чекпоинта: в очереди %s папок, "
                     "ранее собрано файлов %s", len(stack), files)
    # Живая очередь папок от walk: в базу пишем не на каждой папке,
    # а с throttling: на дни идущей описи это сотни лишних записей.
    # Структура меняется на месте -- копия на каждое событие при
    # десятках тысяч папок стоила бы дороже самой описи.
    pending: dict[str, None] = {p: None for p in stack}
    last_checkpoint = time.monotonic()

    def _save_checkpoint() -> None:
        nonlocal last_checkpoint
        db.kv_set(conn, CHECKPOINT_KEY, {
            "root": root, "stack": list(pending), "files": files,
            "dirs": dirs, "bytes": total_bytes, "at": db.now(),
            "started": started})
        last_checkpoint = time.monotonic()

    def _watch(queue: dict[str, None]) -> None:
        nonlocal pending
        pending = queue
        if time.monotonic() - last_checkpoint >= CHECKPOINT_SECONDS:
            _save_checkpoint()

    # Отмена запоминается флагом: walk во время паузы ретрая по ней просто
    # выходит, и без флага это неотличимо от обычного конца очереди --
    # чекпоинт снялся бы, а недолистанные папки потерялись.
    stop_requested = False

    def _stop() -> bool:
        nonlocal stop_requested
        wanted = job_id is not None and db.job_cancelled(conn, job_id)
        stop_requested = stop_requested or wanted
        return wanted

    completed = False
    last_beat = time.monotonic()
    try:
        with open(extended(paths.catalog_jsonl), "a", encoding="utf-8") as cat:  # noqa: ASYNC230 - буферизованная запись на локальный диск
            # Обходу отдаём саму очередь: свежая опись начинает с корня,
            # продолженная -- с папок, оставшихся в чекпоинте.
            async for item in disk.walk(
                    stack or [root],
                    should_stop=_stop,
                    on_pending=_watch,
                    skip=_skip_dir,
                    on_folder=_folder_done,
                    concurrency=concurrency):
                # catalog.jsonl -- журнал того, что сервер рассказывал о
                # файлах, и писать в него стоит только НОВОЕ или
                # ИЗМЕНИВШЕЕСЯ. Раньше каждая опись дописывала каталог
                # целиком: 124 тысячи строк на 41 тысячу путей и 332 МБ
                # почти одинакового текста, который потом ещё и уезжает в
                # архивы. Полный слепок и так лежит в базе, в resources.raw.
                fresh = json.dumps(item, ensure_ascii=False)
                prev = conn.execute("SELECT raw FROM resources WHERE path=?",
                                    (item.get("path"),)).fetchone()
                db.upsert_resource(conn, item)
                if prev is None or prev["raw"] != fresh:
                    cat.write(fresh + "\n")
                if item.get("type") == "dir":
                    # Папка приходит дважды: как элемент родителя и как "сама
                    # себя" при входе внутрь. Запись идемпотентна, а вот счётчик
                    # без set() завышал бы итог вдвое. При продолжении с
                    # чекпоинта к итогу прибавляются папки прошлого прохода.
                    seen_dirs.add(item["path"])
                    dirs = base_dirs + len(seen_dirs)
                    if make_dirs:
                        target = local_for(item["path"], paths.files)
                        try:
                            Path(extended(target)).mkdir(parents=True, exist_ok=True)
                        except OSError:
                            pass
                else:
                    files += 1
                    total_bytes += int(item.get("size") or 0)
                if job_id is not None and (files + dirs) % 50 == 0:
                    db.job_progress(conn, job_id, files + dirs,
                                    message=job_msg("scan.count",
                                                    files=files, dirs=dirs))
                    _watch(pending)
                    if time.monotonic() - last_beat >= HEARTBEAT_SECONDS:
                        log.info("опись: файлов %s, папок %s, в очереди %s, "
                                 "сейчас %s", files, dirs, len(pending),
                                 item.get("path"))
                        last_beat = time.monotonic()
                    if _stop():
                        break
        # «Дошли до конца» -- это только когда обход сам истощил очередь.
        # Отмена посреди папки и отмена во время паузы ретрая выглядят
        # как обычный конец цикла -- их и отличаем по флагу запроса.
        completed = not stop_requested
    finally:
        # Прервали или упали -- очередь остаётся в базе, следующий запуск
        # продолжит с неё. Дошли до конца -- чекпоинт больше не нужен.
        if completed:
            db.kv_del(conn, CHECKPOINT_KEY)
        else:
            _save_checkpoint()
    # Итог -- по базе: продолжение с чекпоинта перечисляет часть папок
    # заново, и счётчики этого прохода завысили бы ответ.
    vanished = (reconcile(conn, root, started)
                if completed and can_reconcile else 0)
    files, dirs, total_bytes = _totals(conn, root)
    db.kv_set(conn, "last_scan", {"files": files, "dirs": dirs,
                                  "bytes": total_bytes, "at": db.now(),
                                  "complete": completed, "vanished": vanished,
                                  "skipped_empty": skipped_dirs})
    out = {"files": files, "dirs": dirs, "bytes": total_bytes}
    if vanished:
        out["vanished"] = vanished
    if skipped_dirs:
        # Пропущенные папки -- это не «мы их не посмотрели», а «мы знаем,
        # что они пустые, и сервер с тех пор их не менял». Сказать об
        # этом честно: человек должен видеть, сколько опись не смотрела.
        log.info("опись: пропущено известно пустых папок: %s", skipped_dirs)
        out["skipped_empty"] = skipped_dirs
    return out


def reconcile(conn: sqlite3.Connection, root: str, started: int) -> int:
    """Отметить то, чего в облаке больше нет.

    Опись -- слепок, а облако живёт дальше. 18 октября из него ушли
    CzarStream-папки на 710 ГБ, и экран продолжал показывать их как
    существующие: цифры врали, пока кто-то не полез проверять руками.

    Делается ТОЛЬКО после полного обхода: прерванный не видел часть дерева,
    и всё недосмотренное он объявил бы пропавшим. Запись не удаляется --
    имя, размер и хеши остаются, ведь именно они и нужны для поиска копии
    на стороне; меняется лишь отметка «в облаке этого больше нет».
    """
    pre = root if root.endswith("/") else root + "/"
    post = pre[:-1] + "0"
    cur = conn.execute(
        "UPDATE resources SET vanished_at=? "
        "WHERE vanished_at IS NULL AND last_seen < ? "
        "  AND (path = ? OR (path >= ? AND path < ?))",
        (db.now(), started, root.rstrip("/") or root, pre, post))
    gone = cur.rowcount or 0
    # Вернулось -- снимаем отметку: в облаке бывает и такое.
    back = conn.execute(
        "UPDATE resources SET vanished_at=NULL "
        "WHERE vanished_at IS NOT NULL AND last_seen >= ?", (started,)).rowcount or 0
    if gone or back:
        log.info("сверка с облаком: пропало %s, вернулось %s", gone, back)
    # Пометка «пустая» ушедшей папки больше не нужна: папки нет, и
    # пропускать её при следующей описи незачем.
    conn.execute("DELETE FROM empty_dirs WHERE path IN "
                 "(SELECT path FROM resources WHERE vanished_at IS NOT NULL)")
    return gone


def preview_dest(cloud_path: str) -> Path:
    """Превью лежит в том же дереве, что и файл -- так его можно
    просто листать глазами в проводнике, рядом с названиями книг."""
    rel = local_for(cloud_path, Path())
    # ".jpg" добавляется ПОСЛЕ safe_component и тоже растит длину: имя
    # книги на 250 символов дало бы компонент в 254+4 и Errno 22. Режем
    # уже окончательное имя -- 17 октября на этом умерла порция превью.
    return config.PATHS.previews / rel.parent / shorten(rel.name + ".jpg")


async def harvest_previews(conn: sqlite3.Connection, disk: Disk,
                           paths: list[str] | None = None, *,
                           job_id: int | None = None,
                           refresh: bool = False) -> dict:
    """Скачать превью для файлов. Делается для всех, не только доступных.

    Ссылка на превью из описи живёт недолго, поэтому на отказ пробуем
    переспросить ресурс и взять свежую ссылку.
    """
    config.PATHS.ensure()
    if paths is None:
        sql = ("SELECT r.path, r.preview FROM resources r "
               "LEFT JOIN meta_saved m ON m.path=r.path "
               "WHERE r.type='file' AND r.preview IS NOT NULL")
        args: list[object] = []
        if not refresh:
            # Превью, которого сервер не отдал, -- такое же наблюдение со
            # сроком, как и доступность: ЦОД может вернуться, и пробовать
            # стоит снова, но не каждый раз. Без срока 3400 битых превью
            # перезапрашивались при КАЖДОМ проходе, съедая его целиком и
            # не давая дойти до тех, что ещё не пробовали ни разу.
            from .probe import stale_before
            sql += (" AND (m.path IS NULL OR ("
                    "m.preview_state NOT IN ('ok','missing') AND m.saved_at < ?))")
            args.append(stale_before())
        # Сначала те, что не пробовали вовсе: первый проход важнее повторов.
        sql += " ORDER BY (m.path IS NOT NULL), r.size"
        rows = conn.execute(sql, args).fetchall()
    else:
        qs = ",".join("?" * len(paths))
        rows = conn.execute(
            f"SELECT path, preview FROM resources WHERE type='file' AND path IN ({qs})",
            paths).fetchall()

    todo = [(r["path"], r["preview"]) for r in rows if r["preview"]]
    counters = {"ok": 0, "missing": 0, "error": 0}
    lock = asyncio.Lock()
    done = 0

    async def one(cloud_path: str, url: str) -> None:
        nonlocal done
        # Один файл не имеет права ронять порцию: имя на 250+ символов,
        # отказ диска, что угодно ещё. Пишем ошибку в строку файла и идём
        # дальше. 17 октября OSError Errno 22 на имени книги убил задачу
        # после часа описи -- 24 577 файлов в базе остались без превью.
        try:
            dest = preview_dest(cloud_path)
            state, status = await disk.fetch_preview(url, dest)
            if state.startswith("error"):
                # Ссылка могла просто истечь -- берём свежую и пробуем ещё раз.
                fresh = await _fresh_preview_url(conn, disk, cloud_path)
                if fresh:
                    state, status = await disk.fetch_preview(fresh, dest)
            if state == "error" and status:
                # Без кода ответа "error" ничего не объясняет: 404 у превью и
                # 504 от раненого хранилища -- это разные истории.
                state = f"error HTTP {status}"
        except Exception as exc:  # noqa: BLE001 - порция живёт днями, одна книга не её цена
            state = f"error: {type(exc).__name__}: {str(exc)[:100]}"
            status = None
        key = "ok" if state == "ok" else ("missing" if state == "missing" else "error")
        if key == "error":
            # Превью живёт отдельно от файла и часто умирает первым --
            # по этим строкам видно, что именно не отдаёт сервер.
            log.warning("превью не взялось: %s -- %s", cloud_path, state)
        async with lock:
            counters[key] += 1
            done += 1
            conn.execute(
                """INSERT INTO meta_saved(path,preview_file,preview_state,saved_at)
                   VALUES(?,?,?,?)
                   ON CONFLICT(path) DO UPDATE SET
                     preview_file=excluded.preview_file,
                     preview_state=excluded.preview_state,
                     saved_at=excluded.saved_at""",
                (cloud_path, str(dest) if key == "ok" else None, state, db.now()))
            if job_id is not None and done % 25 == 0:
                db.job_progress(conn, job_id, done, len(todo),
                                f"превью: сохранено {counters['ok']}")

    batch = 0
    for i in range(0, len(todo), 200):
        chunk = todo[i:i + 200]
        await asyncio.gather(*(one(p, u) for p, u in chunk))
        batch += len(chunk)
        if job_id is not None:
            db.job_progress(conn, job_id, batch, len(todo))
            if db.job_cancelled(conn, job_id):
                break
    return counters | {"total": len(todo)}


async def _fresh_preview_url(conn: sqlite3.Connection, disk: Disk,
                             cloud_path: str) -> str | None:
    try:
        data = await disk.listdir(cloud_path, limit=0)
    except (FileNotFoundError, OSError):
        return None
    url = data.get("preview")
    if url:
        db.upsert_resource(conn, {k: v for k, v in data.items() if k != "_embedded"})
    return url


def compact_catalog(conn: sqlite3.Connection) -> dict:
    """Пересобрать catalog.jsonl из базы, без повторов.

    До появления журнала изменений каждая опись дописывала каталог целиком,
    и файл раздувался кратно числу проходов. Содержимое при этом не
    теряется: полный ответ сервера по каждому ресурсу лежит в resources.raw,
    так что файл собирается заново из базы.
    """
    dest = config.PATHS.catalog_jsonl
    before = dest.stat().st_size if dest.is_file() else 0
    tmp = dest.with_name(f"{dest.name}.{uuid.uuid4().hex[:8]}.tmp")
    rows = conn.execute("SELECT raw FROM resources ORDER BY path")
    n = 0
    with open(extended(tmp), "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(row["raw"] + "\n")
            n += 1
    os.replace(extended(tmp), extended(dest))
    after = dest.stat().st_size
    log.info("catalog.jsonl пересобран: %s записей, %.0f -> %.0f МБ",
             n, before / 2**20, after / 2**20)
    return {"records": n, "before": before, "after": after}


def export_manifest(conn: sqlite3.Connection, dest: Path | None = None) -> Path:
    """Опись в один человекочитаемый файл.

    База -- рабочий инструмент, а этот файл кладётся в архивы и переживёт
    потерю всего остального: по нему книгу можно узнать и через год.
    """
    dest = dest or (config.PATHS.meta / "inventory.jsonl")
    ensure_parent(dest)
    rows = conn.execute(
        """SELECT r.path, r.name, r.size, r.md5, r.sha256, r.mime, r.media_type,
                  r.created, r.modified, r.resource_id,
                  p.state AS probe_state, p.checked_at,
                  l.verify, l.bytes AS local_bytes,
                  m.preview_state
           FROM resources r
           LEFT JOIN probe p ON p.path=r.path
           LEFT JOIN local l ON l.path=r.path
           LEFT JOIN meta_saved m ON m.path=r.path
           WHERE r.type='file' ORDER BY r.path""").fetchall()
    # Пишем во временный файл и подменяем готовым. Две причины, и обе
    # случились на деле: две описи, запущенные подряд, писали ОДИН файл, и
    # вторая получала PermissionError -- на Windows открытый на запись файл
    # второму писателю не отдаётся; а оборванная на середине запись оставила
    # бы обрезанную опись вместо прежней, целой.
    # Имя уникально НА ВЫЗОВ, а не на процесс: обе описи живут в одном
    # сервере, и общий tmp по pid столкнул бы их ровно так же, как раньше
    # сталкивал общий inventory.jsonl.
    tmp = dest.with_name(f"{dest.name}.{uuid.uuid4().hex[:8]}.tmp")
    with open(extended(tmp), "w", encoding="utf-8") as fh:
        fh.writelines(json.dumps(dict(row), ensure_ascii=False) + "\n" for row in rows)
    # Хвосты прошлых неудач не копим.
    for old_tmp in dest.parent.glob(f"{dest.name}.*.tmp"):
        if old_tmp != tmp and db.now() - int(old_tmp.stat().st_mtime) > 3600:
            old_tmp.unlink(missing_ok=True)
    for attempt in range(5):
        try:
            os.replace(extended(tmp), extended(dest))
            break
        except PermissionError:
            # Файл читает кто-то ещё (проводник, антивирус) -- подождём.
            if attempt == 4:
                log.warning("опись не заменена, оставляю рядом: %s", tmp)
                return tmp
            time.sleep(0.4)
    return dest
