"""Запросы для дерева в интерфейсе.

Папку нужно показывать вместе с итогом по всему, что под ней: сколько
файлов, сколько весят, сколько из них доступно и сколько уже спасено.
Иначе выбирать массово невозможно -- не видно, на что подписываешься.

Итоги считаются диапазоном по path, а не LIKE: path -- первичный ключ, и
условие `path >= 'disk:/X/' AND path < 'disk:/X0'` идёт по индексу (символ
'0' -- следующий за '/' в кодировке, поэтому диапазон ровно совпадает с
поддеревом). На ста тысячах записей это разница между мгновением и
секундами на каждом раскрытии папки.
"""

from __future__ import annotations

import re
import sqlite3
import time

from . import config

# Раскрытие папки считает полтора десятка агрегатов по всем строкам
# поддерева: на 26 тыс. файлов это 450 мс (замер 18 октября). Кэш на
# несколько секунд: раскрыл, закрыл, раскрыл снова -- второй раз мгновенно.
# Ключ включает id(conn): у тестов и у сервера разные соединения, и
# подмешивать чужой кэш нельзя.
_CHILDREN_TTL = 4.0
_CHILDREN_CACHE: dict[tuple[int, str], tuple[float, list[dict]]] = {}

# archive_members может хранить путь не один раз (файл попал в архив, архив
# пересобрали). Без DISTINCT такой путь удвоил бы все суммы в строке.
JOINS = """
  LEFT JOIN probe p          ON p.path = {key}
  LEFT JOIN local l          ON l.path = {key}
  LEFT JOIN cloud_deleted cd ON cd.path = {key}
  LEFT JOIN (SELECT DISTINCT path FROM archive_members) am ON am.path = {key}
"""


