"""Проверки того, что ломается молча.

Выбраны ровно те места, где ошибка не видна глазами, а цена высокая:
агрегаты дерева (по ним человек решает, что качать), план порции (по нему
решается, хватит ли места) и допуск к удалению из облака (по нему файл
исчезает навсегда).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from drydock import db, download, tree
from drydock.archive import plan_batch
from drydock.cloud import eligible
from drydock.download import plan
from drydock.localpath import cloud_to_relative, extended, safe_component


def make_db(tmp: Path):
    conn = db.connect(tmp / "t.db")
    items = [
        {"path": "disk:/Library", "name": "Library", "type": "dir"},
        {"path": "disk:/Library/Sorted", "name": "Sorted", "type": "dir"},
        {"path": "disk:/Library/Sorted/Наука", "name": "Наука", "type": "dir"},
        {"path": "disk:/Library/Sorted/Наука/a.pdf", "name": "a.pdf", "type": "file",
         "size": 1000, "md5": "m1", "sha256": "s1"},
        {"path": "disk:/Library/Sorted/Наука/b.pdf", "name": "b.pdf", "type": "file",
         "size": 2000, "md5": "m2", "sha256": "s2"},
        {"path": "disk:/Library/Sorted/История", "name": "История", "type": "dir"},
        {"path": "disk:/Library/Sorted/История/c.djvu", "name": "c.djvu", "type": "file",
         "size": 4000, "md5": "m3", "sha256": "s3"},
        {"path": "disk:/top.txt", "name": "top.txt", "type": "file", "size": 7},
    ]
    for it in items:
        db.upsert_resource(conn, it)
    return conn


def test_paths():
    assert cloud_to_relative("disk:/Library/Sorted/Наука/a.pdf") == \
        Path("Library/Sorted/Наука/a.pdf")
    # Запрещённые в Windows символы заменяются, а не теряются.
    assert safe_component('Что?: "так"') == "Что\uf03f\uf03a \uf022так\uf022"
    # Точка и пробел на конце: Windows их молча срезает -- мы срезаем сами,
    # чтобы путь в базе совпадал с путём на диске.
    assert safe_component("имя. ") == "имя"
    assert safe_component("COM1") == "_COM1"
    long = Path("C:/") / ("x" * 150) / ("y" * 150)
    assert extended(long).startswith("\\\\?\\")
    # Компонент длиннее 255 Windows не принимает даже с префиксом \\?\:
    # имя книги из облака («...Том 3. 1892.pdf», 255 символов) плюс
    # «.jpg» давало Errno 22 и 17 октября убило порцию превью после
    # часа описи. Обрезка детерминированная, с двух концов: начало
    # несут длинные названия, хвост -- том, год и формат.
    long_name = "я" * 250 + " Книга.pdf"
    short = safe_component(long_name)
    assert len(short) <= 255, len(short)
    assert short.endswith(".pdf"), short
    assert short == safe_component(long_name), "обрезка должна быть детерминированной"
    assert safe_component("я" * 250 + " Другая.pdf") != short, \
        "разные длинные имена не должны схлопываться в один файл"
    assert safe_component("обычное имя.pdf") == "обычное имя.pdf"
    real = ("Русская историческая библиография. Указатель книг и статей "
            "по русской и всеобщей истории и вспомогательным наукам "
            "за 1800-1854 включительно. Том 3. 1892.pdf")
    # Влезает в лимит -- имя существует на NTFS как есть, резать нечего.
    assert len(real) <= 255 and safe_component(real) == real
    # А с хвостом «.jpg» к превью -- уже нет: режем, оба конца целы.
    padded = real.replace("Том 3", "Том " + "3" * 40)
    cut = safe_component(padded)
    assert len(cut) <= 255, len(cut)
    assert cut.startswith("Русская историческая"), cut[:40]
    assert "1892.pdf" in cut, cut[-40:]
    print("пути: ок")


def test_client_constructs():
    """Клиент обязан создаваться. Звучит глупо -- ровно это и сломалось.

    В User-Agent была кириллица, httpx кодирует заголовки в latin-1 и падал
    прямо в конструкторе. Валилось ВСЁ -- scan, probe, download, whoami, --
    а прежние проверки трогали только базу и 7z и этого не видели.
    """
    from drydock.yandex import Disk

    disk = Disk("test-token-not-real")
    for key, value in disk._client.headers.items():
        value.encode("latin-1")  # упадёт, если снова появится не-ASCII
        key.encode("latin-1")
    assert "OAuth " in disk._auth["Authorization"]
    import asyncio as _a
    _a.run(disk.aclose())
    print("клиент создаётся, заголовки ASCII: ок")


def test_plan_batch():
    # Запас не трогаем: 10 ГБ свободно, запас 5 ГБ -> бюджет 5 ГБ.
    gb = 1024 ** 3
    assert plan_batch([2 * gb, 2 * gb, 2 * gb], 10 * gb, reserve=5 * gb) == 2
    # Не влезает даже первый -- честный ноль, а не "попробуем".
    assert plan_batch([9 * gb], 10 * gb, reserve=5 * gb) == 0
    assert plan_batch([], 10 * gb, reserve=5 * gb) == 0
    print("план порции: ок")


def test_tree(tmp: Path):
    conn = make_db(tmp)
    kids = {c["name"]: c for c in tree.children(conn, "disk:/")}
    assert set(kids) == {"Library", "top.txt"}, kids.keys()
    assert kids["Library"]["is_dir"] is True
    assert kids["top.txt"]["is_dir"] is False
    # Итог по поддереву, а не по прямым детям: 3 файла на 7000 байт.
    assert kids["Library"]["files"] == 3, kids["Library"]
    assert kids["Library"]["bytes"] == 7000, kids["Library"]
    assert kids["Library"]["unchecked"] == 3

    sub = {c["name"]: c for c in tree.children(conn, "disk:/Library/Sorted")}
    assert sub["Наука"]["files"] == 2 and sub["Наука"]["bytes"] == 3000
    assert sub["История"]["files"] == 1 and sub["История"]["bytes"] == 4000

    # Пробы и спасённое попадают в агрегаты.
    db.record_probe(conn, "disk:/Library/Sorted/Наука/a.pdf", "ok", 206)
    db.record_probe(conn, "disk:/Library/Sorted/Наука/b.pdf", "unavailable", 504)
    conn.execute(
        """INSERT INTO local(path,local_path,bytes,sha256,md5,verify,downloaded_at)
           VALUES('disk:/Library/Sorted/Наука/a.pdf','x',1000,'s1','m1','ok',1)""")
    kids = {c["name"]: c for c in tree.children(conn, "disk:/")}
    lib = kids["Library"]
    # Байты доступного/спасённого по папке интерфейсу не нужны, поэтому
    # в строке дерева их нет (они остались в totals -- там чипы с объёмом).
    assert lib["ok"] == 1, lib
    assert lib["unavailable"] == 1 and lib["saved"] == 1, lib

    # Один путь в двух архивах не должен удваивать суммы.
    conn.execute("INSERT INTO archives(id,name,created_at,state) "
                 "VALUES(1,'A',1,'verified'),(2,'B',2,'verified')")
    conn.execute("INSERT INTO archive_members(archive_id,path) VALUES"
                 "(1,'disk:/Library/Sorted/Наука/a.pdf'),"
                 "(2,'disk:/Library/Sorted/Наука/a.pdf')")
    lib = {c["name"]: c for c in tree.children(conn, "disk:/")}["Library"]
    assert lib["files"] == 3 and lib["archived"] == 1, lib

    t = tree.totals(conn)
    assert t["files"] == 4 and t["dirs"] == 4, t

    files = tree.subtree_files(conn, "disk:/Library", states=["ok"])
    assert files == ["disk:/Library/Sorted/Наука/a.pdf"], files
    print("дерево: ок")


def test_staleness(tmp: Path):
    """Проба -- наблюдение с датой, а не свойство файла.

    ЦОДы отключали частично и вернуться в строй они могут тоже частично,
    поэтому "доступно" вчерашней давности не должно выдаваться за текущее
    состояние, а "недоступно" -- закрывать файлу дорогу навсегда.
    """
    from drydock import probe

    conn = make_db(tmp)
    a = "disk:/Library/Sorted/Наука/a.pdf"
    b = "disk:/Library/Sorted/Наука/b.pdf"
    db.record_probe(conn, a, "ok", 206)
    db.record_probe(conn, b, "unavailable", 504)
    # Состарим обе записи на двое суток.
    old = db.now() - 48 * 3600
    conn.execute("UPDATE probe SET checked_at=?", (old,))

    t = tree.totals(conn)
    assert t["ok"] == 1, t
    assert t["ok_fresh"] == 0, "старое наблюдение не может считаться свежим"
    assert t["stale"] == 2, t

    # Устаревшее должно само проситься на перепроверку...
    stale = probe.select_paths(conn, states=["stale"])
    assert set(stale) == {a, b}, stale
    # ...а свежее -- не попадать в очередь.
    db.record_probe(conn, a, "ok", 206)
    assert probe.select_paths(conn, states=["stale"]) == [b]

    # Недоступное обязано оставаться перепроверяемым: это и есть надежда на
    # вернувшийся ЦОД.
    assert b in probe.select_paths(conn, states=["unavailable"])
    assert tree.totals(conn)["ok_fresh"] == 1
    print("срок годности пробы: ок")


def test_cancel_watch(tmp: Path):
    """«Стоп» должен быть виден каждому файлу, а не только порции.

    Раньше отмена проверялась между порциями по 25-50 файлов, а порция ждёт
    самый медленный файл в ней -- до двух минут таймаута выгрузки. Нажатие
    выглядело проигнорированным.
    """
    import asyncio

    conn = make_db(tmp)
    job = db.job_start(conn, "probe", 100)

    async def scenario() -> tuple[int, bool]:
        started = 0
        async with db.CancelWatch(conn, job, period=0.05) as stop:
            for i in range(100):
                if stop():
                    break
                started += 1
                if i == 3:  # «нажали стоп» посреди работы
                    conn.execute("UPDATE jobs SET cancel=1 WHERE id=?", (job,))
                await asyncio.sleep(0.02)
            return started, stop()

    started, stopped = asyncio.run(scenario())
    assert stopped, "флаг отмены не доехал до работника"
    assert started < 100, "работа не остановилась"
    assert started < 30, f"остановка заняла {started} шагов -- слишком долго"
    print(f"отмена: работа встала через {started} шагов вместо 100")


def test_download_plan(tmp: Path):
    conn = make_db(tmp)
    db.record_probe(conn, "disk:/Library/Sorted/Наука/a.pdf", "ok", 206)
    db.record_probe(conn, "disk:/Library/Sorted/История/c.djvu", "unavailable", 504)
    p = plan(conn, ["disk:/Library/Sorted/Наука/a.pdf",
                    "disk:/Library/Sorted/Наука/b.pdf",
                    "disk:/Library/Sorted/История/c.djvu"])
    assert p["count"] == 3 and p["bytes"] == 7000
    assert p["available"] == 1 and p["available_bytes"] == 1000
    assert p["unavailable"] == 1 and p["unchecked"] == 1, p
    print("план выгрузки: ок")


def test_eligible(tmp: Path):
    """Главная защита: что допускается к удалению из облака."""
    conn = make_db(tmp)
    a = "disk:/Library/Sorted/Наука/a.pdf"
    b = "disk:/Library/Sorted/Наука/b.pdf"
    c = "disk:/Library/Sorted/История/c.djvu"
    conn.execute(
        """INSERT INTO local(path,local_path,bytes,sha256,md5,verify,holes,downloaded_at)
           VALUES(?,?,1000,'s1','m1','ok',NULL,1)""", (a, str(tmp / "a.pdf")))
    (tmp / "a.pdf").write_bytes(b"x" * 1000)
    # Файл с дырками: спасён частично, облачная копия -- единственный шанс.
    conn.execute(
        """INSERT INTO local(path,local_path,bytes,sha256,md5,verify,holes,downloaded_at)
           VALUES(?,?,2000,'z','z','salvaged',?,1)""",
        (b, str(tmp / "b.pdf"), json.dumps([[0, 1024]])))
    # c -- вообще не скачан.

    ok, blocked = eligible(conn, [a, b, c], level="downloaded")
    assert [r["path"] for r in ok] == [a], [r["path"] for r in ok]
    reasons = {r["path"]: r["reason"] for r in blocked}
    assert "дырками" in reasons[b], reasons
    assert reasons[c] == "не скачан", reasons

    # Строгий уровень: без проверенного архива не удаляем ничего.
    ok, blocked = eligible(conn, [a, b, c], level="archived")
    assert ok == [], ok
    assert any("архив" in r["reason"] for r in blocked)

    # Архив есть, но его тома на диске отсутствуют -> всё равно нельзя.
    conn.execute("INSERT INTO archives(id,name,created_at,state) VALUES(1,'A',1,'verified')")
    conn.execute("INSERT INTO archive_members(archive_id,path) VALUES(1,?)", (a,))
    conn.execute("INSERT INTO archive_volumes(archive_id,volume,bytes,sha256) "
                 "VALUES(1,'A.7z.001',10,'deadbeef')")
    ok, blocked = eligible(conn, [a], level="archived")
    assert ok == [], "архив без томов на диске не должен допускать удаление"
    print("допуск к удалению: ок")


def test_remaining(tmp: Path):
    """Остаток по состоянию облака: доступное, недоступное и пропавшее
    разведены, потому что «осталось 791 ГБ» -- не то же самое, что
    «столько ещё можно взять»."""
    # Своя база: make_db сеет четыре файла, и они попали бы в остаток.
    conn = db.connect(tmp / "left.db")
    files = [
        ("disk:/r/avail.pdf", 100, "ok", False),
        ("disk:/r/sick.pdf", 200, "unavailable", False),
        ("disk:/r/gone.pdf", 400, "gone", False),
        ("disk:/r/never.pdf", 800, None, False),
        ("disk:/r/saved.pdf", 1600, "ok", True),
    ]
    for path, size, state, saved in files:
        db.upsert_resource(conn, {"path": path, "name": path.rsplit("/", 1)[-1],
                                  "type": "file", "size": size})
        if state:
            db.record_probe(conn, path, state, 200 if state == "ok" else 404,
                            "s1x.storage.yandex.net")
        if saved:
            conn.execute(
                """INSERT INTO local(path,local_path,bytes,sha256,md5,verify,downloaded_at)
                   VALUES(?,?,?,'s','m','ok',?)""",
                (path, str(tmp / "saved.pdf"), size, db.now()))
    # Удалённое нами и исчезнувшее из описания в остаток не входят.
    db.upsert_resource(conn, {"path": "disk:/r/deleted.pdf", "name": "deleted.pdf",
                              "type": "file", "size": 3200})
    conn.execute("INSERT INTO cloud_deleted(path,deleted_at,permanently,response) "
                 "VALUES(?,?,?,?)",
                 ("disk:/r/deleted.pdf", db.now(), 0, "удалено нами из облака"))
    db.upsert_resource(conn, {"path": "disk:/r/vanished.pdf", "name": "vanished.pdf",
                              "type": "file", "size": 6400})
    conn.execute("UPDATE resources SET vanished_at=? WHERE path='disk:/r/vanished.pdf'",
                 (db.now(),))

    r = tree.remaining(conn)
    assert r["files"] == 4, r
    assert r["bytes"] == 100 + 200 + 400 + 800, r
    assert r["available_files"] == 1, r
    assert r["by_state"]["gone"]["files"] == 1, r
    assert r["by_state"]["unavailable"]["files"] == 1, r
    assert r["by_state"]["unchecked"]["files"] == 1, r
    print("остаток: доступное, недоступное, пропавшее и непроверенное разведены")


def test_salvaged_fixed(tmp: Path):
    """«С дырками» убывает, «докачано полностью» растёт.

    Отметка salvaged_at ставится при спасении с дырками и НЕ стирается,
    когда файл потом докачали целиком -- иначе второй счётчик считать
    неоткуда.
    """
    conn = db.connect(tmp / "fix.db")
    path = "disk:/r/holed.pdf"
    db.upsert_resource(conn, {"path": path, "name": "holed.pdf",
                              "type": "file", "size": 4096})
    target = tmp / "holed.pdf"
    target.write_bytes(b"x" * 4096)

    # 1. Спасли с дырками.
    download.save_local(conn, path, target, 2048, "s", "m", "salvaged",
                        [[0, 2048]])
    t = tree.totals(conn)
    assert t["salvaged"] == 1 and t["fixed"] == 0, t
    assert t["salvaged_bytes"] == 4096, t
    row = conn.execute("SELECT salvaged_at FROM local WHERE path=?", (path,)).fetchone()
    assert row["salvaged_at"] > 0, dict(row)

    # 2. Докачали целиком: дырок нет, но отметка осталась.
    download.save_local(conn, path, target, 4096, "s2", "m2", "ok", [])
    t = tree.totals(conn)
    assert t["salvaged"] == 0, t
    assert t["fixed"] == 1, t
    row = conn.execute("SELECT salvaged_at FROM local WHERE path=?", (path,)).fetchone()
    assert row["salvaged_at"] > 0, dict(row)
    print("дырки: счётчик убывает, «докачано полностью» растёт")


def test_inflight_reserve(tmp: Path):
    """Запас на диске считается с учётом уже начатых выгрузок.

    Проверка «на файл» при 48 потоках пропускает всех: каждый видит один
    и тот же запас. 22 октября в 21:30 это кончилось тем, что диск
    заполнился и SQLite упал с «database or disk is full».
    """
    real_free = download.free_space
    gb = 2 ** 30
    # Запас берём из настроек: в тестах окружение задаёт своё значение,
    # и арифметика «на 5 ГБ» ломалась бы при другом.
    reserve = download.config.RESERVE
    free = 20 * gb
    try:
        download.free_space = lambda _p: free   # type: ignore[assignment]
        download._inflight = 0
        # Ровно до запаса: после этого ещё один байт уже не влезает.
        first = free - reserve
        assert download._claim_space(first), "влезает до запаса"
        assert not download._claim_space(gb), "второй файл уже съедает запас"
        assert download._claim_space(0), "нулевой размер не мешает"
        download._release_space(first)
        assert download._claim_space(first), "после освобождения -- снова можно"
        download._release_space(first)
        download._inflight = 0
        assert download._inflight == 0
    finally:
        download.free_space = real_free  # type: ignore[assignment]
        download._inflight = 0
    print("место резервируется с учётом начатых выгрузок")


def test_hosts_report(tmp: Path):
    """Узлы и кластеры: остаток разложен по машинам и ЦОД."""
    conn = db.connect(tmp / "hosts.db")
    items = [
        ("disk:/h/a.pdf", "s280klg.storage.yandex.net", "unavailable"),
        ("disk:/h/b.pdf", "s535klg.storage.yandex.net", "unavailable"),
        ("disk:/h/c.pdf", "s335vla.storage.yandex.net", "unavailable"),
        ("disk:/h/d.pdf", "s340vla.storage.yandex.net", "ok"),
    ]
    for path, host, state in items:
        db.upsert_resource(conn, {"path": path, "name": path.rsplit("/", 1)[-1],
                                  "type": "file", "size": 100})
        db.record_probe(conn, path, state, 200 if state == "ok" else 500, host)

    rep = tree.hosts_report(conn)
    by_cluster = {c["name"]: c for c in rep["clusters"]}
    assert by_cluster["klg"]["files"] == 2, by_cluster
    assert by_cluster["vla"]["files"] == 2, by_cluster
    assert by_cluster["vla"]["ok"] == 1 and by_cluster["vla"]["share"] == 0.5, by_cluster
    assert by_cluster["klg"]["share"] == 0.0, by_cluster
    # Узлы -- по одному на машину.
    names = {h["name"] for h in rep["hosts"]}
    assert "s280klg.storage.yandex.net" in names and len(names) == 4, names
    print("узлы и кластеры: остаток разложен, доля живых считается")


def test_health_report(tmp: Path):
    """Здоровье: причины отказов, дни и задачи считаются по базе.

    Проверяем главное: отказ хранилища, отсутствие файла и наше
    собственное удаление -- разные причины, и путать их нельзя. Иначе
    отчёт скажет «хранилище больно» там, где файл просто удалили.
    """
    from drydock import health

    conn = db.connect(tmp / "health.db")
    host = "s280klg.storage.yandex.net"
    items = [
        ("disk:/h/ok.pdf", "ok", 200, ""),
        ("disk:/h/silent.pdf", "unavailable", None, "ReadTimeout: хранилище молчит"),
        ("disk:/h/broken.pdf", "unavailable", 500,
         "RemoteProtocolError: peer closed connection"),
        ("disk:/h/nolink.pdf", "gone", 404, "нет ссылки на disk:/h/nolink.pdf: HTTP 404"),
        ("disk:/h/ours.pdf", "gone", 404, "удалено нами из облака"),
    ]
    for path, state, code, detail in items:
        db.upsert_resource(conn, {"path": path, "name": path.rsplit("/", 1)[-1],
                                  "type": "file", "size": 1000})
        db.record_probe(conn, path, state, code, host, detail=detail or None)

    # Одно спасение сегодня и одно удаление из облака.
    conn.execute(
        """INSERT INTO local(path,local_path,bytes,sha256,md5,verify,downloaded_at)
           VALUES(?,?,?,?,?,'ok',?)""",
        ("disk:/h/ok.pdf", str(tmp / "ok.pdf"), 1000, "s", "m", db.now()))
    conn.execute("INSERT INTO cloud_deleted(path,deleted_at,permanently,response) "
                 "VALUES(?,?,?,?)", ("disk:/h/ours.pdf", db.now(), 0, "удалено нами"))

    # Две задачи: одна прошла, одна упала.
    jid = db.job_start(conn, "download-loop", 10)
    conn.execute("UPDATE jobs SET state='done', done=10 WHERE id=?", (jid,))
    jid = db.job_start(conn, "probe", 5)
    conn.execute("UPDATE jobs SET state='failed', message='диск кончился' WHERE id=?",
                 (jid,))
    conn.commit()

    r = health.report(conn, days=7)
    assert r["kpi"]["saved"] == 1, r["kpi"]
    assert r["kpi"]["deleted"] == 1, r["kpi"]

    reasons = {x["code"]: x["n"] for x in r["reasons"]}
    assert reasons == {"silent": 1, "broken": 1}, reasons
    gone = {x["code"]: x["n"] for x in r["gone"]}
    assert gone == {"no_link": 1, "ours": 1}, gone

    # Сегодняшний день -- последний в окне, и в нём видно спасение.
    today = r["days"][-1]
    assert today["saved"] == 1 and today["deleted"] == 1, today
    assert len(r["days"]) == 7, r["days"]

    assert r["jobs"]["total"] == 2, r["jobs"]
    assert r["jobs"]["failed_total"] == 1, r["jobs"]
    assert r["jobs"]["failed"][0]["kind"] == "probe", r["jobs"]

    # Узел один, и отказов на нём три (silent, broken, no_link? нет --
    # nolink и ours тоже gone, они считаются отказом узла).
    assert r["hosts"] and r["hosts"][0]["bad"] >= 3, r["hosts"]
    print("здоровье: причины, дни и задачи считаются по базе")


def test_present_bytes(tmp: Path):
    """Объём «на диске» -- тем же правилом, что и штуки.

    Файл, перенесённый вручную, лежит на диске (present), но проверять его
    не с чем (unverified). Раньше штуки его считали, а байты -- нет, и
    папка показывала «2 092 шт · 0 Б».
    """
    conn = db.connect(tmp / "present.db")
    path = "disk:/p/manual.pdf"
    db.upsert_resource(conn, {"path": path, "name": "manual.pdf",
                              "type": "file", "size": 1000})
    conn.execute(
        """INSERT INTO local(path,local_path,bytes,sha256,md5,verify,downloaded_at)
           VALUES(?,?,1000,'s','m','unverified',?)""",
        (path, str(tmp / "manual.pdf"), db.now()))
    t = tree.totals(conn)
    assert t["present"] == 1, t
    assert t["present_bytes"] == 1000, t
    assert t["saved"] == 0, t          # проверенным он не стал
    print("на диске: штуки и байты считаются одним правилом")


def main() -> int:
    import tempfile
    test_paths()
    test_client_constructs()
    test_plan_batch()
    for fn in (test_tree, test_staleness, test_cancel_watch, test_download_plan,
               test_eligible, test_remaining,
               test_salvaged_fixed, test_inflight_reserve, test_hosts_report,
               test_health_report, test_present_bytes):
        # ignore_cleanup_errors: SQLite на Windows держит файл до сборки
        # мусора, а проверять мы хотим логику, не уборку.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            fn(Path(d))
    print("\nвсе проверки прошли")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
