"""Здоровье хранилища: почему не выходит и что происходит по дням.

Раньше на вопрос «проверь лог» приходилось грепать 50 МБ текста руками.
Здесь то же самое считается по базе: у каждой пробы есть состояние, код
ответа и текст ошибки, у каждой задачи -- итог, у каждого спасения -- дата.
Лог остаётся для подробностей, но ответ на «что не так» даёт этот отчёт.

Классификация причин нарочно грубая: человеку нужно понять, больна машина,
нет файла или облако не дало ссылку, -- а не прочитать пятнадцать
вариантов одной и той же сетевой ошибки.
"""

from __future__ import annotations

import datetime as dt
import sqlite3

from . import db, tree

# Причины отказов. Порядок важен: первое совпадение выигрывает, поэтому
# частные случаи идут раньше общих.
REASONS: list[tuple[str, tuple[str, ...]]] = [
    # Наши собственные удаления -- это не отказ хранилища.
    ("ours", ("удалено нами из облака",)),
    ("no_link", ("нет ссылки",)),
    ("not_found", ("DiskNotFoundError", "Resource not found", "HTTP 404")),
    ("silent", ("ReadTimeout", "молчит")),
    ("refused", ("ConnectTimeout",)),
    ("dns", ("ConnectError", "getaddrinfo")),
    ("broken", ("RemoteProtocolError", "peer closed")),
    ("truncated", ("обрезан", "только первые")),
    ("no_copy", ("no more reliable hosts", "no successful lookup result")),
]

# Человеческие подписи причин живут в словарях интерфейса (health.reason.*),
# здесь -- только коды: сервер не должен знать про языки.


def classify(state: str, detail: str) -> str:
    """Свести текст ошибки к одной из причин."""
    text = detail or ""
    for code, needles in REASONS:
        if any(n in text for n in needles):
            return code
    if state == "gone":
        return "not_found"
    if state == "ok":
        return "ok"
    return "misc"


def _window(days: int) -> tuple[float, list[str]]:
    """Границы окна и список дней в нём, включая сегодняшний."""
    today = dt.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start = today - dt.timedelta(days=days - 1)
    keys = [(start + dt.timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]
    return start.timestamp(), keys


def _by_day(conn: sqlite3.Connection, sql: str, since: float,
            keys: list[str]) -> dict[str, dict]:
    out = {k: {} for k in keys}
    for row in conn.execute(sql, (since,)):
        if row["d"] in out:
            item = dict(row)
            item.pop("d", None)
            out[row["d"]] = item
    return out


def report(conn: sqlite3.Connection, days: int = 7) -> dict:
    """Сводка: по дням, по причинам отказов, по узлам, по задачам."""
    since, keys = _window(days)
    now = db.now()
    day24 = now - 86400

    saved = _by_day(conn,
                    """SELECT date(downloaded_at,'unixepoch','localtime') d,
                              COUNT(*) n, COALESCE(SUM(bytes),0) b
                         FROM local WHERE downloaded_at >= ? GROUP BY d""",
                    since, keys)
    deleted = _by_day(conn,
                      """SELECT date(deleted_at,'unixepoch','localtime') d,
                                COUNT(*) n
                           FROM cloud_deleted WHERE deleted_at >= ? GROUP BY d""",
                      since, keys)
    probes = _by_day(conn,
                     """SELECT date(ts,'unixepoch','localtime') d,
                               SUM(state='ok') ok, SUM(state<>'ok') bad
                          FROM probe_history WHERE ts >= ? GROUP BY d""",
                     since, keys)

    series = []
    for k in keys:
        s = saved.get(k) or {}
        d = deleted.get(k) or {}
        p = probes.get(k) or {}
        series.append({
            "day": k,
            "saved": s.get("n") or 0,
            "saved_bytes": s.get("b") or 0,
            "deleted": d.get("n") or 0,
            "probes_ok": p.get("ok") or 0,
            "probes_bad": p.get("bad") or 0,
        })

    # Причины отказов -- по текущему состоянию, а не по истории: важно,
    # что мешает сейчас.
    reasons: dict[str, dict] = {}
    gone: dict[str, int] = {}
    for row in conn.execute(
            """SELECT state, COALESCE(detail,'') AS detail, COUNT(*) AS n,
                      COALESCE(SUM(r.size),0) AS b
                 FROM probe p JOIN resources r ON r.path = p.path
                WHERE p.state <> 'ok'
                GROUP BY p.state, p.detail"""):
        code = classify(row["state"], row["detail"])
        bucket = gone if row["state"] == "gone" else reasons
        item = bucket.setdefault(code, {"code": code, "n": 0, "bytes": 0})
        item["n"] += row["n"]
        item["bytes"] += row["b"]

    def ranked(items: dict[str, dict]) -> list[dict]:
        total = sum(v["n"] for v in items.values()) or 1
        out = sorted(items.values(), key=lambda x: -x["n"])
        for v in out:
            v["share"] = round(v["n"] / total, 3)
        return out

    # Узлы: где больше всего отказов.
    hosts = []
    for row in conn.execute(
            """SELECT COALESCE(storage_host, last_host) AS host,
                      SUM(state='ok') AS ok, SUM(state<>'ok') AS bad,
                      COUNT(*) AS n
                 FROM probe
                WHERE COALESCE(storage_host, last_host) IS NOT NULL
                GROUP BY host ORDER BY bad DESC, n DESC LIMIT 12"""):
        known = (row["ok"] or 0) + (row["bad"] or 0)
        hosts.append({
            "host": row["host"],
            "cluster": tree._cluster_of(row["host"]),
            "ok": row["ok"] or 0,
            "bad": row["bad"] or 0,
            "files": row["n"],
            "share": round((row["ok"] or 0) / known, 3) if known else 0.0,
        })

    # Задачи за окно: сколько и что именно упало.
    jobs = conn.execute(
        """SELECT id, kind, state, total, done, started_at, message
             FROM jobs WHERE started_at >= ? ORDER BY id DESC""", (since,)).fetchall()
    failed = [dict(j) for j in jobs if j["state"] in ("failed", "interrupted")]
    cancelled = sum(1 for j in jobs if j["state"] == "cancelled")
    done = sum(1 for j in jobs if j["state"] == "done")

    kpi = conn.execute(
        """SELECT
             (SELECT COUNT(*) FROM local WHERE downloaded_at >= ?) AS saved_n,
             (SELECT COALESCE(SUM(bytes),0) FROM local
               WHERE downloaded_at >= ?) AS saved_b,
             (SELECT COUNT(*) FROM cloud_deleted WHERE deleted_at >= ?) AS deleted_n,
             (SELECT COUNT(*) FROM probe_history WHERE ts >= ?) AS probes_n,
             (SELECT COUNT(*) FROM probe_history
               WHERE ts >= ? AND state <> 'ok') AS probes_bad""",
        (day24, day24, day24, day24, day24)).fetchone()

    return {
        "now": now,
        "days": series,
        "kpi": {
            "saved": kpi["saved_n"],
            "saved_bytes": kpi["saved_b"],
            "deleted": kpi["deleted_n"],
            "probes": kpi["probes_n"],
            "probes_bad": kpi["probes_bad"],
        },
        "reasons": ranked(reasons),
        "gone": ranked(gone),
        "hosts": hosts,
        "jobs": {
            "total": len(jobs),
            "done": done,
            "cancelled": cancelled,
            "failed": failed[:6],
            "failed_total": len(failed),
        },
    }