def _agg(size: str, type_: str, *, full: bool = True,
         vanished: str = "r.vanished_at", extra: bool = False) -> str:
    """Агрегаты по поддереву.

    full=True -- полный набор для сводки (там нужны байты доступного и
    спасённого). full=False -- только то, что показывает строка дерева:
    у папки видны число файлов, размер, «спасено», «в архиве» и «удалено»,
    а ok_bytes/saved_bytes/gone/salvaged/released не нужны. Меньше
    выражений -- быстрее раскрытие (замер: 460 мс на 26 тыс. строк).
    """
    f = f"{type_}='file'"
    # Срок годности пробы. Доступность в облаке плавает, поэтому старое
    # наблюдение -- не знание: оно показывается отдельной строкой и просится
    # на перепроверку, а не выдаётся за текущее состояние.
    #
    # Отсечку считаем ОДИН раз, а не strftime на каждую строку: на 26 тыс.
    # строк это отдельные 15 мс, и они повторялись в каждом агрегате.
    cutoff = int(time.time() - config.PROBE_TTL_HOURS * 3600)
    fresh = f"p.checked_at >= {cutoff}"
    _v = vanished
    common = f"""
      COALESCE(SUM({f}),0)                                   AS files,
      COALESCE(SUM({f} AND p.state IS NOT NULL AND NOT ({fresh})),0) AS stale,
      COALESCE(SUM(CASE WHEN {f} THEN COALESCE({size},0) ELSE 0 END),0) AS bytes,
      COALESCE(SUM({f} AND p.state='ok' AND cd.path IS NULL
                    AND {_v} IS NULL),0)                           AS ok,
      COALESCE(SUM({f} AND p.state='unavailable' AND cd.path IS NULL
                    AND {_v} IS NULL),0)                           AS unavailable,
      -- gone нужен и строке дерева: по нему красится точка папки.
      COALESCE(SUM({f} AND p.state='gone' AND cd.path IS NULL
                    AND {_v} IS NULL),0)                           AS gone,
      COALESCE(SUM({f} AND p.state IS NULL AND cd.path IS NULL
                    AND {_v} IS NULL),0)                           AS unchecked,
      -- Размер того, что облако ещё держит (ok + недоступное + непроверенное).
      -- Нужен линзе «Сейчас»: строка папки раньше показывала исторический
      -- размер, и папка, от которой в облаке ничего не осталось, выглядела
      -- полной. 1_семестр: 576 МБ в строке, 0 в облаке.
      COALESCE(SUM(CASE WHEN {f} AND cd.path IS NULL AND {_v} IS NULL
                         AND (p.state IS NULL OR p.state IN
                              ('ok','unavailable','api_error','unknown'))
                        THEN COALESCE({size},0) ELSE 0 END),0) AS live_bytes,
      -- Файла в облаке больше нет: опись его помнит (имя, размер, хеши --
      -- по ним и ищут копию на стороне), но живым он не считается.
      COALESCE(SUM({f} AND {_v} IS NOT NULL),0)     AS vanished,
      COALESCE(SUM({f} AND l.verify='ok' AND l.released=0
                    AND l.missing=0),0)                     AS saved,
      -- Копия есть, но сверять не с чем: файл перенесли вручную, или в
      -- описи нет хеша (у части старых записей его нет вовсе). Это не
      -- «не спасено», поэтому отдельным числом, а не молчанием.
      COALESCE(SUM({f} AND l.verify='unverified' AND l.released=0
                    AND l.missing=0),0)                     AS unverified,
      -- «Есть на диске»: любая годная локальная копия, включая
      -- непроверенную (файл перенесли вручную, облако о нём молчит --
      -- перекачивать нечего и неоткуда). По этому счётчику работает
      -- режим дерева «только нескачанное»; 'mismatch' сюда не входит:
      -- испорченная копия скачанной не считается, как и запись, чей
      -- файл исчез с диска (missing ставит сверка зеркала).
      COALESCE(SUM({f} AND l.path IS NOT NULL AND l.released=0
                    AND l.verify<>'mismatch' AND l.missing=0),0) AS present,
      -- Объём «того, что лежит на диске» -- ТЕМ ЖЕ правилом, что и штуки:
      -- иначе папка с перенесёнными вручную файлами показывала «2 092 шт ·
      -- 0 Б» (штуки включали unverified, а байты считались только по ok).
      COALESCE(SUM(CASE WHEN {f} AND l.path IS NOT NULL AND l.released=0
                         AND l.verify<>'mismatch' AND l.missing=0
                        THEN COALESCE({size},0) ELSE 0 END),0) AS present_bytes,
      COALESCE(SUM({f} AND am.path IS NOT NULL),0)           AS archived,
      -- Сколько ждёт архива и сколько можно удалить из облака прямо
      -- сейчас: это числа на двух главных кнопках.
      COALESCE(SUM({f} AND l.verify IN ('ok','unverified') AND l.released=0
                    AND l.missing=0 AND am.path IS NULL),0) AS arch_ready,
      COALESCE(SUM({f} AND l.verify IN ('ok','unverified') AND l.released=0
                    AND l.missing=0 AND cd.path IS NULL
                    AND {_v} IS NULL),0)                   AS del_ready,
      COALESCE(SUM({f} AND cd.path IS NOT NULL),0)           AS cloud_deleted,
      COALESCE(SUM({f} AND l.missing=1),0)                   AS missing_local,
      -- «Так и не взяли»: копии нет, и в облаке его уже нет (удалено нами
      -- или тобой в вебе). Считается отдельно, потому что saved и
      -- cloud_deleted пересекаются: вычитание давало ноль при 1 629
      -- реально не взятых файлах.
      COALESCE(SUM({f} AND l.path IS NULL
                    AND (cd.path IS NOT NULL OR {_v} IS NOT NULL)),0) AS never_taken
    """
    if not full:
        if not extra:
            return common
        # Строке дерева для линз нужны три числа: сколько ещё в облаке
        # (live_bytes), сколько лежит целым (saved_bytes) и сколько
        # пропало с диска (missing_local). Держим их отдельно от полного
        # набора: он вдвое дороже, а нужен только сводке.
        # live_bytes и missing_local уже посчитаны в common: здесь только
        # то, чего там нет. Две формулы одного числа -- это две правды, и
        # читается всегда первая.
        return common + f""",
      COALESCE(SUM(CASE WHEN {f} AND l.verify='ok' AND l.released=0
                        AND l.missing=0
                        THEN COALESCE({size},0) ELSE 0 END),0) AS saved_bytes
    """
    return common + f""",
      MAX(COALESCE(p.checked_at,0))                          AS checked_at,
      COALESCE(SUM({f} AND p.state='ok' AND {fresh}),0)      AS ok_fresh,
      -- «Готово к выгрузке»: облако отдаёт, локальной копии нет, из
      -- облака мы его не удаляли. Именно это число показывает карточка
      -- «Что дальше»: оно отвечает на вопрос «сколько можно взять прямо
      -- сейчас». Доступность гниёт за часы, так что это главное число.
      COALESCE(SUM({f} AND p.state='ok' AND l.path IS NULL
                    AND cd.path IS NULL),0)                 AS dl_ready,
      COALESCE(SUM(CASE WHEN {f} AND p.state='ok'
                        THEN COALESCE({size},0) ELSE 0 END),0) AS ok_bytes,
      COALESCE(SUM({f} AND l.verify='salvaged' AND l.released=0
                    AND l.missing=0),0)                    AS salvaged,
      COALESCE(SUM(CASE WHEN {f} AND l.verify='salvaged' AND l.released=0
                        THEN COALESCE({size},0) ELSE 0 END),0) AS salvaged_bytes,
      -- Файл когда-то спасли с дырками, а потом докачали целиком. Счётчик
      -- отдельный: «с дырками» должно убывать, а этот -- расти, иначе
      -- человек не видит, что докачка вообще работает.
      COALESCE(SUM({f} AND l.verify IN ('ok','unverified') AND l.salvaged_at>0
                    AND l.released=0 AND l.missing=0),0)   AS fixed,
      COALESCE(SUM({f} AND l.released=1),0)                  AS released,
      COALESCE(SUM(CASE WHEN {f} AND l.verify='ok' AND l.released=0
                        AND l.missing=0
                        THEN COALESCE({size},0) ELSE 0 END),0) AS saved_bytes
    """


