"""Удаление пустых папок из облака.

После выгрузки в облаке остаётся скелет из папок: каталоги, из которых
файлы уехали, и целые деревья папок, где не осталось ни одного файла.
В дереве интерфейса это шум, а в описи -- тысячи лишних запросов.

Отличается от cloud.delete принципиально: там удаляют ФАЙЛЫ ради квоты и
обязательно требуют проверенную локальную копию. Здесь удаляют ПАПКИ,
в которых по определению нет ни одного файла, поэтому проверять копии
нечего, а освобождать место незачем. Отсюда и умолчание: в Корзину, а не
минуя её -- структура каталога может понадобиться, а квоту пустые папки
не занимают.

Две ступени защиты от устаревшей описи:

* Список кандидатов берётся из базы (быстро, без сети, ровно то, что
  человек видит в дереве). Это только НАМЕК, не приговор: опись могла
  закончиться вчера, а за ночь в папку положили файл.
* Перед удалением каждое пустое дерево перечисляется заново живым
  запросом к Диску, рекурсивно вниз. Нашёлся хоть один файл -- дерево
  не трогаем вообще. Только после этого уходит один DELETE на корень.

Удаляем корень дерева, а не каждую папку по отдельности: «диск:/A»,
«диск:/A/B», «диск:/A/B/C» -- это один запрос вместо трёх, и не бывает
состояния, когда половина дерева уже убрана, а половина висит.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from collections.abc import Callable

from . import cloud, db
from .yandex import Disk

log = logging.getLogger("drydock.emptydirs")

ROOT = "disk:/"
# Живая проверка -- это сеть. Ограничение, чтобы сбойный сервер (который
# на каждый запрос отдаёт всё новые папки) не превратил очистку в вечный
# обход. Честно пропускаем такое дерево и говорим об этом в итоге.
MAX_INSPECT_FOLDERS = 5000
# Полный обход ВСЕГО облака -- уже не одно дерево, а вся коллекция. На
# реальной базе это ~17 тыс. папок, то есть ~17 тыс. запросов к Диску.
# Верхняя граница страхует от сбойного сервера, который множит папки.
MAX_LIVE_FOLDERS = 100_000
MAX_DEPTH = 64
# Сколько папок перечисляем одновременно. Восемь -- та же величина, что
# и у описи: больше только увеличит очередь на стороне Диска.
INSPECT_CONCURRENCY = 8


def _parent(path: str) -> str | None:
    """Родитель облачного пути. Совпадает с db.upsert_resource."""
    parent = path.rsplit("/", 1)[0] if "/" in path else None
    return "disk:/" if parent == "disk:" else parent


def _ancestors(path: str):
    """Все папки над файлом, включая корень disk:/."""
    parent = _parent(path)
    while parent:
        yield parent
        if parent == ROOT:
            break
        parent = _parent(parent)


def _span(path: str) -> tuple[str, str]:
    """Диапазон поддерева по индексу path (см. tree.py)."""
    pre = path if path.endswith("/") else path + "/"
    return pre, pre[:-1] + "0"


def candidates(conn: sqlite3.Connection, root: str = ROOT) -> list[str]:
    """Папки-КАНДИДАТЫ: по описи под ними нет ни одного файла в облаке.

    Это не список «что будет удалено», а список «что стоит перепроверить».
    Окончательное решение принимает inspect_tree живым перечислением.

    Проба доступности здесь НЕ участвует намеренно. Её вердикт `gone`
    означает лишь «хранилище не отдало первый байт в этот заход»:
    доступность плавает, файлы возвращаются, и объявлять папку пустой
    по такой пробе нельзя. Учитываем только достоверное:
      * `vanished_at` -- полный обход облака не нашёл файл (reconcile);
      * `cloud_deleted` -- файл удалили мы сами.
    Даже они не приговор: inspect_tree всё равно смотрит в облако.
    """
    # vanished_at обязателен и для САМИХ папок: после уборки запись
    # остаётся в описи ради истории, но предлагать её к удалению снова
    # нельзя -- иначе счётчик на кнопке не уменьшится, а задача будет
    # раз за разом слать DELETE по несуществующей папке.
    dirs = {r["path"] for r in conn.execute(
        "SELECT path FROM resources WHERE type='dir' "
        "AND vanished_at IS NULL").fetchall()}
    rows = conn.execute(
        """SELECT r.path FROM resources r
           LEFT JOIN cloud_deleted cd ON cd.path = r.path
           WHERE r.type='file' AND r.vanished_at IS NULL
             AND cd.path IS NULL""").fetchall()
    nonempty: set[str] = set()
    for r in rows:
        nonempty.update(_ancestors(r["path"]))

    pre = root if root.endswith("/") else root + "/"
    out = [p for p in dirs - nonempty
           if p != ROOT and p != root and p.startswith(pre)]
    return sorted(out)


def tree_roots(paths: list[str]) -> list[str]:
    """Верхние папки пустых деревьев: их родитель сам не пуст.

    Удалять достаточно только их -- всё ниже уйдёт вместе с корнем.
    """
    all_paths = set(paths)
    return sorted(p for p in paths if _parent(p) not in all_paths)


def preview(conn: sqlite3.Connection, root: str = ROOT,
            sample: int = 20) -> dict:
    """Сколько деревьев предстоит ПЕРЕПРОВЕРИТЬ. Только по базе.

    Не «столько будет удалено»: часть деревьев окажется непустой при
    живом перечислении, и задача честно покажет их в счётчике `kept`.
    """
    cands = candidates(conn, root)
    roots = tree_roots(cands)
    return {
        "trees": len(roots),
        "folders": len(cands),
        "sample": roots[:max(0, sample)],
        "confirm": len(roots),
    }


async def _listdir(disk: Disk, path: str) -> tuple[list[dict], bool]:
    """Всё содержимое папки + можно ли ему верить.

    Решение об удалении принимается ИСКЛЮЧИТЕЛЬНО по этому ответу, поэтому
    «сервер сказал total=3, а items пустой» -- не пустая папка, а
    недостоверный ответ. Удалять по нему нельзя ни в коем случае.
    """
    out: list[dict] = []
    offset = 0
    while True:
        data = await disk.listdir(path, offset=offset)
        emb = data.get("_embedded") or {}
        page = emb.get("items") or []
        raw_total = emb.get("total")
        total = int(raw_total) if raw_total is not None else None
        out.extend(page)
        offset += len(page)
        if not page:
            # total > 0, а элементов не отдали -- ответ недостоверен.
            if total and len(out) < total:
                return out, False
            return out, True
        if total is not None and offset >= total:
            # Сервер мог недодать хвост: сверяем собранное с обещанным.
            return out, len(out) >= total
        if len(out) > 10000:
            return out, False


async def inspect_tree(disk: Disk, root: str, *,
                       max_folders: int = MAX_INSPECT_FOLDERS
                       ) -> tuple[str, int, str]:
    """Живо перечислить поддерево и решить, можно ли его удалить.

    Возвращает (вердикт, сколько папок посмотрели, причина).
    Вердикт: "empty" -- файлов нет вообще; "missing" -- папки уже нет;
    "blocked" -- трогать нельзя (нашёлся файл, сеть не ответила, дерево
    слишком большое).
    """
    seen = 0
    sem = asyncio.Semaphore(INSPECT_CONCURRENCY)

    async def walk(path: str, depth: int) -> tuple[str, str]:
        nonlocal seen
        seen += 1
        if seen > max_folders:
            return "blocked", "слишком большое дерево папок"
        if depth > MAX_DEPTH:
            return "blocked", "слишком глубокая вложенность"
        try:
            async with sem:
                items, trustworthy = await _listdir(disk, path)
        except FileNotFoundError:
            return "missing", ""
        except Exception as exc:  # noqa: BLE001 - сеть/токен: не удаляем, а честно пропускаем
            return "blocked", f"не удалось перечислить: {type(exc).__name__}"

        # Неполный или противоречивый ответ -- не доказательство пустоты.
        # Консервативно оставляем дерево в покое: следующий заход
        # попробует снова.
        if not trustworthy:
            return "blocked", "сервер отдал неполное содержимое папки"
        # Всё, что не папка, считаем файлом. Объект без поля type тоже
        # считаем файлом: неизвестное удалять нельзя.
        files = [i for i in items if i.get("type") != "dir"]
        if files:
            return "blocked", "в облаке есть файлы"
        children = [i["path"] for i in items
                    if i.get("type") == "dir" and i.get("path")]
        if children:
            results = await asyncio.gather(
                *(walk(child, depth + 1) for child in children))
            for verdict, reason in results:
                if verdict == "blocked":
                    return verdict, reason
            # "missing" у РЕБЁНКА не делает отсутствующим родителя: его
            # мы только что успешно перечислили, он есть и он пуст.
            # Раньше это правило ошибочно помечало весь корень как уже
            # удалённый, и пустая папка оставалась в облаке навсегда.
        return "empty", ""

    verdict, reason = await walk(root, 0)
    return verdict, seen, reason


async def scan_live(disk: Disk, root: str = ROOT, *,
                    should_stop: Callable[[], bool] | None = None,
                    on_progress: Callable[[int, int], None] | None = None,
                    max_folders: int = MAX_LIVE_FOLDERS) -> dict:
    """Перечислить ВСЁ облако живьём и собрать пустые деревья.

    В отличие от `candidates()` тут нет описи вообще: решение принимается
    по ответам Диска в момент обхода. Это закрывает главный пробел -- папки,
    которые опустели ПОСЛЕ последней описи и потому в базе ещё числятся
    с файлами. Цена: по одному запросу на каждую папку коллекции (~17 тыс.
    на реальной базе), поэтому обход идёт отдельной задачей с прогрессом
    и кнопкой «стоп».

    Консервативные правила, чтобы не удалить лишнего:

    * файл (или объект без `type`) защищает свою папку и всех предков, но
      не мешает удалить пустую СОСЕДНЮЮ ветку -- так же, как `candidates`;
    * папка, которую не удалось перечислить, или ответ с `total > 0` при
      пустых `items`, защищает себя и всю цепочку вверх: содержимое
      неизвестно, а значит неизвестно и то, что выше;
    * оборванный обход (стоп, лимит папок, глубина) НЕ отдаёт ни одного
      корня: список по неполным данным удалять нельзя.

    `delete_empty` всё равно перепроверяет каждый корень перед DELETE:
    между обходом и нажатием «убрать» в папку могли положить файл.
    """
    dirs: set[str] = set()
    protected: set[str] = set()   # есть файлы -- папка и все предки
    blocked: set[str] = set()     # ответу нельзя верить -- папка и предки
    unreliable = 0                # сколько ВЕТОК не удалось проверить
    scanned = 0
    incomplete = False
    sem = asyncio.Semaphore(INSPECT_CONCURRENCY)

    def guard(path: str) -> None:
        """Неизвестное содержимое: защитить папку и всю цепочку вверх."""
        nonlocal unreliable
        unreliable += 1
        p: str | None = path
        while p:
            blocked.add(p)
            if p == ROOT:
                break
            p = _parent(p)

    async def one(path: str, depth: int) -> list[str]:
        nonlocal scanned, incomplete
        if should_stop is not None and should_stop():
            incomplete = True
            return []
        if scanned >= max_folders or depth > MAX_DEPTH:
            incomplete = True
            guard(path)
            return []
        scanned += 1
        try:
            async with sem:
                items, trustworthy = await _listdir(disk, path)
        except FileNotFoundError:
            # Папка исчезла между перечислением родителя и своим вызовом.
            # Удалять нечего; родитель от этого не становится непустым.
            return []
        except Exception as exc:  # noqa: BLE001 - сеть не доказательство пустоты
            log.info("живой обход: %s не перечислен (%s)", path,
                     type(exc).__name__)
            guard(path)
            return []
        if not trustworthy:
            guard(path)
            return []
        children: list[str] = []
        for item in items:
            child = item.get("path")
            if not child:
                # Объект без пути: не знаем, что это. Ветку не трогаем.
                guard(path)
                return []
            if item.get("type") == "dir":
                dirs.add(child)
                children.append(child)
            else:
                # Всё, что не папка, считаем файлом. Без `type` тоже.
                protected.update(_ancestors(child))
        if on_progress is not None and scanned % 100 == 0:
            on_progress(scanned, len(dirs))
        return children

    # Ширина в batches: 17 тыс. папок не превращаются в 17 тыс. корутин
    # одновременно, но сеть всё время занята 8 потоками.
    frontier: list[tuple[str, int]] = [(root, 0)]
    batch_size = INSPECT_CONCURRENCY * 4
    while frontier and not incomplete:
        batch = frontier[:batch_size]
        frontier = frontier[batch_size:]
        found = await asyncio.gather(*(one(p, d) for p, d in batch))
        for (_path, depth), children in zip(batch, found):
            frontier.extend((child, depth + 1) for child in children)

    if incomplete or (should_stop is not None and should_stop()):
        log.info("живой обход прерван: %s папок, корни не отдаём", scanned)
        return {"roots": [], "trees": 0, "folders": 0, "sample": [],
                "confirm": 0, "source": "live", "scanned": scanned,
                "blocked": unreliable, "complete": False}

    pre = root if root.endswith("/") else root + "/"
    cands = sorted(p for p in dirs - protected - blocked
                   if p != ROOT and p != root and p.startswith(pre))
    roots = tree_roots(cands)
    if on_progress is not None:
        on_progress(scanned, len(dirs))
    return {
        "roots": roots, "trees": len(roots), "folders": len(cands),
        "sample": roots[:20], "confirm": len(roots), "source": "live",
        "scanned": scanned, "blocked": unreliable, "complete": True,
    }


def _mark_gone(conn: sqlite3.Connection, root: str) -> None:
    """Убрать дерево из описи, сохранив историю имён и файлов.

    Записи не удаляем: проект хранит слепок даже того, чего в облаке уже
    нет (reconcile делает то же самое). Помечаем vanished_at -- линза
    «Сейчас» сразу перестанет показывать папки. Пометку empty_dirs
    снимаем, иначе следующая опись пропустит несуществующую папку.
    """
    pre, post = _span(root)
    conn.execute(
        "UPDATE resources SET vanished_at=? WHERE vanished_at IS NULL "
        "AND (path=? OR (path>=? AND path<?))",
        (db.now(), root, pre, post))
    conn.execute(
        "DELETE FROM empty_dirs WHERE path=? OR (path>=? AND path<?)",
        (root, pre, post))


async def delete_empty(conn: sqlite3.Connection, disk: Disk,
                       roots: list[str], *, confirm: int = -1,
                       permanently: bool = False,
                       job_id: int | None = None) -> dict:
    """Удалить пустые деревья. confirm должен совпасть с числом корней.

    Пустые папки не занимают квоту, поэтому по умолчанию уходят в
    Корзину: структуру можно вернуть. Безвозвратное удаление -- явный
    выбор человека в окне подтверждения.
    """
    if confirm != len(roots):
        raise ValueError(
            f"не подтверждено: пустых деревьев {len(roots)}, "
            f"а confirm={confirm}. "
            f"Передай confirm={len(roots)}, если согласен.")
    if not roots:
        return {"deleted": 0, "already": 0, "kept": 0, "failed": 0}

    # `kept`, а не `skipped`: это не «обработано успешно», а «оставлено
    # в облаке, потому что по факту там есть файлы или ответ недостоверен».
    # В _success_count сервера skipped числится успехом -- такое имя
    # сделало бы задачу «готово» даже когда не удалено ничего.
    done: dict = {"deleted": 0, "already": 0, "kept": 0, "failed": 0,
                  "errors": []}
    stop = db.CancelWatch(conn, job_id)

    async with stop:
        for i, root in enumerate(sorted(roots), 1):
            if stop():
                break
            verdict, folders, reason = await inspect_tree(disk, root)
            if verdict == "blocked":
                done["kept"] += 1
                if len(done["errors"]) < 50:
                    done["errors"].append({"path": root, "reason": reason})
                log.info("пустые папки: %s оставлено в облаке (%s)",
                         root, reason)
            elif verdict == "missing":
                _mark_gone(conn, root)
                done["already"] += 1
            else:
                ok, detail = await disk.delete(root, permanently=permanently)
                # 404 -- папку убрал клиент Диска между проверкой и
                # удалением. Цель достигнута, это не ошибка.
                already = (not ok) and ("404" in detail
                                        or "DiskNotFoundError" in detail)
                if ok or already:
                    _mark_gone(conn, root)
                    cloud.audit({
                        "ts": db.now(), "action": "empty_dir_delete",
                        "path": root, "folders": folders,
                        "permanently": permanently})
                    if already:
                        done["already"] += 1
                    else:
                        done["deleted"] += 1
                    log.info("пустые папки: %s удалено (%s папок, "
                             "permanently=%s)", root, folders, permanently)
                else:
                    done["failed"] += 1
                    if len(done["errors"]) < 50:
                        done["errors"].append({"path": root, "error": detail})
            if job_id is not None:
                db.job_progress(conn, job_id, i, len(roots),
                                f"пустых деревьев: {i}/{len(roots)}")
    return done
