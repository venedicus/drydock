"""Сверка зеркала с диском: что РЕАЛЬНО лежит локально.

Яндекс.Диск знает о своих файлах мгновенно, потому что клиент сидит в
файловой системе. Нам системный наблюдатель не нужен: обход зеркала
(7,8 тыс. файлов в 17 тыс. папок) занимает 1.4 секунды, поэтому дешевле
сверять часто, чем держать ReadDirectoryChangesW с его переполнением
буфера и особыми случаями переименований.

Что делает сверка:

  * файл на диске, записи в local нет -- заводит её (и ресурс, если
    облако о файле молчит). Это те самые ручные переносы, из-за которых
    переключатель «только нескачанное» показывал уже сохранённое:
    программа о них просто не знала;
  * запись есть, файла нет -- ставит missing=1, и «есть на диске»
    перестаёт врать (файл удалили вручную или перенесли);
  * файл вернулся -- снимает missing.

Хеши здесь НЕ считаются: сверка должна быть быстрой. Проверка -- отдельное
действие («Учесть перенесённое»), и она же ставит verify.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from pathlib import Path

from . import config, db

log = logging.getLogger("drydock.localwatch")

# Фоновая сверка и кнопка «сверить сейчас» могут прийти одновременно.
# Соединение одно, BEGIN/COMMIT внахлёст -- это «cannot start a
# transaction within a transaction». Проще сериализовать: сверка короткая.
_LOCK = threading.Lock()


def _ensure_dirs(conn: sqlite3.Connection, path: str) -> None:
    """Завести в описи все папки-предки файла.

    Без этого дерево считает папку файлом (is_dir берётся из наличия
    ресурса type='dir'), а файл-узел без verify всегда виден в режиме
    «только нескачанное». Так и вышло с ручными переносами: файлы
    учтены, папки -- нет.
    """
    segs = path.split("/")[:-1]  # отбрасываем имя файла
    cur = "disk:"
    for seg in segs[1:]:
        cur = f"{cur}/{seg}"
        if conn.execute("SELECT 1 FROM resources WHERE path=?", (cur,)).fetchone() is None:
            db.upsert_resource(conn, {"path": cur, "name": seg, "type": "dir",
                                      "size": 0, "source": "local"})


def backfill_dirs(conn: sqlite3.Connection) -> int:
    """Разово завести папки для всех файлов, у которых их нет в описи."""
    have = {r["path"] for r in conn.execute(
        "SELECT path FROM resources WHERE type='dir'")}
    made = 0
    for r in conn.execute("SELECT path FROM resources WHERE type='file'"):
        segs = r["path"].split("/")[:-1]
        cur = "disk:"
        for seg in segs[1:]:
            cur = f"{cur}/{seg}"
            if cur not in have:
                db.upsert_resource(conn, {"path": cur, "name": seg,
                                          "type": "dir", "size": 0,
                                          "source": "local"})
                have.add(cur)
                made += 1
    if made:
        log.info("заведено папок в описи: %s", made)
    return made


def _register(conn: sqlite3.Connection, path: str, full: str, size: int) -> None:
    """Завести запись о файле, который лежит на диске мимо программы."""
    if conn.execute("SELECT 1 FROM resources WHERE path=?", (path,)).fetchone() is None:
        db.upsert_resource(conn, {
            "path": path, "name": path.rsplit("/", 1)[-1],
            "type": "file", "size": size, "source": "local",
        })
    _ensure_dirs(conn, path)
    conn.execute(
        """INSERT INTO local(path,local_path,bytes,verify,downloaded_at,
                             released,missing)
           VALUES(?,?,?,'unverified',?,0,0)
           ON CONFLICT(path) DO UPDATE SET
             local_path=excluded.local_path, bytes=excluded.bytes, missing=0""",
        (path, full, size, db.now()))


def scan_disk(root: Path | None = None,
              known: set[str] | None = None,
              *,
              by_local_path: dict[str, str] | None = None) -> dict[str, tuple[str, int | None]]:
    """Что лежит в зеркале: cloud-путь -> (локальный путь, размер).

    Размер нужен только НОВЫМ файлам: для уже известных хватает самого
    факта наличия, а stat на каждый из 7,8 тыс. файлов стоил больше
    самого обхода (замер 18 октября: 3.6 с против 1.4 с).

    by_local_path сопоставляет нормализованный локальный путь с cloud-путем:
    это защищает файлы с символами, замененными на Unicode (\uf03a вместо :),
    укороченными именами или зарезервированными именами от ложного missing=1
    и создания дубликатов.
    """
    files_root = root or config.PATHS.files
    known = known or set()
    local_lookup = by_local_path or {}
    out: dict[str, tuple[str, int | None]] = {}
    for dirpath, _dirnames, filenames in os.walk(files_root):
        for name in filenames:
            if name.endswith(".part"):
                continue  # недокачанное -- не «сохранено»
            full = os.path.join(dirpath, name)
            norm_full = os.path.normcase(os.path.abspath(full))
            if norm_full in local_lookup:
                cloud_path = local_lookup[norm_full]
                out[cloud_path] = (full, None)
                continue
            rel = os.path.relpath(full, files_root).replace(os.sep, "/")
            path = "disk:/" + rel
            if path in known:
                out[path] = (full, None)
                continue
            try:
                out[path] = (full, os.stat(full).st_size)
            except OSError:
                continue
    return out


def sync(conn: sqlite3.Connection, root: Path | None = None) -> dict:
    """Привести local к тому, что на диске. Возвращает, что изменилось."""
    with _LOCK:
        return _sync(conn, root)


def _sync(conn: sqlite3.Connection, root: Path | None = None) -> dict:
    rows_raw = conn.execute(
        "SELECT path, local_path, missing, released FROM local").fetchall()
    by_cloud: dict[str, sqlite3.Row] = {r["path"]: r for r in rows_raw}
    by_local: dict[str, str] = {}
    for r in rows_raw:
        lp = r["local_path"]
        if lp:
            by_local[os.path.normcase(os.path.abspath(lp))] = r["path"]

    on_disk = scan_disk(root, set(by_cloud), by_local_path=by_local)

    added = restored = vanished = 0
    conn.execute("BEGIN")
    try:
        for path, (full, size) in on_disk.items():
            row = by_cloud.get(path)
            if row is None:
                _register(conn, path, full, size or 0)
                added += 1
            elif row["missing"]:
                conn.execute("UPDATE local SET missing=0 WHERE path=?", (path,))
                restored += 1
        for path, row in by_cloud.items():
            # Если файл освобожден после архивации, отсутствие на диске штатно
            if row["released"]:
                continue
            if path in on_disk or row["missing"]:
                continue
            conn.execute("UPDATE local SET missing=1 WHERE path=?", (path,))
            vanished += 1
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise

    if added or restored or vanished:
        log.info("сверка зеркала: новых %s, вернулось %s, пропало %s "
                 "(на диске %s файлов)", added, restored, vanished, len(on_disk))
    return {"added": added, "restored": restored, "vanished": vanished,
            "files": len(on_disk)}