def _range(folder: str) -> tuple[str, str, int]:
    pre = folder if folder.endswith("/") else folder + "/"
    return pre, pre[:-1] + "0", len(pre) + 1


def children(conn: sqlite3.Connection, folder: str = "disk:/", *,
             use_cache: bool = False) -> list[dict]:
    """Прямые дети папки: папки с итогом по поддереву, файлы по отдельности.

    Кэш включается только на стороне HTTP (use_cache=True): тесты и
    внутренние вызовы читают то, что лежит в базе сейчас.
    """
    if not use_cache:
        return _children_uncached(conn, folder)
    key = (id(conn), folder)
    hit = _CHILDREN_CACHE.get(key)
    if hit is not None and time.monotonic() - hit[0] < _CHILDREN_TTL:
        return hit[1]
    value = _children_uncached(conn, folder)
    if len(_CHILDREN_CACHE) > 200:
        _CHILDREN_CACHE.clear()
    _CHILDREN_CACHE[key] = (time.monotonic(), value)
    return value


def _children_uncached(conn: sqlite3.Connection, folder: str) -> list[dict]:
    pre, post, plen = _range(folder)
    base = pre[:-1] if pre != "disk:/" else "disk:"
    seg = (f"CASE WHEN instr(substr(r.path,{plen}),'/')=0 "
           f"THEN substr(r.path,{plen}) "
           f"ELSE substr(r.path,{plen},instr(substr(r.path,{plen}),'/')-1) END")

    rows = conn.execute(
        f"""
        WITH sub AS (
          SELECT r.path AS path, r.size AS size, r.type AS type,
                 r.vanished_at AS vanished_at, {seg} AS seg
          FROM resources r WHERE r.path >= ? AND r.path < ?
        )
        SELECT s.seg AS name,
               ? || '/' || s.seg AS path,
               MAX(CASE WHEN s.path = ? || '/' || s.seg AND s.type='dir'
                        THEN 1 ELSE 0 END) AS is_dir,
               {_agg('s.size', 's.type', full=False, vanished='s.vanished_at', extra=True)}
        FROM sub s {JOINS.format(key='s.path')}
        WHERE s.seg <> ''
        GROUP BY s.seg
        ORDER BY is_dir DESC, s.seg COLLATE NOCASE
        """, (pre, post, base, base)).fetchall()

    out = []
    for row in rows:
        rec = dict(row)
        rec["is_dir"] = bool(rec["is_dir"])
        out.append(rec)

    # Детали файлов -- ОДНИМ запросом на папку, а не по запросу на файл.
    # Для папки в 615 файлов это 615 запросов (35 мс) и линейный рост: на
    # пяти тысячах файлов раскрытие уже заметно тормозило.
    files = [rec["path"] for rec in out if not rec["is_dir"]]
    if files:
        qs = ",".join("?" * len(files))
        detail = conn.execute(
            f"""SELECT r.path AS _path, r.size AS bytes,
                       COALESCE(p.state,'unchecked') AS state,
                       r.mime, r.modified, l.verify, l.released, l.holes,
                       COALESCE(l.missing,0) AS local_missing,
                       m.preview_state,
                       am.path IS NOT NULL AS archived,
                       cd.path IS NOT NULL AS cloud_deleted
                FROM resources r {JOINS.format(key='r.path')}
                LEFT JOIN meta_saved m ON m.path=r.path
                WHERE r.path IN ({qs})""", files).fetchall()
        by_path = {}
        for r in detail:
            item = dict(r)
            item.pop("_path", None)
            by_path[r["_path"]] = item
        for rec in out:
            if not rec["is_dir"] and rec["path"] in by_path:
                rec |= by_path[rec["path"]]

    return out


