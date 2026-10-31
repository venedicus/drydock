"""Каталог спасения: единственный источник правды о том, что мы уже знаем.

Почему SQLite, а не json: операция растянута на дни и на много порций, её
рвут перезапуски, а доступность файлов в облаке плавает (8.1 ГБ из 21.3
"вернулись" через вечер). Нужна база, которую можно переспросить и
дополнить, а не слепок.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Self

SCHEMA = """
PRAGMA journal_mode=WAL;

-- Опись облака. Живёт даже для файлов, чьи данные уже не отдаются:
-- имя, размер, хеши и превью -- это то, что спасаем в первую очередь.
CREATE TABLE IF NOT EXISTS resources(
  path        TEXT PRIMARY KEY,
  parent      TEXT,
  name        TEXT NOT NULL,
  type        TEXT NOT NULL,
  size        INTEGER,
  md5         TEXT,
  sha256      TEXT,
  mime        TEXT,
  media_type  TEXT,
  created     TEXT,
  modified    TEXT,
  resource_id TEXT,
  revision    INTEGER,
  preview     TEXT,
  raw         TEXT NOT NULL,
  first_seen  INTEGER NOT NULL,
  last_seen   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_res_parent ON resources(parent, type, name);
CREATE INDEX IF NOT EXISTS ix_res_type   ON resources(type, size DESC);

-- Папки, которые при последнем перечислении оказались пустыми. Пустая
-- папка стоит ровно один запрос и не даёт ничего, а таких папок в
-- коллекции тысячи -- именно они съедали время описи. Пока сервер отдаёт
-- ту же дату изменения, такую папку можно не перечислять заново.
-- modified здесь -- тот, что был В МОМЕНТ находки: текущая дата папки
-- живёт в resources.modified и меняется на каждой описи, а сравнивать
-- надо именно с тем, что видели тогда.
CREATE TABLE IF NOT EXISTS empty_dirs(
  path     TEXT PRIMARY KEY,
  modified TEXT,
  at       INTEGER NOT NULL
);

-- Проба доступности: отдаёт ли хранилище первый байт. Скачивания нет.
CREATE TABLE IF NOT EXISTS probe(
  path         TEXT PRIMARY KEY,
  state        TEXT NOT NULL,
  http_status  INTEGER,
  storage_host TEXT,
  -- Последний узел, о котором мы вообще что-то знали. storage_host
  -- затирается каждым наблюдением, а 404 хоста не сообщает -- и узел
  -- терялся. Это поле не чистится никогда: по нему видно, где файл
  -- лежал, даже когда облако уже отвечает «нет такого».
  last_host    TEXT,
  detail       TEXT,
  checked_at   INTEGER NOT NULL,
  attempts     INTEGER NOT NULL DEFAULT 1,
  first_ok_at  INTEGER,
  last_ok_at   INTEGER
);
CREATE INDEX IF NOT EXISTS ix_probe_state ON probe(state, checked_at);

-- История проб: доступность плавает, и это надо видеть, а не затирать.
CREATE TABLE IF NOT EXISTS probe_history(
  path TEXT NOT NULL, state TEXT NOT NULL, http_status INTEGER, ts INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ph_path ON probe_history(path, ts DESC);

-- Что уже спасено на диск и сошлись ли хеши.
CREATE TABLE IF NOT EXISTS local(
  path          TEXT PRIMARY KEY,
  local_path    TEXT NOT NULL,
  bytes         INTEGER NOT NULL,
  sha256        TEXT,
  md5           TEXT,
  verify        TEXT NOT NULL,
  holes         TEXT,
  -- Когда файл последний раз спасли с дырками (0 -- никогда). Нужно,
  -- чтобы отличить «докачали полностью» от «с самого начала целый»:
  -- без этой отметки второй счётчик посчитать неоткуда.
  salvaged_at   INTEGER NOT NULL DEFAULT 0,
  downloaded_at INTEGER NOT NULL,
  released      INTEGER NOT NULL DEFAULT 0,
  -- Файла нет на диске (удалён вручную, перенесён, стёрт чистилкой).
  -- Сверка зеркала ставит и снимает этот флаг: без него «есть на диске»
  -- считалось по записи в базе, а не по факту.
  missing       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_local_verify ON local(verify, released);

-- Превью и опись: спасаем для ВСЕХ файлов, включая недоступные.
CREATE TABLE IF NOT EXISTS meta_saved(
  path          TEXT PRIMARY KEY,
  preview_file  TEXT,
  preview_state TEXT,
  saved_at      INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS archives(
  id         INTEGER PRIMARY KEY,
  name       TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  state      TEXT NOT NULL,
  bytes      INTEGER,
  note       TEXT
);
CREATE TABLE IF NOT EXISTS archive_volumes(
  archive_id INTEGER NOT NULL, volume TEXT NOT NULL, bytes INTEGER, sha256 TEXT
);
CREATE TABLE IF NOT EXISTS archive_members(
  archive_id INTEGER NOT NULL, path TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_am_path ON archive_members(path);
CREATE INDEX IF NOT EXISTS ix_am_arch ON archive_members(archive_id);

-- Удаления из облака: необратимо, поэтому пишем отдельно и подробно.
CREATE TABLE IF NOT EXISTS cloud_deleted(
  path TEXT PRIMARY KEY, deleted_at INTEGER NOT NULL,
  permanently INTEGER NOT NULL, response TEXT
);

CREATE TABLE IF NOT EXISTS jobs(
  id          INTEGER PRIMARY KEY,
  kind        TEXT NOT NULL,
  state       TEXT NOT NULL,
  total       INTEGER NOT NULL DEFAULT 0,
  done        INTEGER NOT NULL DEFAULT 0,
  started_at  INTEGER NOT NULL,
  finished_at INTEGER,
  message     TEXT,
  cancel      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);

-- Отчёт «Здоровье» группирует по дате: без этих индексов он сканировал
-- историю проб (115 тыс. строк) и читался полсекунды.
CREATE INDEX IF NOT EXISTS ix_ph_ts      ON probe_history(ts);
CREATE INDEX IF NOT EXISTS ix_local_dl   ON local(downloaded_at);
CREATE INDEX IF NOT EXISTS ix_cd_deleted ON cloud_deleted(deleted_at);
CREATE INDEX IF NOT EXISTS ix_jobs_start ON jobs(started_at);

"""


def connect(path: Path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(Path(path), isolation_level=None, timeout=30,
                           check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=NORMAL")
    # База 279 МБ, и почти все запросы -- агрегаты по 26 тыс. строк с
    # соединениями. Без mmap и с кэшем по умолчанию это чтение с диска:
    # замер 18 октября -- 206 мс на выборку 21 тыс. строк, с mmap 256 МБ
    # и кэшем 64 МБ -- 77 мс. На раскрытии дерева и итогах это заметно.
    conn.execute("PRAGMA mmap_size=268435456")
    conn.execute("PRAGMA cache_size=-65536")
    # Своя функция «сложить регистр»: встроенные LIKE и lower() понимают
    # только латиницу, поэтому «отчёт» не находил «Отчёт». casefold знает
    # и кириллицу, и турецкую i.
    conn.create_function("fold", 1, lambda v: (v or "").casefold(),
                         deterministic=True)
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def prune_history(conn: sqlite3.Connection, keep_days: int) -> int:
    """Убрать историю проб старше keep_days. Возвращает, сколько удалили."""
    if keep_days <= 0:
        return 0
    cutoff = now() - keep_days * 86400
    cur = conn.execute("DELETE FROM probe_history WHERE ts < ?", (cutoff,))
    return int(cur.rowcount or 0)


def _migrate(conn: sqlite3.Connection) -> None:
    """Довести старую базу до текущей схемы.

    CREATE TABLE IF NOT EXISTS не добавляет колонки в существующую
    таблицу, поэтому новые поля заводятся здесь и только если их нет.
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(local)")}
    if "missing" not in cols:
        conn.execute("ALTER TABLE local ADD COLUMN missing INTEGER NOT NULL DEFAULT 0")
    pcols = {r["name"] for r in conn.execute("PRAGMA table_info(probe)")}
    if "last_host" not in pcols:
        conn.execute("ALTER TABLE probe ADD COLUMN last_host TEXT")
        # Восстанавливаем из того, что ещё помним.
        conn.execute("UPDATE probe SET last_host=storage_host "
                     "WHERE last_host IS NULL AND storage_host IS NOT NULL")
    if "salvaged_at" not in cols:
        conn.execute("ALTER TABLE local ADD COLUMN salvaged_at INTEGER NOT NULL DEFAULT 0")

    # Опись -- слепок, а облако живёт дальше: 18 октября из него ушли
    # CzarStream-папки на 710 ГБ, и экран продолжал показывать их как
    # существующие. Здесь отмечается то, чего в облаке больше нет.
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(resources)")}
    if "vanished_at" not in cols:
        conn.execute("ALTER TABLE resources ADD COLUMN vanished_at INTEGER")
        conn.execute("CREATE INDEX IF NOT EXISTS ix_res_vanished "
                     "ON resources(vanished_at)")


def now() -> int:
    return int(time.time())


def kv_get(conn: sqlite3.Connection, key: str, default: Any = None) -> Any:
    row = conn.execute("SELECT v FROM kv WHERE k=?", (key,)).fetchone()
    return json.loads(row["v"]) if row else default


def kv_set(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                 (key, json.dumps(value, ensure_ascii=False)))


def kv_del(conn: sqlite3.Connection, key: str) -> None:
    conn.execute("DELETE FROM kv WHERE k=?", (key,))


def known_empty_dirs(conn: sqlite3.Connection) -> dict[str, str]:
    """Папки, которые в прошлый раз оказались пустыми: путь -> дата изменения.

    Дата изменения та, что была в момент находки: текущая лежит в
    resources.modified и меняется на каждой описи.
    """
    rows = conn.execute("SELECT path, modified FROM empty_dirs").fetchall()
    return {r["path"]: r["modified"] or "" for r in rows}


def mark_empty(conn: sqlite3.Connection, path: str, empty: bool) -> None:
    """Пометить папку пустой -- или снять пометку, если там что-то есть.

    Пометку обязательно снимать: папка, в которую положили файл, больше
    не пустая, и если оставить её в списке «пустых», следующая опись
    пропустит её и не увидит файл.
    """
    if empty:
        conn.execute(
            "INSERT INTO empty_dirs(path, modified, at) "
            "VALUES(?, (SELECT modified FROM resources WHERE path=?), ?) "
            "ON CONFLICT(path) DO UPDATE SET "
            "modified=excluded.modified, at=excluded.at",
            (path, path, now()))
    else:
        conn.execute("DELETE FROM empty_dirs WHERE path=?", (path,))


def upsert_resource(conn: sqlite3.Connection, item: dict) -> None:
    """Запись одного ресурса описи.

    raw храним целиком: на сервере может быть поле, цена которого
    выяснится только при восстановлении, а второго шанса спросить не будет.
    """
    path = item.get("path") or ""
    parent = path.rsplit("/", 1)[0] if "/" in path else None
    if parent == "disk:":
        parent = "disk:/"
    ts = now()
    conn.execute(
        """INSERT INTO resources(path,parent,name,type,size,md5,sha256,mime,media_type,
                                 created,modified,resource_id,revision,preview,raw,
                                 first_seen,last_seen)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(path) DO UPDATE SET
             parent=excluded.parent, name=excluded.name, type=excluded.type,
             size=excluded.size, md5=excluded.md5, sha256=excluded.sha256,
             mime=excluded.mime, media_type=excluded.media_type,
             created=excluded.created, modified=excluded.modified,
             resource_id=excluded.resource_id, revision=excluded.revision,
             preview=excluded.preview, raw=excluded.raw, last_seen=excluded.last_seen""",
        (path, parent, item.get("name") or "", item.get("type") or "file",
         item.get("size"), item.get("md5"), item.get("sha256"),
         item.get("mime_type"), item.get("media_type"),
         item.get("created"), item.get("modified"),
         item.get("resource_id"), item.get("revision"), item.get("preview"),
         json.dumps(item, ensure_ascii=False), ts, ts),
    )


def record_probe(conn: sqlite3.Connection, path: str, state: str,
                 http_status: int | None = None, storage_host: str | None = None,
                 detail: str | None = None) -> None:
    ts = now()
    ok = state == "ok"
    conn.execute(
        """INSERT INTO probe(path,state,http_status,storage_host,last_host,detail,
                             checked_at,attempts,first_ok_at,last_ok_at)
           VALUES(?,?,?,?,?,?,?,1,?,?)
           ON CONFLICT(path) DO UPDATE SET
             state=excluded.state, http_status=excluded.http_status,
             storage_host=excluded.storage_host, detail=excluded.detail,
             last_host=COALESCE(excluded.storage_host, probe.last_host),
             checked_at=excluded.checked_at, attempts=probe.attempts+1,
             first_ok_at=COALESCE(probe.first_ok_at, excluded.first_ok_at),
             last_ok_at=COALESCE(excluded.last_ok_at, probe.last_ok_at)""",
        (path, state, http_status, storage_host, storage_host,
         (detail or "")[:500], ts,
         ts if ok else None, ts if ok else None),
    )
    conn.execute("INSERT INTO probe_history(path,state,http_status,ts) VALUES(?,?,?,?)",
                 (path, state, http_status, ts))


def job_start(conn: sqlite3.Connection, kind: str, total: int = 0) -> int:
    cur = conn.execute(
        "INSERT INTO jobs(kind,state,total,done,started_at) VALUES(?,'running',?,0,?)",
        (kind, total, now()))
    return int(cur.lastrowid)


def job_progress(conn: sqlite3.Connection, job_id: int, done: int,
                 total: int | None = None, message: str | None = None) -> None:
    if total is None:
        conn.execute("UPDATE jobs SET done=?, message=COALESCE(?,message) WHERE id=?",
                     (done, message, job_id))
    else:
        conn.execute("UPDATE jobs SET done=?, total=?, message=COALESCE(?,message) WHERE id=?",
                     (done, total, message, job_id))


def job_finish(conn: sqlite3.Connection, job_id: int, state: str,
               message: str | None = None) -> None:
    conn.execute(
        "UPDATE jobs SET state=?, finished_at=?, message=COALESCE(?,message) WHERE id=?",
        (state, now(), message, job_id))


def job_cancelled(conn: sqlite3.Connection, job_id: int) -> bool:
    row = conn.execute("SELECT cancel FROM jobs WHERE id=?", (job_id,)).fetchone()
    return bool(row and row["cancel"])


class CancelWatch:
    """Флаг «нажали стоп», который видит КАЖДЫЙ файл, а не только порция.

    Раньше отмена проверялась между порциями по 25-50 файлов, а порция
    ждёт самый медленный файл в ней -- до двух минут таймаута выгрузки.
    Нажатие «стоп» выглядело как проигнорированное. Теперь флаг
    подтягивается из базы в фоне, а каждый файл перед началом смотрит на
    него: уже начатое доводится до конца (обрывать запись на середине
    незачем -- .part всё равно докачается), новое не начинается.
    """

    def __init__(self, conn: sqlite3.Connection, job_id: int | None,
                 period: float = 0.4) -> None:
        self._conn = conn
        self._job_id = job_id
        self._period = period
        self._stop = False
        self._task: object | None = None

    def __call__(self) -> bool:
        return self._stop

    async def __aenter__(self) -> Self:
        import asyncio
        if self._job_id is None:
            return self

        async def poll() -> None:
            while not self._stop:
                try:
                    self._stop = job_cancelled(self._conn, self._job_id)
                except sqlite3.Error:
                    pass
                if self._stop:
                    break
                await asyncio.sleep(self._period)

        self._task = asyncio.create_task(poll())
        return self

    async def __aexit__(self, *exc: object) -> None:
        import asyncio
        self._stop = True
        task = self._task
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
