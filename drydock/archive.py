"""Упаковка спасённого в 7z-тома под Телеграм.

Основа взята из TagConveyor (core/tagconveyor/offload.py): 7z без сжатия,
тома по 3900 МБ (премиум-Телеграм берёт файлы до 4 ГБ), порции по
свободному месту с неприкосновенным запасом, проверка `7z t`, и никаких
удалений до того, как проверка прошла. Что изменено под эту задачу:

1. Оригиналы НЕ удаляются сразу после упаковки. В TagConveyor это было
   нужно, чтобы освободить место под следующую порцию. Здесь между
   упаковкой и освобождением места есть человек: он уносит тома в Телеграм.
   Поэтому удаление вынесено в отдельный шаг `release`, который делается
   по явной команде, и только для архива в состоянии verified.

2. Считается sha256 каждого тома. Том уедет в Телеграм и вернётся оттуда
   через месяцы: нужно чем-то проверить, что он вернулся целым. У
   TagConveyor этого не было -- там архив оставался на своём диске.

3. Внутри архива лежит не только манифест, но и превью: пути `files/...`
   и `meta/previews/...` складываются от корня спасения, так что архив
   распаковывается ровно в ту же структуру, из которой собран.

4. Один запуск -- один набор томов. Недозаполнен только последний том
   набора, поэтому порцию не дробят на мелкие архивы без нужды.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from . import config, db

log = logging.getLogger("drydock.archive")
from .localpath import extended
from .scan import preview_dest


def seven_zip() -> Path | None:
    for cand in (shutil.which("7z"), shutil.which("7za"),
                 r"C:\Program Files\7-Zip\7z.exe",
                 r"C:\Program Files (x86)\7-Zip\7z.exe"):
        if cand and Path(cand).is_file():
            return Path(cand)
    return None


def plan_batch(sizes: list[int], free: int, reserve: int | None = None) -> int:
    """Сколько первых файлов влезает в порцию. 0 -- не влезает и первый.

    Архив без сжатия весит столько же, сколько файлы: заголовки -- доли
    процента, их покрывает запас. Оригиналы в момент упаковки ещё на диске,
    поэтому в свободное место должен уложиться именно архив целиком.
    """
    budget = free - (config.RESERVE if reserve is None else reserve)
    total = n = 0
    for size in sizes:
        if total + size > budget:
            break
        total += size
        n += 1
    return n


def pending(conn: sqlite3.Connection, paths: list[str] | None = None) -> list[dict]:
    """Что готово к упаковке: спасено, проверено, ещё не в архиве, не убрано."""
    where = ["l.released=0", "l.verify IN ('ok','salvaged','unverified')",
             "am.path IS NULL"]
    args: list[object] = []
    if paths:
        where.append(f"l.path IN ({','.join('?' * len(paths))})")
        args += paths
    rows = conn.execute(
        f"""SELECT l.path, l.local_path, l.bytes, l.verify, r.name
            FROM local l
            JOIN resources r ON r.path=l.path
            LEFT JOIN archive_members am ON am.path=l.path
            WHERE {' AND '.join(where)}
            ORDER BY l.bytes ASC""", args).fetchall()
    return [dict(r) for r in rows]


def _run(cmd: list[str], cwd: Path,
         should_stop: Callable[[], bool] | None = None) -> tuple[int, str]:
    """Запустить 7z так, чтобы его можно было остановить.

    Раньше здесь был subprocess.run -- вызов, который нельзя прервать. На
    одной паковке он держал процесс часами, а «стоп» в это время лишь
    помечал задачу отменённой: 19 октября 7z пережил и отмену, и закрытие
    приложения и работал ещё пятнадцать часов, пока его не сняли вручную.

    Поэтому Popen и опрос: раз в полсекунды смотрим, не попросили ли
    остановиться, и тогда просим 7z завершиться, а через десять секунд
    снимаем. Недописанные тома убирает вызывающий -- он знает их имена.
    """
    proc = subprocess.Popen(
        cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    chunks: list[str] = []
    while True:
        try:
            out, _ = proc.communicate(timeout=0.5)
            chunks.append(out or "")
            return proc.returncode, "".join(chunks)[-4000:]
        except subprocess.TimeoutExpired:
            if should_stop is not None and should_stop():
                log.info("останавливаю 7z по запросу")
                proc.terminate()
                try:
                    out, _ = proc.communicate(timeout=10)
                    chunks.append(out or "")
                except subprocess.TimeoutExpired:
                    proc.kill()
                    chunks.append("\n[7z не завершился сам, снят принудительно]")
                return STOPPED, "".join(chunks)[-4000:]


# Код возврата, которым _run сообщает «остановлено», а не «сломалось».
STOPPED = -9


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(extended(path), "rb") as fh:
        while chunk := fh.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def build(conn: sqlite3.Connection, paths: list[str] | None = None, *,
          job_id: int | None = None, runner=_run,
          volume: str | None = None, compression: str | None = None,
          should_stop: Callable[[], bool] | None = None) -> dict:
    """Упаковать готовое в тома. Оригиналы остаются на месте.

    volume -- размер тома для 7z (например "3900m" под Телеграм-премиум,
    "1900m" под обычный, "0" -- не дробить вовсе). compression -- ключ
    вроде "-mx0". Оба задаются на запуск: раньше они брались только из
    переменных окружения, и поменять их из окна было нельзя.
    """
    exe = seven_zip()
    if exe is None and runner is _run:
        raise ValueError("не найден 7-Zip (7z.exe) -- установите 7-Zip")
    root = config.PATHS.root
    out_dir = config.PATHS.archives
    out_dir.mkdir(parents=True, exist_ok=True)

    items = pending(conn, paths)
    items = [it for it in items if Path(extended(Path(it["local_path"]))).is_file()]
    if not items:
        raise ValueError("нечего упаковывать: нет проверенных файлов вне архивов")

    vol = volume or config.VOLUME
    comp = compression or config.COMPRESSION
    if should_stop is None and job_id is not None:
        def should_stop() -> bool:
            return db.job_cancelled(conn, job_id)

    made: list[dict] = []
    total, done = len(items), 0
    while items:
        if should_stop is not None and should_stop():
            break
        free = shutil.disk_usage(out_dir).free
        n = plan_batch([it["bytes"] for it in items], free)
        if n == 0:
            raise ValueError(
                f"на {out_dir.anchor} не хватает места даже на один файл "
                f"({items[0]['bytes'] / 2**30:.1f} ГБ + запас "
                f"{config.RESERVE / 2**30:.0f} ГБ); упаковано {done} из {total}")
        batch, items = items[:n], items[n:]
        made.append(_one_archive(conn, exe, root, out_dir, batch, runner,
                                 vol, comp, should_stop))
        done += len(batch)
        if job_id is not None:
            db.job_progress(conn, job_id, done, total,
                            f"наборов {len(made)}, файлов {done}")
    return {"archives": made, "files": done, "total": total}


def _one_archive(conn: sqlite3.Connection, exe: Path | None, root: Path,
                 out_dir: Path, batch: list[dict], runner,
                 vol: str, comp: str,
                 should_stop: Callable[[], bool] | None = None) -> dict:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    name = f"CR_{stamp}"
    archive = out_dir / f"{name}.7z"
    cur = conn.execute(
        "INSERT INTO archives(name,created_at,state,bytes) VALUES(?,?,'building',?)",
        (name, db.now(), sum(it["bytes"] for it in batch)))
    archive_id = int(cur.lastrowid)

    # Манифест: по нему книгу узнают и через год, даже если база потеряна.
    manifest_rel = f"{name}_manifest.json"
    manifest_abs = root / manifest_rel
    entries = []
    for it in batch:
        row = conn.execute(
            """SELECT r.path, r.name, r.size, r.md5, r.sha256, r.mime, r.media_type,
                      r.created, r.modified, r.raw,
                      l.sha256 AS local_sha256, l.verify, l.holes,
                      p.state AS probe_state
               FROM resources r
               LEFT JOIN local l ON l.path=r.path
               LEFT JOIN probe p ON p.path=r.path
               WHERE r.path=?""", (it["path"],)).fetchone()
        if row is None:
            continue
        # sqlite3.Row -- не словарь: при переборе он отдаёт ЗНАЧЕНИЯ,
        # поэтому .keys() здесь обязателен (ruff SIM118 этого не знает).
        rec = {k: row[k] for k in row.keys() if k != "raw"}  # noqa: SIM118
        rec["cloud_meta"] = json.loads(row["raw"] or "{}")
        entries.append(rec)
    manifest_abs.write_text(
        json.dumps({"archive": name, "created": stamp, "files": entries},
                   ensure_ascii=False, indent=1), encoding="utf-8")

    # Список для 7z: пути ОТНОСИТЕЛЬНО корня спасения, поэтому внутри
    # архива сохраняется та же структура, и распаковка возвращает её as is.
    listed: list[str] = [manifest_rel]
    for it in batch:
        try:
            listed.append(str(Path(it["local_path"]).resolve().relative_to(root.resolve())))
        except ValueError:
            listed.append(str(Path(it["local_path"])))
        prev = preview_dest(it["path"])
        if Path(extended(prev)).is_file():
            try:
                listed.append(str(prev.resolve().relative_to(root.resolve())))
            except ValueError:
                pass
    listfile = out_dir / f".{name}.list.txt"
    listfile.write_text("\n".join(listed), encoding="utf-8")

    # "0" -- просьба не дробить: один файл архива вместо томов.
    split = [] if str(vol).strip() in ("", "0") else [f"-v{vol}"]
    cmd = [str(exe), "a", "-t7z", comp, *split,
           "-y", "-scsUTF-8", "-ssw", str(archive), f"@{listfile}"]
    code, out = runner(cmd, root, should_stop)
    if code == 0:
        first = Path(f"{archive}.001")
        target = first if first.exists() else archive
        code, out = runner([str(exe), "t", "-y", str(target)], root,
                           should_stop)
    if code != 0:
        # Имя не vol: так звался бы аргумент «размер тома», и путаница
        # между ним и файлом тома тут совсем некстати.
        for leftover in out_dir.glob(f"{archive.name}*"):
            leftover.unlink(missing_ok=True)
        listfile.unlink(missing_ok=True)
        manifest_abs.unlink(missing_ok=True)
        conn.execute("UPDATE archives SET state='failed', note=? WHERE id=?",
                     (out[-900:], archive_id))
        raise ValueError(f"7z завершился с ошибкой, файлы на месте: {out[-400:]}")

    volumes = sorted(out_dir.glob(f"{archive.name}.0*")) or [archive]
    # Имя не vol: так зовётся аргумент «размер тома», и путать его с файлом
    # тома тут совсем некстати.
    for part in volumes:
        conn.execute(
            "INSERT INTO archive_volumes(archive_id,volume,bytes,sha256) VALUES(?,?,?,?)",
            (archive_id, part.name, part.stat().st_size, _sha256(part)))
    for it in batch:
        conn.execute("INSERT INTO archive_members(archive_id,path) VALUES(?,?)",
                     (archive_id, it["path"]))
    conn.execute("UPDATE archives SET state='verified' WHERE id=?", (archive_id,))

    # Манифест и опись кладём ещё и рядом с томами: чтобы посмотреть, что
    # внутри набора, не надо его распаковывать.
    shutil.move(str(manifest_abs), str(out_dir / manifest_rel))
    (out_dir / f"{name}_volumes.txt").write_text(
        "\n".join(f"{_sha256_cached(conn, archive_id, v.name)}  {v.name}  {v.stat().st_size}"
                  for v in volumes), encoding="utf-8")
    listfile.unlink(missing_ok=True)

    return {"id": archive_id, "name": name, "files": len(batch),
            "volumes": [v.name for v in volumes],
            "bytes": sum(v.stat().st_size for v in volumes)}


def _sha256_cached(conn: sqlite3.Connection, archive_id: int, volume: str) -> str:
    row = conn.execute(
        "SELECT sha256 FROM archive_volumes WHERE archive_id=? AND volume=?",
        (archive_id, volume)).fetchone()
    return (row["sha256"] if row else "") or ""


def verify(conn: sqlite3.Connection, archive_id: int) -> dict:
    """Пересчитать sha256 томов и сравнить с записанным при упаковке.

    Это проверка на дорогу: том уходит в Телеграм и возвращается оттуда,
    и повреждение надо заметить до того, как оригиналы удалены.
    """
    rows = conn.execute(
        "SELECT volume, bytes, sha256 FROM archive_volumes WHERE archive_id=?",
        (archive_id,)).fetchall()
    out = {"ok": [], "bad": [], "missing": []}
    for r in rows:
        vol = config.PATHS.archives / r["volume"]
        if not Path(extended(vol)).is_file():
            out["missing"].append(r["volume"])
        elif _sha256(vol) == r["sha256"]:
            out["ok"].append(r["volume"])
        else:
            out["bad"].append(r["volume"])
    return out


def release(conn: sqlite3.Connection, archive_id: int, *,
            require_verified: bool = True) -> dict:
    """Убрать локальные оригиналы упакованного -- освободить место под
    следующую порцию. Только для проверенного архива, и только после того,
    как тома действительно лежат на диске целыми."""
    row = conn.execute("SELECT name, state FROM archives WHERE id=?",
                       (archive_id,)).fetchone()
    if row is None:
        raise ValueError(f"нет архива {archive_id}")
    if require_verified and row["state"] != "verified":
        raise ValueError(f"архив {row['name']} в состоянии {row['state']}, не verified")
    check = verify(conn, archive_id)
    if check["bad"] or check["missing"]:
        raise ValueError(
            f"тома архива {row['name']} не сходятся (битых {len(check['bad'])}, "
            f"нет {len(check['missing'])}) -- оригиналы не трогаю")

    freed = count = 0
    for r in conn.execute(
            """SELECT l.path, l.local_path, l.bytes FROM archive_members am
               JOIN local l ON l.path=am.path
               WHERE am.archive_id=? AND l.released=0""", (archive_id,)).fetchall():
        p = Path(r["local_path"])
        try:
            if Path(extended(p)).is_file():
                os.remove(extended(p))
            conn.execute("UPDATE local SET released=1 WHERE path=?", (r["path"],))
            freed += int(r["bytes"] or 0)
            count += 1
        except OSError:
            continue
    return {"released": count, "freed_bytes": freed}
