"""Удаление файлов из облака -- чтобы освободить место в квоте.

Это единственное место в программе, которое что-то ломает необратимо, и
единственное, где осторожность важнее удобства. Правила:

1. Удалять можно только то, что ТОЧНО спасено. "Спасено" означает: хеш
   скачанного файла сошёлся с тем, что сам Яндекс сообщил о файле. Не
   "скачалось без ошибки" -- именно сошёлся хеш.

2. Файлы, собранные salvage-режимом, не удаляются НИКОГДА. У них внутри
   дырки: часть содержимого потеряна. Облачная копия -- единственный шанс
   дочитать остальное, если машины хранилища оживут. Удалить её означает
   добить файл своими руками.

3. По умолчанию требуется не просто скачанный файл, а проверенный архив:
   тома на диске, их sha256 сходятся. Телеграм -- не гарантия, но хотя бы
   два носителя вместо нуля.

4. permanently=true. Корзина Яндекса держит удалённое 30 дней и всё это
   время занимает место в квоте, а смысл удаления ровно в освобождении
   места. Обратного хода после этого нет.

5. Ничего не удаляется само. Нужен явный вызов с confirm=<число файлов>:
   случайным кликом такое не делается.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from pathlib import Path

from . import config, db

log = logging.getLogger("drydock.cloud")
from .archive import verify as verify_archive
from .localpath import extended
from .yandex import Disk

# Состояния local.verify, при которых файл считается спасённым полностью.
SAFE_VERIFY = ("ok",)

# Состояния пробы, при которых файл уже не спасётся: хранилище его не
# отдаёт или проба не смогла получить ответ. "gone" сюда не входит --
# объекта нет, удалять нечего; "unchecked" -- ещё не приговор, сначала
# проба. Уровень "junk" чистит квоту ровно от этого.
JUNK_STATES = ("unavailable", "api_error", "unknown")


def _is_file_fast(path: str) -> bool:
    """Есть ли файл, без лишнего обхода файловой системы.

    `extended()` зовёт resolve() -- это второй системный вызов на каждый
    путь: 7,7 тыс. проверок выходили 1.5 с вместо 0.5 с. Префикс \\?\
    нужен только для путей длиннее 240 символов, поэтому обычный путь
    проверяем напрямую, а длинный -- через extended.
    """
    if not path:
        return False
    try:
        if Path(path).is_file():
            return True
        if len(path) >= 240:
            return Path(extended(Path(path))).is_file()
        return False
    except OSError:
        return False


def eligible(conn: sqlite3.Connection, paths: list[str] | None = None, *,
             level: str = "downloaded") -> tuple[list[dict], list[dict]]:
    """Что можно удалить из облака, а что нельзя и почему.

    level="downloaded" -- достаточно проверенной копии на диске (по умолчанию)
    level="archived"   -- вдобавок нужен проверенный архив (строже)
    level="junk"       -- не спасено и уже не спасётся: недоступно или
                          проба не смогла ответить. Всё, что доступно,
                          не трогаем -- его ещё можно скачать; "gone" не
                          трогаем -- объекта уже нет, удалять нечего.
    level="selected"   -- ровно то, что человек выбрал в дереве. Проверку
                          «спасено ли» не применяем: выбор -- его решение,
                          а интерфейс отдельно предупреждает, сколько из
                          выбранного не спасено. Не берём только "gone" --
                          там удалять нечего.

    Архив -- это ВТОРОЙ носитель, а не пропуск к удалению. Требовать его
    всегда означало бы, что место в облаке нельзя освободить, пока тома не
    уехали в Телеграм, -- а порядок действий выбирает владелец коллекции.
    Поэтому по умолчанию хватает того, что файл скачан и его хеш сошёлся с
    тем, который сообщил сам Яндекс.
    """
    where = ["r.type='file'", "cd.path IS NULL"]
    args: list[object] = []
    if paths:
        where.append(f"r.path IN ({','.join('?' * len(paths))})")
        args += paths
    rows = conn.execute(
        f"""SELECT r.path, r.size, r.md5, r.sha256,
                   l.verify, l.local_path, l.bytes, l.released, l.holes,
                   COALESCE(p.state,'unchecked') AS probe_state,
                   am.archive_id, a.state AS archive_state, a.name AS archive_name
            FROM resources r
            LEFT JOIN local l  ON l.path=r.path
            LEFT JOIN probe p  ON p.path=r.path
            LEFT JOIN cloud_deleted cd ON cd.path=r.path
            LEFT JOIN archive_members am ON am.path=r.path
            LEFT JOIN archives a ON a.id=am.archive_id
            WHERE {' AND '.join(where)}""", args).fetchall()

    ok: list[dict] = []
    blocked: list[dict] = []
    checked_archives: dict[int, bool] = {}
    for r in rows:
        rec = dict(r)
        if level == "selected":
            # Выбор человека важнее эвристик: он мог сознательно удалить
            # то, что спасать не собирается. Единственное, что остаётся
            # за программой, -- не отправлять запрос по файлам, которых в
            # облаке уже нет.
            if r["probe_state"] == "gone":
                blocked.append(rec | {"reason": "в облаке уже нет -- удалять нечего"})
            else:
                ok.append(rec)
            continue
        if level == "junk":
            # Мусор -- только то, что НЕ спасено и не спасётся. Спасённое
            # удаляется обычным уровнем, а непроверенное сначала надо
            # проверить: это ещё не приговор.
            if r["verify"]:
                blocked.append(rec | {"reason": "уже спасено -- удаляй обычным уровнем"})
            elif r["probe_state"] in JUNK_STATES:
                ok.append(rec)
            elif r["probe_state"] == "gone":
                blocked.append(rec | {"reason": "в облаке уже нет -- удалять нечего"})
            elif r["probe_state"] == "unchecked":
                blocked.append(rec | {"reason": "не проверено -- сначала проба"})
            else:
                blocked.append(rec | {"reason": "доступно -- ещё можно скачать"})
            continue
        if not r["verify"]:
            blocked.append(rec | {"reason": "не скачан"})
            continue
        if r["verify"] == "salvaged" or r["holes"]:
            blocked.append(rec | {"reason": "собран с дырками, облачная копия нужна"})
            continue
        if r["verify"] not in SAFE_VERIFY:
            blocked.append(rec | {"reason": f"проверка хеша: {r['verify']}"})
            continue
        if level == "archived":
            if not r["archive_id"] or r["archive_state"] != "verified":
                blocked.append(rec | {"reason": "нет проверенного архива"})
                continue
            aid = int(r["archive_id"])
            if aid not in checked_archives:
                res = verify_archive(conn, aid)
                checked_archives[aid] = not (res["bad"] or res["missing"])
            if not checked_archives[aid]:
                blocked.append(rec | {"reason": f"тома архива {r['archive_name']} не сходятся"})
                continue
        else:
            if r["released"]:
                blocked.append(rec | {"reason": "локальный оригинал уже убран"})
                continue
            p = r["local_path"] or ""
            if not _is_file_fast(p):
                blocked.append(rec | {"reason": "локального файла нет на диске"})
                continue
            if int(r["bytes"] or 0) != int(r["size"] or 0):
                blocked.append(rec | {"reason": "размер на диске не совпал"})
                continue
        ok.append(rec)
    return ok, blocked


def _audit(entry: dict) -> None:
    path = config.PATHS.audit
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(extended(path), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


async def delete(conn: sqlite3.Connection, disk: Disk, paths: list[str], *,
                 level: str = "downloaded", confirm: int = -1,
                 permanently: bool = True, job_id: int | None = None) -> dict:
    """Удалить из облака. confirm должен совпасть с числом файлов к удалению."""
    allowed, blocked = eligible(conn, paths, level=level)
    if confirm != len(allowed):
        raise ValueError(
            f"не подтверждено: к удалению подходит {len(allowed)} файлов "
            f"(отклонено {len(blocked)}), а confirm={confirm}. "
            f"Передай confirm={len(allowed)}, если согласен.")
    if not allowed:
        return {"deleted": 0, "blocked": len(blocked), "failed": 0}

    lock = asyncio.Lock()
    done = {"deleted": 0, "failed": 0, "errors": []}

    async def one(rec: dict) -> None:
        ok, detail = await disk.delete(rec["path"], permanently=permanently)
        # 404 = объекта уже нет. Так бывает штатно: клиент Яндекс.Диска
        # видит, что файл убран из его папки (мы перенесли), и удаляет
        # облачную копию сам -- наша явная попытка приходит второй.
        # Это НЕ ошибка: цель достигнута, копии в облаке нет.
        already = (not ok) and ("404" in detail or "DiskNotFoundError" in detail)
        async with lock:
            if ok or already:
                conn.execute(
                    """INSERT INTO cloud_deleted(path,deleted_at,permanently,response)
                       VALUES(?,?,?,?) ON CONFLICT(path) DO UPDATE SET
                         deleted_at=excluded.deleted_at,
                         permanently=excluded.permanently,
                         response=excluded.response""",
                    (rec["path"], db.now(), 1 if permanently else 0,
                     ("уже отсутствовало: " + detail[:280]) if already else detail[:300]))
                # Своё удаление -- не потеря (в тогдашней правке введена
                # таблица cloud_deleted именно для этого), но и не «живое».
                # Без этой строки проба ещё долго показывала удалённое как
                # доступное: к 18 октября накопилось 427 файлов, на которых
                # интерфейс предлагал скачивать то, чего в облаке уже нет.
                db.record_probe(conn, rec["path"], "gone", 404, None,
                                "удалено нами из облака")
                if already:
                    done["already"] = done.get("already", 0) + 1
                else:
                    done["deleted"] += 1
                _audit({"ts": db.now(), "action": "cloud_delete", "path": rec["path"],
                        "size": rec["size"], "sha256": rec["sha256"],
                        "level": level, "permanently": permanently,
                        "archive": rec.get("archive_name")})
            else:
                done["failed"] += 1
                if len(done["errors"]) < 50:
                    done["errors"].append({"path": rec["path"], "error": detail})
            if job_id is not None:
                db.job_progress(conn, job_id,
                                done["deleted"] + done.get("already", 0) + done["failed"],
                                len(allowed), f"удалено {done['deleted']}")

    for i in range(0, len(allowed), 50):
        if job_id is not None and db.job_cancelled(conn, job_id):
            break
        await asyncio.gather(*(one(r) for r in allowed[i:i + 50]))
    return done | {"blocked": len(blocked)}