def subtree_files(conn: sqlite3.Connection, folder: str, *,
                  states: list[str] | None = None,
                  only_saved: bool = False,
                  exclude_saved: bool = False) -> list[str]:
    """Все файлы под папкой -- для выбора "взять всё целиком"."""
    pre, post, _ = _range(folder)
    where = ["r.type='file'", "r.path >= ?", "r.path < ?"]
    args: list[object] = [pre, post]
    if states:
        if "unchecked" in states:
            rest = [s for s in states if s != "unchecked"]
            if rest:
                where.append(
                    f"(p.state IS NULL OR p.state IN ({','.join('?' * len(rest))}))")
                args += rest
            else:
                where.append("p.state IS NULL")
        else:
            where.append(f"p.state IN ({','.join('?' * len(states))})")
            args += states
    if only_saved:
        where.append("l.verify='ok' AND l.released=0")
    if exclude_saved:
        # 'unverified' -- тоже «есть на диске»: файл перенесён вручную,
        # облако о нём молчит, качать его неоткуда.
        where.append("(l.path IS NULL OR l.verify NOT IN ('ok','unverified') "
                     "OR l.released=1)")
    return [r["path"] for r in conn.execute(
        f"""SELECT r.path FROM resources r
            LEFT JOIN probe p ON p.path=r.path
            LEFT JOIN local l ON l.path=r.path
            WHERE {' AND '.join(where)} ORDER BY r.size ASC""", args)]


