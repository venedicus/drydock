"""Проверка HTTP-слоя: кнопки интерфейса должны действительно работать.

Этого теста не хватало дважды, и оба раза цена была одинаковой -- человек
нажимал кнопку, получал 500 и висящую на нуле полоску, а в логе не было
ничего. Прошлые проверки трогали базу, пути и 7z, то есть всё, кроме того
единственного пути, которым пользуются на самом деле: запрос -> обработчик
-> фоновая задача.

Главное здесь -- не код ответа, а то, что задача РЕАЛЬНО запустилась и
дошла до конца. Ошибка была именно в этом: строка задачи создавалась, ответ
падал в 500, а корутина не стартовала никогда, потому что
asyncio.create_task() вызывался из потока пула, где нет event loop.

Сеть не трогаем: каталог пустой, поэтому опись превью и проба честно
находят ноль файлов и завершаются сами, а клиент Диска подменён заглушкой.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Self

try:  # pytest есть не всегда: файл умеет запускаться и напрямую.
    import pytest
except ImportError:  # pragma: no cover - режим без pytest
    pytest = None

ROOT = Path(tempfile.mkdtemp(prefix="cr-srv-"))
os.environ["DRYDOCK_ROOT"] = str(ROOT)
os.environ["DRYDOCK_SECRETS"] = str(ROOT / "secrets.bin")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from drydock import config, server

if pytest is not None:

    @pytest.fixture(autouse=True, scope="module")
    def _own_root():
        """Свой корень спасения для этого файла тестов.

        Файл задаёт DRYDOCK_ROOT при импорте, а PATHS связывается
        один раз на процесс. Если в одном воркере оказалось несколько
        файлов, они бы поделили корень и писали в чужую базу.
        """
        config.set_root(ROOT)
        yield


if pytest is not None:

    @pytest.fixture()
    def client():
        """Живой клиент приложения с подменённым Диском.

        Папка tmp приходит общей фикстурой из conftest.py.
        """
        server._disk = lambda concurrency=None: FAKE
        with TestClient(server.app) as c:
            yield c


class FakeDisk:
    """Ровно столько, сколько трогают обработчики на пустом каталоге."""

    def __init__(self) -> None:
        self.deleted: list[tuple[str, bool]] = []

    async def aclose(self) -> None:
        return None

    async def delete(self, path: str, *, permanently: bool = True):
        self.deleted.append((path, permanently))
        return True, ""

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


def wait_job(client: TestClient, job_id: int, timeout: float = 10) -> dict:
    """Дождаться, пока задача перестанет быть running."""
    deadline = time.time() + timeout
    last: dict = {}
    while time.time() < deadline:
        for job in client.get("/api/jobs?limit=20").json()["items"]:
            if job["id"] == job_id:
                last = job
                if job["state"] != "running":
                    return job
        time.sleep(0.15)
    return last


def test_reads(client: TestClient) -> None:
    for url in ("/api/state", "/api/tree?path=disk:%2F", "/api/jobs",
                "/api/auth/status", "/api/log?lines=5", "/api/archives",
                "/api/search?q=x"):
        resp = client.get(url)
        assert resp.status_code == 200, f"{url} -> {resp.status_code} {resp.text[:200]}"
    print("чтение: все ручки отвечают 200")


def test_jobs_actually_run(client: TestClient) -> None:
    """Сердце проверки: задача стартует и доходит до конца."""
    for name, url, body in (
        ("превью", "/api/previews", {}),
        ("проба", "/api/probe", {"paths": [], "folders": [], "states": ["unchecked"]}),
    ):
        resp = client.post(url, json=body)
        assert resp.status_code == 200, \
            f"{name}: {resp.status_code} {resp.text[:300]}"
        job_id = resp.json()["job"]
        job = wait_job(client, job_id)
        assert job, f"{name}: задача {job_id} не найдена"
        assert job["state"] == "done", (
            f"{name}: состояние {job['state']}, сообщение {job.get('message')!r} "
            f"-- задача не отработала")
        print(f"{name}: задача #{job_id} дошла до состояния done")


def test_no_silent_500(client: TestClient) -> None:
    """Отказ должен быть объяснённым, а не голым Internal Server Error."""
    resp = client.post("/api/download", json={"paths": [], "folders": []})
    assert resp.status_code == 400, f"ожидал 400, получил {resp.status_code}"
    assert resp.json().get("detail"), "отказ без объяснения"
    print("пустая выгрузка: 400 со словами, а не 500")


def test_job_cancel(client: TestClient) -> None:
    resp = client.post("/api/jobs/1/cancel", json={})
    assert resp.status_code == 200, resp.text[:200]
    print("отмена задачи: ок")


def test_local_sync(client: TestClient) -> None:
    """Сверка зеркала: диск -- источник правды о том, что сохранено.

    Без неё переключатель «только нескачанное» показывал уже лежащее:
    файл перенесли в папку руками, а программа о нём не знает.
    """
    conn = server.conn()
    from drydock import config, db

    watch = config.PATHS.files / "Watch"
    watch.mkdir(parents=True, exist_ok=True)

    # 1. Файл появился мимо программы.
    (watch / "new.pdf").write_bytes(b"n" * 7)
    # 2. Запись есть, файла нет.
    db.upsert_resource(conn, {"path": "disk:/Watch/gone.pdf", "name": "gone.pdf",
                              "type": "file", "size": 5})
    conn.execute(
        "INSERT INTO local(path,local_path,bytes,verify,downloaded_at,released,missing) "
        "VALUES('disk:/Watch/gone.pdf',?,5,'ok',1,0,0)", (str(watch / "gone.pdf"),))

    resp = client.post("/api/local/sync", json={})
    assert resp.status_code == 200, resp.text[:200]

    row = conn.execute("SELECT verify, missing FROM local WHERE path='disk:/Watch/new.pdf'").fetchone()
    assert row and row["verify"] == "unverified" and row["missing"] == 0, dict(row or {})
    assert conn.execute("SELECT 1 FROM resources WHERE path='disk:/Watch/new.pdf'").fetchone()
    gone = conn.execute("SELECT missing FROM local WHERE path='disk:/Watch/gone.pdf'").fetchone()
    assert gone["missing"] == 1, dict(gone)

    # 3. Файл вернулся -- запись снова считается копией.
    (watch / "gone.pdf").write_bytes(b"g" * 5)
    client.post("/api/local/sync", json={})
    gone = conn.execute("SELECT missing FROM local WHERE path='disk:/Watch/gone.pdf'").fetchone()
    assert gone["missing"] == 0, dict(gone)
    print("сверка зеркала: новый файл учтён, исчезнувший помечен, вернувшийся снят")


def test_double_start_guard(client: TestClient) -> None:
    """Две задачи одного вида одновременно -- отказ, а не гонка.

    Две выгрузки одного файла писали один .part (файл выходил mismatch),
    две описи затирали общий чекпоинт.
    """
    from drydock import db

    conn = server.conn()
    conn.execute("INSERT INTO jobs(kind,state,started_at,total,done) "
                 "VALUES('scan','running',?,0,0)", (db.now(),))
    try:
        resp = client.post("/api/scan", json={})
        assert resp.status_code == 409, (resp.status_code, resp.text[:200])
        detail = resp.json()["detail"]
        # Ошибка приходит кодом: перевод делает интерфейс.
        assert detail["code"] == "err.busy", detail
        assert detail["kind"] == "scan", detail
    finally:
        conn.execute("UPDATE jobs SET state='interrupted' "
                     "WHERE kind='scan' AND state='running'")
    print("повторный запуск того же вида: 409 с объяснением")


def test_download_and_loop_conflict_both_directions(client: TestClient) -> None:
    """Обычная выгрузка и круг не должны трогать один .part одновременно.

    В базе это разные kind, но обе работы зовут download.run и пишут в один
    путь. Блокировка обязана быть симметричной для двух порядков запуска.
    """
    c = server.conn()
    from drydock import db

    paths = ("disk:/cross-download.pdf", "disk:/cross-loop.pdf")
    for path in paths:
        db.upsert_resource(c, {"path": path, "name": path.rsplit("/", 1)[-1],
                               "type": "file", "size": 10})

    def running(kind: str) -> int:
        return int(c.execute(
            "INSERT INTO jobs(kind,state,started_at,total,done) "
            "VALUES(?,'running',?,1,0)", (kind, db.now())).lastrowid)

    first_id = running("download-loop")
    resp = client.post("/api/download", json={
        "paths": [paths[0]], "available_only": False})
    assert resp.status_code == 409, (resp.status_code, resp.text[:200])
    assert resp.json()["detail"]["kind"] == "download-loop"
    c.execute("UPDATE jobs SET state='interrupted' WHERE id=?", (first_id,))

    second_id = running("download")
    resp = client.post("/api/download/loop", json={"paths": [paths[1]]})
    assert resp.status_code == 409, (resp.status_code, resp.text[:200])
    assert resp.json()["detail"]["kind"] == "download"
    c.execute("UPDATE jobs SET state='interrupted' WHERE id=?", (second_id,))

    autopilot_id = running("autopilot")
    resp = client.post("/api/download", json={
        "paths": [paths[0]], "available_only": False})
    assert resp.status_code == 409, (resp.status_code, resp.text[:200])
    assert resp.json()["detail"]["kind"] == "autopilot"
    c.execute("UPDATE jobs SET state='interrupted' WHERE id=?", (autopilot_id,))


def test_delete_rejects_unknown_destructive_level(client: TestClient) -> None:
    """Неизвестный уровень удаления не должен молча стать downloaded."""
    resp = client.post("/api/cloud-delete/preview", json={"level": "junk"})
    assert resp.status_code == 422, (resp.status_code, resp.text[:200])


def test_scan_body_accepts_full_flag() -> None:
    """Флаг полной описи должен доходить до сервера.

    Он снимает пропуск известно пустых папок, и без него человек не смог
    бы перепроверить облако целиком.
    """
    assert server.ScanBody(root="disk:/", full=True).full is True
    assert server.ScanBody(root="disk:/").full is False


def test_partial_state(client: TestClient) -> None:
    """Задача с провалами -- «готово с ошибками», а не «готово».

    А если провалилось всё -- это «ошибка», а не «частично»: задача #48
    по Library/Sorted провалила 71 файл из 71.
    """
    async def work_partial(_disk, _job_id):
        return {"failed": 2, "ok": 5}

    job_id = server._spawn("probe-partial", work_partial, 7, needs_disk=False)
    job = wait_job(client, job_id)
    assert job and job["state"] == "partial", job

    async def work_failed(_disk, _job_id):
        return {"failed": 7}

    job_id = server._spawn("probe-allfail", work_failed, 7, needs_disk=False)
    job = wait_job(client, job_id)
    assert job and job["state"] == "failed", job
    print("задача с провалами: partial; полный провал: failed")


def test_revived_counts_real_returns(client: TestClient) -> None:
    """«Ожило» -- только настоящее возвращение, не наши удаления."""
    from drydock import db, tree

    conn = server.conn()
    base = tree.totals(conn)["revived"]
    t = db.now()
    # был недоступен, потом ожил
    conn.execute("INSERT INTO probe_history(path,state,ts) VALUES('disk:/r1.pdf','unavailable',?)", (t - 100,))
    conn.execute("INSERT INTO probe_history(path,state,ts) VALUES('disk:/r1.pdf','ok',?)", (t,))
    # ok, потом наш gone: это удаление, а не возвращение
    conn.execute("INSERT INTO probe_history(path,state,ts) VALUES('disk:/r2.pdf','ok',?)", (t - 100,))
    conn.execute("INSERT INTO probe_history(path,state,ts) VALUES('disk:/r2.pdf','gone',?)", (t,))
    conn.execute("INSERT INTO cloud_deleted(path,deleted_at,permanently,response) "
                 "VALUES('disk:/r2.pdf',?,1,'')", (t,))
    after = tree.totals(conn)["revived"]
    assert after - base == 1, (base, after)
    print("«ожило» считает только возвращение после недоступности")


def test_autopilot_toggle(client: TestClient) -> None:
    """Автопилот включается и выключается, его видно в состоянии."""

    r = client.post("/api/autopilot", json={"on": True})
    assert r.status_code == 200, r.text[:200]
    assert r.json()["on"] is True, r.json()
    st = client.get("/api/state").json()
    assert st["autopilot"] is True, st.get("autopilot")
    assert st["autopilot_config"]["hours"] > 0, st["autopilot_config"]

    r = client.post("/api/autopilot", json={"on": False})
    assert client.get("/api/state").json()["autopilot"] is False
    print("автопилот: включение, выключение, отражение в состоянии")


def test_host_stats(client: TestClient) -> None:
    """Статистика узлов: живой узел виден живым, мёртвый -- мёртвым."""
    from drydock import autopilot, db

    conn = server.conn()
    # Ресурс + проба: кандидаты ищутся в описи, а не в одной пробе.
    for name, host, state in (("h1.pdf", "s1x.storage.yandex.net", "ok"),
                              ("h2.pdf", "s1x.storage.yandex.net", "ok"),
                              ("h3.pdf", "s2x.storage.yandex.net", "unavailable")):
        path = f"disk:/Watch/{name}"
        db.upsert_resource(conn, {"path": path, "name": name,
                                  "type": "file", "size": 100})
        db.record_probe(conn, path, state,
                        200 if state == "ok" else None, host)
    scores = autopilot.host_scores(conn)
    assert scores["s1x.storage.yandex.net"] == 1.0, scores
    assert scores["s2x.storage.yandex.net"] == 0.0, scores
    live = autopilot.host_liveness(conn)
    assert live["alive"] >= 1 and live["dead"] >= 1, live
    # Кандидаты на перепроверку: недоступное, которого нет на диске.
    cand = autopilot.recheck_candidates(conn, limit=10)
    assert "disk:/Watch/h3.pdf" in cand, cand
    # Живые файлы в кандидаты не идут: их перепроверять нечего.
    assert "disk:/Watch/h1.pdf" not in cand, cand
    print("узлы хранения: живучесть считается, порядок обхода по ней")


def test_autopilot_round(client: TestClient) -> None:
    """Круг автопилота: перепроверил и забрал ожившее.

    Проверяем склейку -- кандидаты, вызов пробы, поиск ожившего, вызов
    выгрузки. Сами проба и выгрузка подменяются: это их собственные
    тесты, а тут важен порядок. (pytest нет -- подмена руками, с
    восстановлением в finally.)
    """
    import asyncio

    from drydock import autopilot, db

    conn = server.conn()
    path = "disk:/Watch/revived.pdf"
    db.upsert_resource(conn, {"path": path, "name": "revived.pdf",
                              "type": "file", "size": 50})
    db.record_probe(conn, path, "unavailable", None, "s1x.storage.yandex.net")
    dead = "disk:/Watch/dead.pdf"
    db.upsert_resource(conn, {"path": dead, "name": "dead.pdf",
                              "type": "file", "size": 50})
    db.record_probe(conn, dead, "unavailable", None, "s2x.storage.yandex.net")

    seen: dict[str, list[str]] = {}

    async def fake_probe(c, _disk, paths, **_kw):
        seen["probed"] = list(paths)
        # Так ведёт себя настоящая проба: один файл ожил и записал это
        # в базу -- круг должен его найти по базе, а не по памяти.
        db.record_probe(c, path, "ok", 200, "s1x.storage.yandex.net")
        return {"ok": 1, "unavailable": len(paths) - 1}

    async def fake_download(_conn, _disk, paths, **_kw):
        seen["downloaded"] = list(paths)
        return {"ok": len(paths), "failed": 0}

    real_probe, real_download = autopilot.probe_mod.run, autopilot.download.run
    autopilot.probe_mod.run = fake_probe  # type: ignore[assignment]
    autopilot.download.run = fake_download  # type: ignore[assignment]
    try:
        res = asyncio.run(autopilot.round_once(conn, None))
    finally:
        autopilot.probe_mod.run = real_probe  # type: ignore[assignment]
        autopilot.download.run = real_download  # type: ignore[assignment]

    # Кандидатов может быть больше этих двух (в базе остались мёртвые
    # файлы от предыдущих тестов) -- важно, что оба наших в перепроверке,
    # а забирается только оживший.
    assert path in seen.get("probed", []), seen
    assert dead in seen.get("probed", []), seen
    assert seen.get("downloaded") == [path], seen
    assert res["revived"] == 1 and res["ok"] == 1, res
    print("автопилот: перепроверил кандидатов и забрал только ожившее")


def test_next_step(client: TestClient) -> None:
    """Следующий шаг: живое раньше мёртвого, прогон недоступного -- раньше
    перепроверки того, что и так известно."""
    from drydock import db, server

    c = server.conn()
    db.kv_set(c, "scan_queue", None)   # иначе шаг будет «продолжить опись»
    left = {"by_state": {"unavailable": {"files": 5, "bytes": 100},
                         "gone": {"files": 3, "bytes": 900}}}

    # Пустая опись -- это «ещё не начинали», а не «всё сделано».
    step = server.next_step(c, {})
    assert step["kind"] == "start", step

    step = server.next_step(c, {"files": 20, "dl_ready": 7, "unchecked": 2},
                            left=left)
    assert step["kind"] == "download" and step["n"] == 7, step

    step = server.next_step(c, {"files": 20, "dl_ready": 0, "unchecked": 2},
                            left=left)
    assert step["kind"] == "loop" and step["n"] == 5, step

    step = server.next_step(c, {"files": 20, "dl_ready": 0, "unchecked": 2},
                            left={})
    assert step["kind"] == "probe" and step["n"] == 2, step
    print("следующий шаг: пустая опись, живое, недоступное, проба")


def test_hosts_endpoints(client: TestClient) -> None:
    """Узлы и кластеры: отчёт отдаётся, пустая попытка -- понятный отказ."""
    r = client.get("/api/hosts")
    assert r.status_code == 200, r.text[:200]
    data = r.json()
    assert "hosts" in data and "clusters" in data, data
    # Без узла и кластера -- 400 с объяснением, а не 500.
    r = client.post("/api/hosts/try", json={})
    assert r.status_code == 400, r.text[:200]
    print("узлы: отчёт отдаётся, пустая попытка отклоняется с объяснением")


def test_account_in_state(client: TestClient) -> None:
    """Аккаунт отдаётся в состоянии: кнопке в шапке не нужен свой запрос."""
    from drydock import db, server

    db.kv_set(server.conn(), "account", {
        "login": "tester", "name": "Тест", "uid": 1,
        "used": 10, "total": 100, "ts": db.now()})
    d = client.get("/api/state").json()
    assert d["account"]["login"] == "tester", d.get("account")
    assert d["account"]["total"] == 100, d.get("account")
    print("аккаунт: состояние отдаёт логин и квоту")


def test_health_endpoint(client: TestClient) -> None:
    """Здоровье отдаётся и содержит все разделы, на которые смотрит UI."""
    r = client.get("/api/health")
    assert r.status_code == 200, r.text[:200]
    d = r.json()
    for key in ("kpi", "days", "reasons", "gone", "hosts", "jobs"):
        assert key in d, (key, d.keys())
    assert len(d["days"]) == 7, d["days"]
    # Окно ограничено: 0 и 999 не должны ломать запрос.
    assert client.get("/api/health?days=0").status_code == 200
    assert client.get("/api/health?days=999").status_code == 200
    print("здоровье: эндпоинт отдаёт дни, причины, узлы и задачи")


def test_job_state_vocabulary(client: TestClient) -> None:
    """Провал задачи считается по словарю той работы, которая её делала."""
    from drydock import server

    # выгрузка: провалы -- это состояния, а не ключ failed из чужой работы
    assert server._job_state({"ok": 0, "failed": 10}, False) == "failed"
    assert server._job_state({"ok": 5, "failed": 10}, False) == "partial"
    assert server._job_state({"ok": 0, "failed": 0, "salvaged": 3},
                             False) == "done"
    assert server._job_state({"no_space": 1}, False) == "failed"
    # круг
    assert server._job_state({"rounds": 2, "saved": 0, "failed": 9},
                             False) == "failed"
    # итог -- короткая строка, а не repr словаря
    summary = server._summary({"ok": 5, "failed": 0, "unavailable": 102})
    assert summary == "ok 5 · unavailable 102", summary
    print("состояние задачи: провалы по словарю работы, итог -- строкой")


def test_settings_endpoints(client: TestClient, tmp: Path) -> None:
    """Корень спасения выбирается в окне и переживает перезапуск.

    Файл настроек подменяем на временный: настоящий живёт в
    LOCALAPPDATA и после теста сдвинул бы корень самой программы.
    """
    import json

    from drydock import config

    real = config.SETTINGS_FILE
    config.SETTINGS_FILE = tmp / "settings.json"
    try:
        cur = client.get("/api/settings")
        assert cur.status_code == 200, cur.text[:200]
        assert cur.json()["save_root"] == str(config.PATHS.root), cur.json()

        new_root = tmp / "elsewhere"
        resp = client.post("/api/settings", json={"save_root": str(new_root)})
        assert resp.status_code == 200, resp.text[:200]
        # Возвращается выбранное на следующий запуск, а не действующее:
        # иначе окно показало бы старый корень как сохранённый.
        assert resp.json()["chosen_root"] == str(new_root), resp.json()
        assert resp.json()["restart_required"] is True
        assert json.loads(config.SETTINGS_FILE.read_text(encoding="utf-8"))["save_root"] \
            == str(new_root)
        # Действующий король запуска не меняется до перезапуска.
        assert client.get("/api/settings").json()["save_root"] == str(config.PATHS.root)

        # Относительный путь и пустая строка -- отказ, а не новый корень
        # в неизвестном месте.
        for bad in ("", "relative/path"):
            r = client.post("/api/settings", json={"save_root": bad})
            assert r.status_code == 400, (bad, r.status_code, r.text[:120])
        # Переменная окружения в тесте задана -- интерфейс должен сказать,
        # что выбор в окне ей не противоречит.
        assert client.get("/api/settings").json()["locked_by_env"] is True
        print("настройки корня: выбирается, проверяется, сохраняется")
    finally:
        config.SETTINGS_FILE = real


def test_mirror_endpoints(client: TestClient, tmp: Path) -> None:
    """Учёт перенесённого в зеркало вручную.

    Первый аудит такое нашёл: 1914 файлов в 500 папках лежали в
    спасении мимо программы -- ни в дереве, ни в итогах, ни в архивах.
    """
    import hashlib

    from drydock import config, db

    conn = server.conn()
    files_root = config.PATHS.files

    # Уже спасённое программой -- не трогаем.
    (files_root / "Library").mkdir(parents=True, exist_ok=True)
    (files_root / "Library" / "saved.pdf").write_bytes(b"x" * 10)
    db.upsert_resource(conn, {"path": "disk:/Library/saved.pdf",
                              "name": "saved.pdf", "type": "file", "size": 10})
    conn.execute(
        "INSERT INTO local(path,local_path,bytes,verify,downloaded_at,released) "
        "VALUES('disk:/Library/saved.pdf',?,10,'ok',1,0)",
        (str(files_root / "Library" / "saved.pdf"),))

    # Есть в облачной описи -- хеши сверятся.
    data = b"y" * 20
    (files_root / "Library" / "known.pdf").write_bytes(data)
    db.upsert_resource(conn, {
        "path": "disk:/Library/known.pdf", "name": "known.pdf", "type": "file",
        "size": len(data), "md5": hashlib.md5(data).hexdigest(),
        "sha256": hashlib.sha256(data).hexdigest()})

    # Незнакомое программе -- учтём без хешей.
    (files_root / "Manual").mkdir(parents=True, exist_ok=True)
    (files_root / "Manual" / "only-here.pdf").write_bytes(b"z" * 30)
    (files_root / "Manual" / "half.pdf.part").write_bytes(b"unfinished")

    survey = client.post("/api/mirror/survey", json={})
    assert survey.status_code == 200, survey.text[:200]
    info = survey.json()
    assert info["files"] == 2, info
    assert info["with_cloud_meta"] == 1, info

    resp = client.post("/api/mirror", json={})
    assert resp.status_code == 200, f"{resp.status_code} {resp.text[:300]}"
    job = wait_job(client, resp.json()["job"])
    assert job and job["state"] == "done", (
        f"mirror: состояние {job.get('state')}, сообщение {job.get('message')!r}")

    rows = {r["path"]: r["verify"] for r in
            conn.execute("SELECT path, verify FROM local")}
    assert rows["disk:/Library/known.pdf"] == "ok", rows
    assert rows["disk:/Manual/only-here.pdf"] == "unverified", rows
    # Ресурс для незнакомого файла создан -- дерево и итоги его увидят.
    r = conn.execute("SELECT name, size FROM resources WHERE path=?",
                     ("disk:/Manual/only-here.pdf",)).fetchone()
    assert r and r["name"] == "only-here.pdf" and r["size"] == 30, dict(r or {})
    # Недокачанное .part не берём.
    assert "disk:/Manual/half.pdf.part" not in rows, rows
    print("учёт зерцала: обзор, задача, хеши, незнакомые, .part")


def test_repair_deleted_probe() -> None:
    """Удалённое нами не должно выглядеть живым в интерфейсе.

    Исторический хвост: удаление не писало вердикт пробы, и к 18 октября
    427 файлов висели «доступными» после удаления из облака. Момент
    удаления чинит это теперь сам; repairs доворачивает то, что наживлено
    до правки, и должна быть идемпотентной.
    """
    from drydock import db

    conn = server.conn()
    conn.execute("INSERT INTO cloud_deleted(path,deleted_at,permanently,response) "
                 "VALUES('disk:/old.pdf',1,1,'ok')")
    conn.execute("INSERT INTO cloud_deleted(path,deleted_at,permanently,response) "
                 "VALUES('disk:/kept.pdf',1,1,'ok')")
    db.record_probe(conn, "disk:/old.pdf", "ok", 200, "h", "")
    db.record_probe(conn, "disk:/kept.pdf", "gone", 404, None, "уже было")
    n = server._repair_deleted_probe(conn)
    assert n == 1, n
    states = {r["path"]: r["state"] for r in
              conn.execute("SELECT path,state FROM probe WHERE path LIKE 'disk:/%.pdf'")}
    assert states["disk:/old.pdf"] == "gone", states
    assert states["disk:/kept.pdf"] == "gone", states
    assert server._repair_deleted_probe(conn) == 0, "повторный проход не должен ничего менять"
    print("repairs: своё удаление в пробе -- gone, повтор безопасен")


def test_adopt_endpoints(client: TestClient, tmp: Path) -> None:
    """Перенос из папки клиента: файл уходит из неё и из облака.

    Раньше брали жёсткой ссылкой -- файл оставался в папке клиента, а
    значит и в облаке. Теперь перенос: клиент Диска видит пропажу, а мы
    после сверки хеша удаляем облачную копию явно.
    """
    import hashlib

    from drydock import db

    src_dir = tmp / "client2" / "Library"
    src_dir.mkdir(parents=True)
    data = b"y" * 120
    src_file = src_dir / "moved.pdf"
    src_file.write_bytes(data)
    conn = server.conn()
    db.upsert_resource(conn, {"path": "disk:/Library/moved.pdf",
                              "name": "moved.pdf", "type": "file",
                              "size": len(data),
                              "md5": hashlib.md5(data).hexdigest(),
                              "sha256": hashlib.sha256(data).hexdigest()})

    survey = client.post("/api/adopt/survey",
                         json={"source": str(tmp / "client2")})
    assert survey.status_code == 200, survey.text[:200]
    assert survey.json()["files"] == 1, survey.json()

    resp = client.post("/api/adopt", json={"source": str(tmp / "client2")})
    assert resp.status_code == 200, f"{resp.status_code} {resp.text[:300]}"
    job = wait_job(client, resp.json()["job"])
    assert job and job["state"] == "done", (
        f"adopt: состояние {job.get('state')}, сообщение {job.get('message')!r}")

    # Перенос: источника больше нет, файл в зеркале, хеш сверен.
    assert not src_file.exists(), "файл остался в папке клиента -- это не перенос"
    dest = Path(server.scan.local_for("disk:/Library/moved.pdf",
                                      server.config.PATHS.files))
    assert dest.is_file() and dest.stat().st_size == len(data)
    row = conn.execute("SELECT verify FROM local WHERE path=?",
                       ("disk:/Library/moved.pdf",)).fetchone()
    assert row and row["verify"] == "ok", dict(row or {})
    # И облачная копия удалена после сверки.
    gone = conn.execute("SELECT COUNT(*) FROM cloud_deleted WHERE path=?",
                        ("disk:/Library/moved.pdf",)).fetchone()[0]
    assert gone == 1, "облачная копия не удалена после переноса"
    assert ("disk:/Library/moved.pdf", True) in FAKE.deleted, FAKE.deleted
    print("перенос из папки клиента: файл переехал, облако почищено")

    # ── прежние жёсткие ссылки доделываются тем же действием ────────
    # Их брали ссылкой: файл лежал и в папке клиента, и в зеркале, и в
    # облаке. Новый механизм обязан довести такие до конца.
    src2 = tmp / "client3" / "Library"
    src2.mkdir(parents=True)
    data2 = b"z" * 80
    linked_src = src2 / "linked.pdf"
    linked_src.write_bytes(data2)
    db.upsert_resource(conn, {"path": "disk:/Library/linked.pdf",
                              "name": "linked.pdf", "type": "file",
                              "size": len(data2),
                              "md5": hashlib.md5(data2).hexdigest(),
                              "sha256": hashlib.sha256(data2).hexdigest()})
    r1 = client.post("/api/adopt", json={"source": str(tmp / "client3"),
                                         "mode": "link", "delete_cloud": False})
    assert r1.status_code == 200, r1.text[:300]
    assert wait_job(client, r1.json()["job"])["state"] == "done"
    linked_dest = Path(server.scan.local_for("disk:/Library/linked.pdf",
                                             server.config.PATHS.files))
    assert linked_src.exists() and linked_dest.exists(), "ссылка не создана"
    assert os.stat(linked_src).st_ino == os.stat(linked_dest).st_ino, \
        "это не жёсткая ссылка"

    survey2 = client.post("/api/adopt/survey",
                          json={"source": str(tmp / "client3")}).json()
    assert survey2["linked"] == 1, survey2

    r2 = client.post("/api/adopt", json={"source": str(tmp / "client3")})
    assert r2.status_code == 200, r2.text[:300]
    job2 = wait_job(client, r2.json()["job"])
    assert job2["state"] == "done", job2
    # Запись из папки клиента убрана, данные остались в зеркале.
    assert not linked_src.exists(), "ссылка осталась в папке клиента"
    assert linked_dest.read_bytes() == data2
    gone2 = conn.execute("SELECT COUNT(*) FROM cloud_deleted WHERE path=?",
                         ("disk:/Library/linked.pdf",)).fetchone()[0]
    assert gone2 == 1, "облачная копия доделанной ссылки не удалена"
    print("жёсткие ссылки доделаны: папка клиента и облако очищены")


def test_assets_revalidate(client: TestClient) -> None:
    """Файлы интерфейса должны перепроверяться, а не браться из кэша вслепую.

    StaticFiles сам ставит только last-modified и etag, а без Cache-Control
    браузер применяет эвристическое кэширование: показывает свою копию, не
    спрашивая сервер. Окно приложения -- постоянный профиль Edge, и из-за
    этого исправленный app.js до него не доезжал: человек видел баг,
    который давно починен.
    """
    for name in ("/app.js", "/i18n.js", "/style.css", "/"):
        resp = client.get(name)
        assert resp.status_code == 200, f"{name} -> {resp.status_code}"
        cache = resp.headers.get("cache-control", "")
        assert "no-cache" in cache, f"{name}: Cache-Control = {cache!r}"
    print("файлы интерфейса отдаются с обязательной перепроверкой")


def test_assets_versioned(client: TestClient) -> None:
    """Адрес скрипта обязан меняться вместе с его содержимым.

    Это то, чего не хватало: заголовок Cache-Control -- всего лишь просьба
    к браузеру, а версия в адресе делает подмену старым файлом физически
    невозможной. В Tauri-приложениях то же самое даёт сборщик, который
    именует файлы хешем; здесь считаем отпечаток сами.
    """
    import re

    from drydock import server as sv

    html = client.get("/").text
    assert re.search(r'app\.js\?v=[0-9a-f]{6,}', html), html[:400]
    assert re.search(r'style\.css\?v=[0-9a-f]{6,}', html), html[:400]

    before = sv.assets_version()
    target = sv.WEB / "app.js"
    original = target.read_bytes()
    try:
        target.write_bytes(original + b"// marker\n")
        assert sv.assets_version() != before, "правка файла не изменила отпечаток"
    finally:
        target.write_bytes(original)
    assert sv.assets_version() == before, "отпечаток не вернулся после отката"

    # Страница и состояние должны называть одну и ту же версию -- по этому
    # сравнению открытое окно понимает, что пора перезагрузиться.
    assert client.get("/api/state").json()["assets_version"] in html
    print("версия в адресах скриптов меняется вместе с файлами")


FAKE = FakeDisk()


def main() -> int:
    # Принимает параллельность: проба запускается на своём, большем лимите.
    server._disk = lambda concurrency=None: FAKE
    with TestClient(server.app) as client:
        test_reads(client)
        test_assets_revalidate(client)
        test_assets_versioned(client)
        test_jobs_actually_run(client)
        test_no_silent_500(client)
        test_job_cancel(client)
        test_repair_deleted_probe()
        test_double_start_guard(client)
        test_partial_state(client)
        test_revived_counts_real_returns(client)
        test_local_sync(client)
        test_autopilot_toggle(client)
        test_host_stats(client)
        test_autopilot_round(client)
        test_next_step(client)
        test_hosts_endpoints(client)
        test_health_endpoint(client)
        test_account_in_state(client)
        test_job_state_vocabulary(client)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            test_settings_endpoints(client, Path(d))
            test_adopt_endpoints(client, Path(d))
            test_mirror_endpoints(client, Path(d))
    print("\nсервер: все проверки прошли")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
