"""Автопилот: перепроверяет недоступное и забирает ожившее.

Идея взята у yandex-disk-rescue: неподелившееся лечится не одним
заходом, а повтором по расписанию. У нас это даже важнее -- по замерам
18 октября набор доступных менялся быстро (за пару часов выпадала пятая
часть, а 71 файл умирал между пробой и скачиванием). Значит «доступно» --
это разведка, а не обещание, и обещание надо перепроверять.

Круг автопилота:
  1. берёт файлы, которых нет на диске и чью доступность стоит
     перепроверить: недоступные, устаревшие и непроверенные;
  2. упорядочивает их по живучести узла хранения -- с узлов, где файлы
     отдаются чаще, шанс выше;
  3. проба этих файлов;
  4. всё, что ожило, сразу качает.

salvage в автопилоте не включается: файл с дырками -- это осознанный
выбор человека, а не чёрная работа ночью.

Круг идёт задачей (её видно в панели, по ней работает «стоп») и не
начинается, пока идёт любая другая работа: гонка двух выгрузок испортит
.part, а гонка с пробой -- просто сожжёт квоту.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from . import config, db, download
from . import probe as probe_mod

log = logging.getLogger("drydock.autopilot")


def host_scores(conn: sqlite3.Connection) -> dict[str, float]:
    """Доля живых файлов на каждом узле хранения.

    Фильтровать по узлу нельзя -- узлы смешанные (на верхних узлах нашего
    аккаунта 60-70% ok), но порядок обхода имеет смысл: с живого узла
    шанс выше, чем с мёртвого.
    """
    rows = conn.execute(
        """SELECT storage_host,
                  SUM(state='ok') AS ok, COUNT(*) AS n
             FROM probe
            WHERE storage_host IS NOT NULL
            GROUP BY storage_host""").fetchall()
    return {r["storage_host"]: (r["ok"] or 0) / r["n"]
            for r in rows if r["n"]}


def host_liveness(conn: sqlite3.Connection) -> dict:
    """Сколько узлов живых и сколько чисто-мёртвых -- для чипа."""
    scores = host_scores(conn)
    alive = sum(1 for s in scores.values() if s > 0)
    dead = sum(1 for s in scores.values() if s == 0)
    best = max(scores.items(), key=lambda kv: kv[1]) if scores else None
    return {"alive": alive, "dead": dead,
            "best_host": best[0] if best else None,
            "best_share": round(best[1], 3) if best else 0.0,
            "hosts": len(scores)}


def recheck_candidates(conn: sqlite3.Connection,
                       limit: int | None = None) -> list[str]:
    """Что перепроверить: недоступное, устаревшее и непроверенное.

    Только то, чего нет на диске: перепроверять спасённое незачем.
    Упорядочено по живучести узла -- с живого узла выше шанс, что файл
    ожил. Внутри узла -- по пути, чтобы порядок был устойчивым.
    """
    limit = limit or config.AUTOPILOT_BATCH
    scores = host_scores(conn)
    rows = conn.execute(
        """SELECT r.path, p.storage_host
             FROM resources r
             LEFT JOIN probe p  ON p.path = r.path
             LEFT JOIN local l   ON l.path = r.path
             LEFT JOIN cloud_deleted cd ON cd.path = r.path
            WHERE r.type='file' AND l.path IS NULL AND cd.path IS NULL
              AND (p.state IS NULL
                   OR p.state IN ('unavailable','api_error','unknown')
                   OR p.checked_at IS NULL
                   OR p.checked_at < ?)
            ORDER BY r.path""",
        (db.now() - int(config.PROBE_TTL_HOURS * 3600),)).fetchall()
    rows = sorted(rows, key=lambda r: -scores.get(r["storage_host"] or "", 0.0))
    return [r["path"] for r in rows][:limit]


def _revived_now(conn: sqlite3.Connection, paths: list[str]) -> list[str]:
    """Что ожило после пробы и не лежит на диске."""
    qs = ",".join("?" * len(paths))
    return [r["path"] for r in conn.execute(
        f"""SELECT r.path FROM resources r
              JOIN probe p ON p.path = r.path
              LEFT JOIN local l ON l.path = r.path
              LEFT JOIN cloud_deleted cd ON cd.path = r.path
             WHERE r.path IN ({qs}) AND p.state='ok'
               AND l.path IS NULL AND cd.path IS NULL""", paths)]


async def round_once(conn: sqlite3.Connection, disk: Any, *,
                     job_id: int | None = None) -> dict:
    """Один круг: перепроверить и забрать ожившее."""
    paths = recheck_candidates(conn)
    if not paths:
        return {"probed": 0, "revived": 0, "ok": 0, "failed": 0,
                "skipped": 0, "note": "перепроверять нечего"}
    stop = db.CancelWatch(conn, job_id)
    if job_id is not None:
        db.job_progress(conn, job_id, 0, len(paths),
                        f"перепроверяю {len(paths)} файлов")

    async with stop:
        probed = await probe_mod.run(conn, disk, paths)
        out: dict[str, Any] = {
            "probed": sum(v for v in probed.values() if isinstance(v, int)),
            "revived": 0, "ok": 0, "failed": 0, "skipped": 0}
        if stop():
            out["cancelled"] = 1
            return out

        revived = _revived_now(conn, paths)
        out["revived"] = len(revived)
        if not revived:
            return out

        db.job_progress(conn, job_id, len(paths), len(paths),
                        f"ожило {len(revived)} -- забираю")
        try:
            took = await download.run(conn, disk, revived, salvage=False,
                                      job_id=job_id)
        except Exception as exc:  # noqa: BLE001 - круг не должен умирать молча
            log.warning("автопилот: выгрузка ожившего: %s: %s",
                        type(exc).__name__, exc)
            out["error"] = f"{type(exc).__name__}: {exc}"
            return out
        out.update({k: v for k, v in took.items() if k != "bytes"})
    return out