def remaining(conn: sqlite3.Connection) -> dict:
    """Сколько ещё не взято -- по последнему известному состоянию облака.

    Опись -- слепок, облако живёт дальше: часть файлов исчезла, часть
    ожила. Поэтому «осталось скачать» мало показать одним числом -- надо
    разложить по тому, что облако говорило в последний раз, и сказать,
    когда это было. Иначе «791 ГБ осталось» читается как «столько ещё
    можно взять», хотя половина уже не отдаётся.
    """
    rows = conn.execute(
        """SELECT COALESCE(p.state,'unchecked') AS st,
                  COUNT(*) AS n, COALESCE(SUM(r.size),0) AS b,
                  MIN(p.checked_at) AS oldest, MAX(p.checked_at) AS newest
             FROM resources r
             LEFT JOIN probe p ON p.path = r.path
             LEFT JOIN local l ON l.path = r.path
             LEFT JOIN cloud_deleted cd ON cd.path = r.path
            WHERE r.type='file' AND r.vanished_at IS NULL AND cd.path IS NULL
              AND (l.path IS NULL OR l.missing=1)
            GROUP BY st""").fetchall()
    by: dict[str, dict] = {}
    total_n = total_b = 0
    oldest = None
    for r in rows:
        by[r["st"]] = {"files": r["n"], "bytes": r["b"],
                       "oldest": r["oldest"], "newest": r["newest"]}
        total_n += r["n"]
        total_b += r["b"]
        if r["oldest"] and (oldest is None or r["oldest"] < oldest):
            oldest = r["oldest"]
    # «Облако отдаёт сейчас» -- это только свежие ok. Устаревшая проба
    # доступности не обещает: она про вчера.
    cutoff = int(time.time() - config.PROBE_TTL_HOURS * 3600)
    fresh_ok = conn.execute(
        """SELECT COUNT(*) AS n, COALESCE(SUM(r.size),0) AS b
             FROM resources r
             JOIN probe p ON p.path = r.path
             LEFT JOIN local l ON l.path = r.path
             LEFT JOIN cloud_deleted cd ON cd.path = r.path
            WHERE r.type='file' AND p.state='ok' AND p.checked_at >= ?
              AND r.vanished_at IS NULL AND cd.path IS NULL
              AND (l.path IS NULL OR l.missing=1)""", (cutoff,)).fetchone()
    return {"files": total_n, "bytes": total_b,
            "available_files": fresh_ok["n"], "available_bytes": fresh_ok["b"],
            "checked_at": oldest, "by_state": by}


# Узел хранилища выглядит как s535klg.storage.yandex.net: номер машины
# плюс кластер (klg, vla, sas...). Кластер -- это ЦОД; когда он ложится,
# ложится весь, и это видно по отказам одного вида: klg принимает
# соединение и замолкает (ReadTimeout), vla не принимает вовсе
# (ConnectTimeout).
_CLUSTER = re.compile(r"^s\d+([a-z]+)\.storage\.yandex\.net$")


def _cluster_of(host: str) -> str:
    # downloader.disk.yandex.ru -- не узел хранилища, а сам API: сюда
    # попадают файлы, у которых ссылку так и не выдали.
    if host.endswith("downloader.disk.yandex.ru"):
        return "api"
    m = _CLUSTER.match(host)
    return m.group(1) if m else "другие"


