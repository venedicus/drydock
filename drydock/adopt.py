"""Усыновление локальной папки Яндекс.Диска.

Часть коллекции клиент Диска когда-то синхронизировал на компьютер, и эти
файлы никуда не делись. Для нас это не просто экономия трафика:

    из 20 160 найденных файлов 3 425 НЕДОСТУПНЫ в облаке.

Их нельзя скачать ни при каких условиях -- повреждённые ЦОДы их не отдают.
Они существуют ровно в одном месте: в локальной папке. Если их не забрать,
они пропадут вместе с ней -- при переустановке клиента, очистке места или
первой же "синхронизации" удалений.

Как берём. Обе папки обычно на одном томе, поэтому по умолчанию ставится
ЖЁСТКАЯ ССЫЛКА: мгновенно и без единого лишнего байта. 239 ГБ копией не
влезли бы в 76 ГБ свободных -- а ссылка не занимает ничего. Данные при этом
не "общие с Яндексом": файл на диске один, и он останется, даже если клиент
удалит свою ссылку. Копия нужна только для другого тома или если хочется
полной независимости от клиента (--copy).

Хеши сверяем с теми, что сообщил сам Яндекс: без этого файл не считается
спасённым и не допускается к удалению из облака. Сверка читает все данные,
то есть на сотнях гигабайт идёт долго, -- её можно отключить (--no-verify),
но тогда состояние будет "unverified" со всеми следствиями.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sqlite3
import uuid
from pathlib import Path

from . import config, db
from .localpath import ensure_parent, extended, local_for
from .yandex import Disk

log = logging.getLogger("drydock.adopt")

# Папка, куда клиент Яндекс.Диска складывает синхронизированное.
DEFAULT_SOURCE = Path(os.environ.get(
    "DRYDOCK_YADISK", str(Path.home() / "Yandex.Disk")))


# Папка клиента Яндекс.Диска -- это Cloud Files API, как OneDrive: файл
# может быть ЗАГЛУШКОЙ. Размер у неё настоящий, имя на месте, а данных на
# диске нет -- они подтягиваются при открытии, то есть из того самого
# облака, которое сейчас и не отдаёт. Сравнение по размеру тут обманывает:
# «нашлось 20 160 файлов на 239 ГБ», а материализовано из них 1 254 на 19 ГБ.
# Поэтому заглушки отсеиваем по атрибутам ФС, до всякого чтения.
FILE_ATTRIBUTE_OFFLINE = 0x1000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000
PLACEHOLDER = (FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_OPEN
               | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS)
INVALID_ATTRS = 0xFFFFFFFF


def is_placeholder(path: Path) -> bool:
    """Правда ли это пустышка без данных на диске."""
    if os.name != "nt":
        return False
    import ctypes
    attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
    if attrs == INVALID_ATTRS:
        return True  # не прочитать атрибуты -- не трогаем
    return bool(attrs & PLACEHOLDER)


def source_for(cloud_path: str, source: Path) -> Path:
    """disk:/Library/book.pdf -> <папка клиента>/Library/book.pdf.

    Имя берём ИСХОДНОЕ, как в облаке: у клиента Яндекса те же имена, что на
    сервере, и наши замены запрещённых символов тут ни при чём.
    """
    rel = cloud_path
    for prefix in ("disk:/", "disk:"):
        if rel.startswith(prefix):
            rel = rel[len(prefix):]
            break
    parts = [p for p in rel.split("/") if p]
    direct = source.joinpath(*parts)
    if direct.exists() or len(parts) < 2:
        return direct
    # Папка клиента может быть САМА подпапкой облака: папка «Отчёты» на
    # рабочем столе -- это disk:/Отчёты, а не disk:/Отчёты/Отчёты. Из-за
    # этого опрос однажды показал ноль при двух тысячах файлов в папке.
    shorter = source.joinpath(*parts[1:])
    return shorter if shorter.exists() else direct


def candidates(conn: sqlite3.Connection, source: Path,
               paths: list[str] | None = None) -> list[dict]:
    """Что из описи лежит в локальной папке и ещё не спасено."""
    where = ["r.type='file'", "(l.path IS NULL OR l.verify NOT IN ('ok','salvaged'))"]
    args: list[object] = []
    if paths:
        where.append(f"r.path IN ({','.join('?' * len(paths))})")
        args += paths
    rows = conn.execute(
        f"""SELECT r.path, r.size, r.md5, r.sha256, COALESCE(p.state,'unchecked') AS state
            FROM resources r
            LEFT JOIN local l ON l.path=r.path
            LEFT JOIN probe p ON p.path=r.path
            WHERE {' AND '.join(where)}
            ORDER BY r.size""", args).fetchall()
    out = []
    placeholders = 0
    for r in rows:
        src = source_for(r["path"], source)
        try:
            if not Path(extended(src)).is_file():
                continue
            size = Path(extended(src)).stat().st_size
        except OSError:
            continue
        if size != int(r["size"] or -1):
            continue
        if is_placeholder(src):
            placeholders += 1
            continue
        out.append({"path": r["path"], "src": src, "size": size,
                    "md5": r["md5"], "sha256": r["sha256"], "state": r["state"]})
    if placeholders:
        log.info("пропущено заглушек без данных: %s", placeholders)
    return out


def survey(conn: sqlite3.Connection, source: Path | None = None) -> dict:
    """Сколько и чего можно забрать -- без единого изменения на диске."""
    source = source or DEFAULT_SOURCE
    if not source.is_dir():
        return {"source": str(source), "exists": False, "files": 0, "bytes": 0}
    items = candidates(conn, source)
    by_state: dict[str, int] = {}
    for it in items:
        by_state[it["state"]] = by_state.get(it["state"], 0) + 1
    linked = linked_candidates(conn, source)
    return {
        "source": str(source), "exists": True,
        "files": len(items), "bytes": sum(it["size"] for it in items),
        "by_state": by_state,
        # Главная цифра: столько файлов не вытащить ниоткуда, кроме этой папки.
        "only_here": by_state.get("unavailable", 0) + by_state.get("gone", 0),
        "same_volume": same_volume(source, config.PATHS.files),
        # Уже взятое ссылками: перенос надо доделать (убрать запись из
        # папки клиента и облачную копию), иначе оно так и останется
        # наполовину перенесённым.
        "linked": len(linked),
        "linked_bytes": sum(it["size"] for it in linked),
    }


def same_volume(a: Path, b: Path) -> bool:
    """Можно ли обойтись ссылкой вместо копии."""
    def anchor(p: Path) -> str:
        probe = Path(p)
        while not probe.exists() and probe.parent != probe:
            probe = probe.parent
        return str(probe.anchor).upper()
    return anchor(a) == anchor(b)


def _take(src: Path, staged: Path, *, mode: str = "move") -> str:
    """Подготовить перенос, ссылку или копию во временном файле.

    Источник не убирается до проверки хеша: клиент Диска иначе может
    увидеть временное исчезновение, удалить облачную копию, а сверка
    обнаружит mismatch уже после гонки с синхронизацией.
    """
    ensure_parent(staged)
    if mode in ("move", "link"):
        try:
            # На одном томе это атомарно и не требует второго места. Для
            # move это только staging-ссылка; исходное имя остаётся до
            # проверки хеша и установки назначения.
            os.link(extended(src), extended(staged))
            return "move-link" if mode == "move" else "link"
        except OSError:
            pass  # другой том или ФС без ссылок -- безопасно копируем
    # Заглушка могла проскочить candidates (атрибуты меняются между
    # обходом и взятием) -- или ссылка не сработала именно на ней
    # (WinError 362). Копировать такую нельзя: copy2 пойдёт
    # материализовывать данные из того самого облака, которое не отдаёт,
    # и поток повиснет на часы.
    if is_placeholder(src):
        raise OSError("файл в папке клиента -- заглушка без данных, "
                      "облако её не отдаёт")
    free = shutil.disk_usage(staged.parent).free
    if free - src.stat().st_size < config.RESERVE:
        raise OSError("не хватает места на копию")
    shutil.copy2(extended(src), extended(staged))
    return "move-copy" if mode == "move" else "copy"


def _discard_staged(staged: Path) -> None:
    """Убрать подготовленную ссылку/копию, оставив исходник и назначение."""
    try:
        os.remove(extended(staged))
    except FileNotFoundError:
        pass


def adopt_one(conn: sqlite3.Connection, item: dict, *, mode: str = "move",
              verify: bool = True) -> dict:
    from .download import _hashes

    dest = local_for(item["path"], config.PATHS.files)
    staged = dest.with_name(f"_cr_adopt_{uuid.uuid4().hex}.tmp")
    try:
        how = _take(item["src"], staged, mode=mode)
        state = "unverified"
        md5 = sha = None
        if verify:
            md5, sha = _hashes(staged)
            if ((item["sha256"] and sha.lower() == str(item["sha256"]).lower())
                    or (item["md5"] and md5.lower() == str(item["md5"]).lower())):
                state = "ok"
            elif not item["sha256"] and not item["md5"]:
                state = "unverified"
            else:
                state = "mismatch"
                log.warning("хеш не сошёлся у локального %s -- файл испорчен "
                            "или это другая версия", item["path"])

        if state == "mismatch":
            # Новый файл не прошёл сверку: назначение и источник должны
            # остаться нетронутыми. На одном томе staging -- лишь hardlink.
            _discard_staged(staged)
            return {"path": item["path"], "state": state, "how": how}

        # Замена назначения атомарна: существующая копия остаётся на месте,
        # пока временный файл не прошёл проверку и не готов к установке.
        os.replace(extended(staged), extended(dest))
        if how in ("move-link", "move-copy"):
            # Исходник удаляем только после того, как проверенная копия
            # установлена. Если уборка не удалась, остаётся две копии --
            # это безопаснее, чем потерять файл.
            try:
                os.remove(extended(item["src"]))
                how = "move"
            except OSError as exc:
                log.warning("копия %s принята, исходник оставить не удалось: %s",
                            item["path"], exc)
                how = "copy"
    except OSError as exc:
        try:
            _discard_staged(staged)
        except OSError as discard_exc:
            # Не удалять исходник/назначение; staging останется рядом для
            # восстановления, если фильтр файловой системы держит handle.
            log.error("не удалось убрать временную копию %s: %s",
                      staged, discard_exc)
        log.warning("не взять %s: %s", item["path"], exc)
        return {"path": item["path"], "state": "failed", "error": str(exc)}

    conn.execute(
        """INSERT INTO local(path,local_path,bytes,sha256,md5,verify,holes,
                             downloaded_at,released)
           VALUES(?,?,?,?,?,?,NULL,?,0)
           ON CONFLICT(path) DO UPDATE SET
             local_path=excluded.local_path, bytes=excluded.bytes,
             sha256=excluded.sha256, md5=excluded.md5,
             verify=excluded.verify, holes=NULL,
             downloaded_at=excluded.downloaded_at, released=0""",
        (item["path"], str(dest), item["size"], sha, md5, state, db.now()))
    return {"path": item["path"], "state": state, "how": how}


def linked_candidates(conn: sqlite3.Connection,
                      source: Path | None = None) -> list[dict]:
    """Что уже взято ЖЁСТКОЙ ССЫЛКОЙ и не доделано.

    Прежний механизм ставил ссылку: файл оставался в папке клиента (и в
    облаке), а в зеркале появлялась вторая запись на те же данные. При
    переносе так быть не должно, поэтому такие пары надо доделать:
    убрать запись из папки клиента (данные остаются в зеркале -- это один
    и тот же файл на диске) и удалить облачную копию после сверки.

    Признак ссылки -- совпадение тома и inode у источника и зеркала.
    """
    source = source or DEFAULT_SOURCE
    out: list[dict] = []
    for r in conn.execute(
            "SELECT path, local_path, bytes FROM local "
            "WHERE verify='ok' AND released=0"):
        dest = Path(r["local_path"] or "")
        src = source_for(r["path"], source)
        try:
            if not (src.is_file() and dest.is_file()):
                continue
            a, b = os.stat(extended(src)), os.stat(extended(dest))
        except OSError:
            continue
        if a.st_dev == b.st_dev and a.st_ino == b.st_ino:
            out.append({"path": r["path"], "src": src, "dest": dest,
                        "size": int(r["bytes"] or 0)})
    out.sort(key=lambda it: it["path"])
    return out


def unlink_one(item: dict) -> dict:
    """Убрать ссылку из папки клиента. Данные остаются в зеркале."""
    try:
        # Перепроверяем inode прямо перед удалением: если файл успели
        # пересоздать, это уже другая запись -- её трогать нельзя.
        a = os.stat(extended(item["src"]))
        b = os.stat(extended(item["dest"]))
        if (a.st_dev, a.st_ino) != (b.st_dev, b.st_ino):
            return {"path": item["path"], "state": "changed"}
        try:
            os.remove(extended(item["src"]))
        except OSError:
            # Имя в 255 символов: удаление через промежуточное короткое
            # имя (удаление длинного пути спотыкается на некоторых
            # оболочках и фильтрах файловой системы).
            tmp = item["src"].with_name(
                "_cr_del_" + item["src"].name[:16].strip() + ".tmp")
            os.replace(extended(item["src"]), extended(tmp))
            os.remove(extended(tmp))
    except OSError as exc:
        return {"path": item["path"], "state": "failed", "error": str(exc)}
    return {"path": item["path"], "state": "unlinked"}


async def run(conn: sqlite3.Connection, source: Path | None = None, *,
              paths: list[str] | None = None, mode: str = "move",
              verify: bool = True, delete_cloud: bool = True,
              disk: Disk | None = None,
              job_id: int | None = None) -> dict:
    """Забрать всё, что нашлось в локальной папке клиента.

    mode="move" -- перенос: файл уходит из папки клиента в нашу, клиент
    Диска видит пропажу и убирает его из облака. delete_cloud=True
    добивает облачную копию явно, но ТОЛЬКО для файлов, чей хеш сошёлся
    с сообщённым Яндексом: непроверенное не удаляется никогда (уровень
    "downloaded" в cloud.eligible проверяет это ещё раз).

    Работа упирается в диск, а не в сеть, поэтому идём по одному файлу и
    отдаём управление циклу между ними: иначе долгая сверка хешей подвесила
    бы интерфейс целиком.
    """
    source = source or DEFAULT_SOURCE
    if not source.is_dir():
        raise ValueError(f"папки {source} нет -- укажи, где лежит Яндекс.Диск")
    items = candidates(conn, source, paths)
    counters: dict[str, int] = {}
    stop = db.CancelWatch(conn, job_id)
    taken_bytes = 0
    adopted_ok: list[str] = []
    # Сперва доделываем то, что взято ЖЁСТКИМИ ССЫЛКАМИ прежним
    # механизмом: запись в папке клиента убираем (данные остаются в
    # зеркале -- это тот же файл), облачную копию удалим ниже вместе с
    # остальными. Иначе такие файлы навсегда остаются «наполовину
    # перенесёнными»: и в облаке, и в папке клиента.
    linked = linked_candidates(conn, source)
    linked_ok: list[str] = []
    async with stop:
        for n, item in enumerate(linked, 1):
            if stop():
                counters["cancelled"] = 1
                break
            res = await asyncio.to_thread(unlink_one, item)
            counters["linked_" + res["state"]] = \
                counters.get("linked_" + res["state"], 0) + 1
            if res["state"] == "unlinked":
                linked_ok.append(item["path"])
            if job_id is not None and n % 25 == 0:
                db.job_progress(conn, job_id, n, len(linked) + len(items),
                                f"доделано ссылок {counters.get('linked_unlinked', 0)}")
        for n, item in enumerate(items, 1):
            if stop():
                counters["cancelled"] = 1
                break
            result = await asyncio.to_thread(
                adopt_one, conn, item, mode=mode, verify=verify)
            counters[result["state"]] = counters.get(result["state"], 0) + 1
            if result["state"] in ("ok", "unverified"):
                taken_bytes += item["size"]
            if result["state"] == "ok":
                # Удалять из облака можно только то, что сошлось хешем.
                adopted_ok.append(item["path"])
            if job_id is not None and n % 10 == 0:
                db.job_progress(conn, job_id, n + len(linked),
                                len(linked) + len(items),
                                f"взято {counters.get('ok', 0)}, "
                                f"{taken_bytes / 2**30:.1f} ГБ")
    counters["bytes"] = taken_bytes

    # Облачные копии -- и только что перенесённых, и доделанных ссылок.
    cloud_ok = linked_ok + adopted_ok
    if delete_cloud and cloud_ok and disk is not None:
        from . import cloud

        # cloud.eligible ещё раз проверит: хеш сошёлся, файл на диске,
        # размер совпал, архива не требует (level="downloaded").
        allowed, _blocked = cloud.eligible(conn, cloud_ok, level="downloaded")
        if allowed:
            try:
                res = await cloud.delete(
                    conn, disk, [r["path"] for r in allowed],
                    level="downloaded", confirm=len(allowed),
                    permanently=True, job_id=job_id)
                counters["cloud_deleted"] = int(res.get("deleted", 0))
                counters["cloud_failed"] = int(res.get("failed", 0))
            except (OSError, ValueError) as exc:
                # Файлы уже перенесены и учтены -- неудача с облаком не
                # отменяет спасения, она лишь оставляет копию в облаке.
                log.warning("удаление облачных копий после переноса: %s", exc)
                counters["cloud_error"] = 1
    log.info("из локальной папки взято: %s", counters)
    return counters


# ── учёт самого зеркала ─────────────────────────────────────────────
#
# В папку спасения файлы попадают не только программой: часть коллекции
# человек переносит туда руками -- до программы, мимо неё, из другого
# места. Такие файлы для программы не существуют: их нет в resources, в
# local, в дереве, в итогах и в архивах, хотя на диске они лежат. Первый
# такой аудит (18 октября) нашёл 1914 файлов в 500 папках -- разговор про
# CzarStream и про «почему в описи пусто».
#
# Здесь от них отличия нет: файл уже на месте, качать нечего. Регистрируем
# -- ресурс, если облако о нём ничего не знает, и локальную запись. Хеши
# сверяем, когда облако о файле что-то знает; не знает -- «unverified»,
# это честнее, чем выдумывать.


def mirror_candidates(conn: sqlite3.Connection) -> list[dict]:
    """Что лежит в зеркале мимо программы: файлы без записи в local."""

    files_root = config.PATHS.files
    known = {r["path"] for r in conn.execute("SELECT path FROM local")}
    out: list[dict] = []
    for dirpath, _dirnames, filenames in os.walk(files_root):
        for name in filenames:
            if name.endswith(".part"):
                continue  # недокачанное -- учёт берёт только целые
            full = Path(dirpath) / name
            rel = full.relative_to(files_root)
            cloud_path = "disk:/" + "/".join(rel.parts)
            if cloud_path in known:
                continue
            try:
                size = full.stat().st_size
            except OSError:
                continue
            row = conn.execute(
                "SELECT size, md5, sha256 FROM resources WHERE path=?",
                (cloud_path,)).fetchone()
            out.append({
                "path": cloud_path, "disk": full, "size": size,
                "known": row is not None,
                "md5": row["md5"] if row else None,
                "sha256": row["sha256"] if row else None,
            })
    out.sort(key=lambda it: it["path"])
    return out


def mirror_survey(conn: sqlite3.Connection) -> dict:
    """Сколько и чего лежит в зеркале мимо программы -- без изменений."""
    items = mirror_candidates(conn)
    return {"files": len(items), "bytes": sum(it["size"] for it in items),
            "with_cloud_meta": sum(1 for it in items if it["known"]),
            "folders": len({str(it["disk"].parent) for it in items})}


def mirror_one(conn: sqlite3.Connection, item: dict, *,
               verify: bool = True) -> dict:
    """Зарегистрировать один файл зеркала: ресурс + локальная запись."""
    from .download import _hashes

    if not item["known"]:
        # Облако о файле ничего не знает -- минимальный ресурс, чтобы
        # дерево, итоги и архив его видели. raw помечаем источником.
        db.upsert_resource(conn, {
            "path": item["path"],
            "name": item["disk"].name,
            "type": "file",
            "size": item["size"],
            "source": "mirror",
        })
    # Папки-предки тоже нужны: дерево определяет is_dir по наличию
    # ресурса type='dir', а без него папка рисуется файлом и всегда
    # видна в режиме «только нескачанное».
    from .localwatch import _ensure_dirs
    _ensure_dirs(conn, item["path"])
    state = "unverified"
    md5 = sha = None
    if verify and (item["sha256"] or item["md5"]):
        md5, sha = _hashes(item["disk"])
        if ((item["sha256"] and sha.lower() == str(item["sha256"]).lower())
                or (item["md5"] and md5.lower() == str(item["md5"]).lower())):
            state = "ok"
        else:
            state = "mismatch"
            log.warning("хеш перенесённого вручную %s не сошёлся с облачным",
                        item["path"])
    conn.execute(
        """INSERT INTO local(path,local_path,bytes,sha256,md5,verify,holes,
                             downloaded_at,released)
           VALUES(?,?,?,?,?,?,NULL,?,0)
           ON CONFLICT(path) DO UPDATE SET
             local_path=excluded.local_path, bytes=excluded.bytes,
             sha256=excluded.sha256, md5=excluded.md5, verify=excluded.verify,
             holes=NULL, released=0""",
        (item["path"], str(item["disk"]), item["size"], sha, md5, state,
         db.now()))
    return {"path": item["path"], "state": state}


async def run_mirror(conn: sqlite3.Connection, *, verify: bool = True,
                     job_id: int | None = None) -> dict:
    """Учесть всё, что лежит в зеркале мимо программы."""
    items = mirror_candidates(conn)
    counters: dict[str, int] = {}
    stop = db.CancelWatch(conn, job_id)
    async with stop:
        for n, item in enumerate(items, 1):
            if stop():
                counters["cancelled"] = 1
                break
            result = await asyncio.to_thread(mirror_one, conn, item,
                                             verify=verify)
            counters[result["state"]] = counters.get(result["state"], 0) + 1
            if job_id is not None and n % 10 == 0:
                db.job_progress(conn, job_id, n, len(items),
                                f"учтено {counters.get('ok', 0)}")
    counters["bytes"] = sum(it["size"] for it in items)
    counters["files"] = len(items)
    log.info("учтено из зеркала: %s", counters)
    return counters