def hosts_report(conn: sqlite3.Connection) -> dict:
    """Узлы и кластеры: где лежит несспасённое и что они отвечали.

    Считаем по ВСЕМ файлам с известным узлом, а не только по остатку:
    иначе кластер, где всё уже решено, исчезает из списка, и кажется,
    что его не было. «Файлов» -- сколько ещё взять, «видели» -- сколько
    вообще лежало на нём.

    Узел берём из last_host: storage_host затирается каждым наблюдением,
    а 404 хоста не сообщает -- и узел терялся.
    """
    rows = conn.execute(
        """SELECT COALESCE(p.storage_host, p.last_host) AS host,
                  COALESCE(p.state,'unchecked') AS st,
                  CASE WHEN r.vanished_at IS NULL AND cd.path IS NULL
                            AND (l.path IS NULL OR l.missing=1)
                       THEN 1 ELSE 0 END AS left,
                  r.size AS size
             FROM resources r
             JOIN probe p ON p.path = r.path
             LEFT JOIN local l ON l.path = r.path
             LEFT JOIN cloud_deleted cd ON cd.path = r.path
            WHERE r.type='file'
              AND COALESCE(p.storage_host, p.last_host) IS NOT NULL""").fetchall()

    def blank(name: str) -> dict:
        return {"name": name, "files": 0, "bytes": 0, "seen": 0,
                "ok": 0, "unavailable": 0, "gone": 0, "unchecked": 0}

    hosts: dict[str, dict] = {}
    clusters: dict[str, dict] = {}
    for r in rows:
        for bucket, name in ((hosts, r["host"]),
                             (clusters, _cluster_of(r["host"]))):
            item = bucket.setdefault(name, blank(name))
            item["seen"] += 1
            if not r["left"]:
                continue
            item["files"] += 1
            item["bytes"] += r["size"] or 0
            key = r["st"] if r["st"] in ("ok", "unavailable", "gone") else "unchecked"
            item[key] += 1

    def finish(items: dict[str, dict]) -> list[dict]:
        out = []
        for item in items.values():
            known = item["ok"] + item["unavailable"] + item["gone"]
            # Доля живых считается по тем, о ком что-то известно: иначе
            # непроверенные тянули бы её вниз, ничего не говоря.
            item["share"] = round(item["ok"] / known, 3) if known else 0.0
            out.append(item)
        return sorted(out, key=lambda x: (-x["files"], -x["seen"]))

    return {"hosts": finish(hosts), "clusters": finish(clusters)}


def totals(conn: sqlite3.Connection) -> dict:
    # WHERE type='file' -- не мелочь: в описи 44 тыс. строк, из них 17 тыс.
    # папок, и каждая строка прогоняется через три десятка SUM. Папки в
    # итогах не нужны ни в одном счётчике (все они про файлы), а скан
    # становится на 40% короче.
    row = conn.execute(
        f"""SELECT {_agg('r.size', 'r.type')} FROM resources r
            {JOINS.format(key='r.path')}
            WHERE r.type='file'""").fetchone()
    out = dict(row) if row else {}
    for key, sql in (
        ("dirs", "SELECT COUNT(*) AS v FROM resources WHERE type='dir'"),
        ("previews", "SELECT COALESCE(SUM(preview_state='ok'),0) AS v FROM meta_saved"),
        ("archives", "SELECT COUNT(*) AS v FROM archives WHERE state='verified'"),
        ("archive_bytes",
         "SELECT COALESCE(SUM(bytes),0) AS v FROM archive_volumes"),
        # Файлы, что были недоступны, а при следующей пробе отдались. Это
        # «Ожило» -- файл был недоступен и ПОЗЖЕ стал доступен. Раньше
        # считалось по факту «был ok и был не-ok» в любом порядке, а в
        # историю попадает и наш собственный gone при удалении из облака:
        # на 18 октября из 5677 «оживших» 4881 были нашими же удалениями.
        # Теперь: ok строго после не-ok, и удалённые нами не в счёт.
        ("revived",
         """SELECT COUNT(*) AS v FROM (
              SELECT h.path FROM probe_history h
              WHERE h.state='ok'
                AND h.path NOT IN (SELECT path FROM cloud_deleted)
                AND EXISTS (SELECT 1 FROM probe_history x
                            WHERE x.path=h.path AND x.state<>'ok'
                              AND x.ts < h.ts)
              GROUP BY h.path)"""),
        # Удаления из облака: наши и «уже не было» (клиент Диска успел
        # раньше). Складывать их в одно число -- значит приписывать себе
        # чужую работу: 18 октября из 5526 таких записей 943 были не наши.
        ("cloud_deleted", "SELECT COUNT(*) AS v FROM cloud_deleted"),
        ("cloud_deleted_by_us",
         ("SELECT COUNT(*) AS v FROM cloud_deleted "
          "WHERE response NOT LIKE 'уже отсутствовало%'")),
    ):
        got = conn.execute(sql).fetchone()
        out[key] = got["v"] if got else 0
    return out
