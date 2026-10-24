"""Проверки того, чего не видно в логе, а стоит это всей описи.

Три сценария, и все три уже случались по-настоящему:

1. Обход облака (walk) падал от одного сетевого моргания -- getaddrinfo
   failed на 3050-м файле убил часовую работу. Теперь неудачная страница
   переспрашивается: проверяем, что обход её переживает и что отмена во
   время паузы ретрая его останавливает.

2. Прерванная опись начиналась с корня заново -- каждый обрыв стоил
   часов. Проверяем, что очередь папок сохраняется, что папка «в работе»
   в ней тоже есть (иначе теряется её хвост) и что после продолжения в
   базе есть всё.

3. Окно, закрывшееся через миллисекунды после запуска, -- это Edge,
   отдавший адрес уже запущенному окну нашего профиля. Гасить по нему
   живой сервер нельзя: проверяем таблицу решений лаунчера.
"""

from __future__ import annotations

try:  # pytest не нужен файлу для работы напрямую
    import pytest
except ImportError:  # pragma: no cover
    pytest = None

import asyncio
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(tempfile.mkdtemp(prefix="cr-res-"))
os.environ["DRYDOCK_ROOT"] = str(ROOT)
os.environ["DRYDOCK_SECRETS"] = str(ROOT / "secrets.bin")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

import drydock.yandex as yandex_mod
from drydock import config, db, desktop
from drydock import scan as scan_mod

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
from drydock.yandex import Disk


def tree_listings() -> dict:
    """Три папки по 60 файлов: счётчик «каждые 50» в описи срабатывает
    внутри папки, и отмена приходится на её середину."""

    def folder(name: str) -> dict:
        return {"path": f"disk:/{name}", "name": name, "type": "dir"}

    def file(path: str, name: str, size: int) -> dict:
        return {"path": f"{path}/{name}", "name": name, "type": "file",
                "size": size}

    listings: dict = {"disk:/": [folder("A"), folder("B"), folder("C"),
                                 file("disk:", "top.txt", 7)]}
    for name in ("A", "B", "C"):
        listings[f"disk:/{name}"] = [
            file(f"disk:/{name}", f"{i:02}.txt", 10 + i) for i in range(60)]
    return listings


def fake_disk(listings: dict) -> Disk:
    """Disk с картой папок вместо сети. Считает обращения к каждой папке."""
    disk = Disk("test-token-not-real")
    calls: dict[str, int] = {}

    async def listdir(path: str, *, offset: int = 0, limit: int = 500) -> dict:
        calls[path] = calls.get(path, 0) + 1
        items = listings.get(path, [])
        return {"type": "dir", "name": path.rsplit("/", 1)[-1], "path": path,
                "_embedded": {"total": len(items),
                              "items": items[offset:offset + limit]}}

    disk.listdir = listdir  # type: ignore[method-assign]
    disk._calls = calls  # type: ignore[attr-defined]
    return disk


def _paths(walker) -> list[str]:
    async def run():
        return [item.get("path", "") async for item in walker]
    return asyncio.run(run())


def _collect(walker, timeout: float) -> list[str]:
    """То же, но под asyncio.wait_for: если отмена не сработает, тест
    упадёт по таймауту, а не повиснет навсегда."""
    async def run():
        return [item.get("path", "") async for item in walker]
    return asyncio.run(asyncio.wait_for(run(), timeout))


def test_walk_survives_network_flake() -> None:
    """Сеть моргнула на папке -- обход обязан переспросить и идти дальше.

    Ровно этот сбой 16 октября убил часовую опись на 3050-м файле.
    """
    listings = tree_listings()
    disk = fake_disk(listings)
    original = disk.listdir  # type: ignore[attr-defined]
    state = {"failed": 0}

    async def flaky(path: str, *, offset: int = 0, limit: int = 500) -> dict:
        if path == "disk:/B" and state["failed"] < 2:
            state["failed"] += 1
            raise httpx.ConnectError(
                "[Errno 11001] getaddrinfo failed",
                request=httpx.Request("GET", "https://cloud-api.yandex.net"))
        return await original(path, offset=offset, limit=limit)  # type: ignore[attr-defined]

    disk.listdir = flaky  # type: ignore[method-assign]

    old = yandex_mod.WALK_RETRY_MIN
    yandex_mod.WALK_RETRY_MIN = 0.05  # тест не должен спать по-настоящему
    try:
        paths = _paths(disk.walk("disk:/"))
    finally:
        yandex_mod.WALK_RETRY_MIN = old

    assert state["failed"] == 2, state
    assert "disk:/B/59.txt" in paths, "папка после двух сетевых морганий не долистана"
    assert len(paths) == 1 + 4 + 3 * (1 + 60), len(paths)
    print("обход переживает сетевые морганья и продолжает: ок")


def test_walk_stops_on_cancel_during_retry() -> None:
    """Запросили отмену посреди паузы ретрая -- обход выходит, а не висит."""
    disk = Disk("test-token-not-real")

    async def down(path: str, *, offset: int = 0, limit: int = 500) -> dict:
        raise httpx.ConnectError("нет сети",
                                 request=httpx.Request("GET", "https://x"))

    disk.listdir = down  # type: ignore[method-assign]

    old = yandex_mod.WALK_RETRY_MIN
    yandex_mod.WALK_RETRY_MIN = 30.0  # без should_stop обход завис бы навсегда
    try:
        items = _collect(disk.walk("disk:/", should_stop=lambda: True), 5)
    finally:
        yandex_mod.WALK_RETRY_MIN = old
    assert items == [], items
    print("отмена во время паузы ретрая останавливает обход: ок")


def test_scan_checkpoint_and_resume() -> None:
    """Прерванная опись продолжается с места, и хвост прерванной папки цел."""
    listings = tree_listings()
    conn = db.connect(ROOT / "checkpoint.db")
    disk = fake_disk(listings)

    real_cancelled = db.job_cancelled
    state = {"n": 0}

    def cancel_from_first_check(conn_arg, job_id: int) -> bool:
        # «Стоп» нажимают на первой же проверке -- отмена посреди папки.
        state["n"] += 1
        return True

    db.job_cancelled = cancel_from_first_check  # type: ignore[assignment]
    try:
        scan_mod.CHECKPOINT_SECONDS = 0.0  # чекпоинт на каждый снимок очереди
        first = asyncio.run(scan_mod.scan(conn, disk, job_id=1))
    finally:
        db.job_cancelled = real_cancelled  # type: ignore[assignment]
        scan_mod.CHECKPOINT_SECONDS = 10.0

    saved = db.kv_get(conn, scan_mod.CHECKPOINT_KEY)
    assert saved and "disk:/C" in saved["stack"], saved
    assert "disk:/C/43.txt" in _db_paths(conn), "начало прерванной папки потеряно"
    assert "disk:/C/59.txt" not in _db_paths(conn), \
        "отмена должна была прийтись на середину папки"
    assert first["files"] < 181, first

    # Продолжение: то же облако, отмены больше нет.
    second = asyncio.run(scan_mod.scan(conn, disk, job_id=2))

    paths = _db_paths(conn)
    assert len(paths) == 181, f"ожидал 181 файл, получил {len(paths)}"
    assert "disk:/C/59.txt" in paths, "хвост прерванной папки не добрали"
    assert "disk:/A/59.txt" in paths and "disk:/B/00.txt" in paths
    assert db.kv_get(conn, scan_mod.CHECKPOINT_KEY) is None, \
        "завершённая опись обязана снять чекпоинт"
    # Корень не перечислялся заново, прерванная папка -- один раз, остальные по разу.
    calls = disk._calls
    assert calls["disk:/"] == 1, calls
    assert calls["disk:/C"] == 2, calls
    assert calls["disk:/A"] == 1 and calls["disk:/B"] == 1, calls
    assert second["files"] == 181 and second["dirs"] == 4, second
    print("опись продолжается с чекпоинта, хвост прерванной папки цел: ок")


def _db_paths(conn) -> set[str]:
    return {r["path"] for r in
            conn.execute("SELECT path FROM resources WHERE type='file'")}


def test_launcher_window_decision() -> None:
    """Мгновенно закрывшееся окно -- не всегда «пользователь закрыл»."""
    # Edge отдал адрес уже запущенному окну нашего профиля: сервер живой,
    # окно профиля живое -- гасить нельзя, надо ждать того окна.
    assert desktop.decide_after_window_closed(
        0.2, window_alive=True, server_ours=True) == "adopt"
    # То же окно, но закрылось через десять минут -- это настоящий выход.
    assert desktop.decide_after_window_closed(
        600, window_alive=True, server_ours=True) == "shutdown"
    # Мгновенно закрылось, а окна профиля нет -- закрыли по-настоящему.
    assert desktop.decide_after_window_closed(
        0.2, window_alive=False, server_ours=True) == "shutdown"
    # Сервер и так мёртв -- чинить нечего.
    assert desktop.decide_after_window_closed(
        0.2, window_alive=True, server_ours=False) == "leave"
    print("решение лаунчера про мгновенно закрывшееся окно: ок")


def test_preview_name_within_component_limit() -> None:
    """Имя превью с '.jpg' не имеет права вылезать за 255 на компонент.

    Настоящее имя из лога: файл облака ровно 255 символов, плюс '.jpg'
    -- 259, и open() падал с Errno 22, роняя порцию после часа описи.
    """
    long_name = "я" * 250 + " Книга.pdf"
    dest = scan_mod.preview_dest(f"disk:/Folder/{long_name}")
    assert len(dest.name) <= 255, len(dest.name)
    assert dest.name.endswith(".jpg"), dest.name
    assert dest == scan_mod.preview_dest(f"disk:/Folder/{long_name}"), \
        "имя должно быть одним и тем же между запусками"
    print("имя превью укладывается в лимит компонента: ок")


def test_harvest_survives_single_bad_file() -> None:
    """Одна битая превью не роняет порцию.

    17 октября OSError Errno 22 на длинном имени вылетел из gather и
    убил задачу: 24 577 файлов в описи остались без превью-доработки.
    """
    conn = db.connect(ROOT / "preview.db")
    for path, url in (("disk:/A/long.pdf", "https://x/a"),
                      ("disk:/B/ok.pdf", "https://x/b")):
        db.upsert_resource(conn, {"path": path, "name": path.rsplit("/", 1)[-1],
                                  "type": "file", "size": 1, "preview": url})
    disk = Disk("test-token-not-real")

    async def fetch_preview(url: str, dest: Path) -> tuple[str, int | None]:
        if url.endswith("/a"):
            # Ровно то, что случилось: open() не принял имя.
            raise OSError("[Errno 22] Invalid argument: " + str(dest))
        return "ok", 200

    disk.fetch_preview = fetch_preview  # type: ignore[method-assign]

    counters = asyncio.run(scan_mod.harvest_previews(conn, disk))
    assert counters == {"ok": 1, "missing": 0, "error": 1, "total": 2}, counters
    states = {r["path"]: r["preview_state"] for r in
              conn.execute("SELECT path, preview_state FROM meta_saved")}
    assert states["disk:/B/ok.pdf"] == "ok", states
    assert "Errno 22" in (states["disk:/A/long.pdf"] or ""), states
    print("порция превью переживает один битый файл: ок")


class _Stream:
    """Подставной поток выгрузки: отдаёт куски и обрывается на нужном."""

    def __init__(self, chunks, fail_after=None, status: int = 206) -> None:
        self.chunks = chunks
        self.fail_after = fail_after
        self.status_code = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def aiter_bytes(self, _size: int):
        for i, chunk in enumerate(self.chunks):
            if self.fail_after is not None and i >= self.fail_after:
                raise httpx.RemoteProtocolError(
                    "peer closed connection without sending complete message body")
            yield chunk

    async def aread(self) -> bytes:
        return b""


class _FlakyDisk:
    """Диск, у которого передача рвётся по сценарию. Помнит смещения."""

    def __init__(self, script: list[tuple[list[bytes], int | None]]) -> None:
        self.script = script
        self.starts: list[int] = []

    async def open_stream(self, path: str, *, start: int = 0):
        # Настоящий Disk.open_stream -- корутина: она сперва просит
        # свежую ссылку у API, и только потом отдаёт поток.
        self.starts.append(start)
        item = self.script.pop(0)
        chunks, fail_after = item[0], item[1]
        status = item[2] if len(item) > 2 else 206
        return _Stream(chunks, fail_after, status)


def test_download_retries_and_resumes() -> None:
    """Обрыв передачи не теряет скачанное: повтор идёт с места обрыва.

    18 октября хранилище рвало передачу 67 раз за сеанс, и каждый обрыв
    означал «файл не скачался» -- до ручного перезапуска задачи. Теперь
    попытка повторяется внутри задачи, а .part копит прогресс.
    """
    from drydock import download

    part = Path(tempfile.mkdtemp(prefix="cr-dl-")) / "x.part"
    disk = _FlakyDisk([([b"a" * 100, b"b" * 100], 1), ([b"b" * 100, b"c" * 100], None)])
    written, _holes = asyncio.run(
        download._straight(disk, "disk:/x", part, 300))
    assert written == 300, written
    assert part.stat().st_size == 300, part.stat().st_size
    # Второй заход начался с 100 байт, а не с нуля.
    assert disk.starts == [0, 100], disk.starts
    assert part.read_bytes() == b"a" * 100 + b"b" * 100 + b"c" * 100
    print("выгрузка: обрыв на середине, повтор с места, файл цел: ок")


def test_download_gives_up_but_keeps_part() -> None:
    """Обрез на одном смещении: сдаёмся быстро, .part сохраняет прогресс.

    Хранилище рвёт на одном и том же абсолютном байте при любом старте
    (проверено: 51910 из 1244840). Повтор туда не пройдёт, и тратить на
    него пять попыток по сорок секунд незачем -- но скачанное до обреза
    остаётся в .part.
    """
    from drydock import download

    part = Path(tempfile.mkdtemp(prefix="cr-dl2-")) / "y.part"
    part.write_bytes(b"a" * 50)  # уже что-то скачано прошлым заходом
    # Оба захода не отдают ни байта -- прогресса нет.
    disk = _FlakyDisk([([], 0)] * 4)
    try:
        asyncio.run(download._straight(disk, "disk:/y", part, 1000))
    except OSError as exc:
        assert "обрезан" in str(exc), exc
    else:
        raise AssertionError("должно было сдаться после двух заходов без прогресса")
    assert len(disk.starts) == 2, disk.starts
    assert part.exists() and part.stat().st_size == 50, "прогресс не сохранён"
    print("выгрузка: обрез на одном смещении -- сдаёмся быстро, .part цел: ок")


def test_download_survives_server_ignoring_range() -> None:
    """200 в ответ на докачку не стирает уже скачанное.

    Хранилище иногда игнорирует Range и шлёт файл с начала. Раньше в
    этом случае .part обрезался в ноль: если поток умирал на первом
    байте, терялось всё накопленное (18 октября 51910 байт стали нулём).
    Теперь лишний кусок просто пропускается в потоке.
    """
    from drydock import download

    part = Path(tempfile.mkdtemp(prefix="cr-dl3-")) / "z.part"
    part.write_bytes(b"a" * 100)  # уже скачано
    disk = _FlakyDisk([([b"a" * 100, b"b" * 100, b"c" * 100], None, 200)])
    written, _holes = asyncio.run(
        download._straight(disk, "disk:/z", part, 300))
    assert written == 300, written
    assert part.read_bytes() == b"a" * 100 + b"b" * 100 + b"c" * 100
    assert disk.starts == [100], disk.starts
    print("выгрузка: сервер проигнорировал Range, .part не стёрт: ок")


class _Resp:
    """Подставной ответ хранилища для пробы."""

    def __init__(self, status: int, headers: dict | None = None,
                 chunks: tuple = (), fail: bool = False) -> None:
        self.status_code = status
        self.headers = headers or {}
        self.chunks = chunks
        self.fail = fail
        self.is_redirect = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def aiter_bytes(self, _size: int):
        for chunk in self.chunks:
            if self.fail:
                raise httpx.RemoteProtocolError(
                    "peer closed connection without sending complete message body")
            yield chunk

    async def aread(self) -> bytes:
        return b""


class _Storage:
    """Клиент хранилища: первый байт отдаётся, хвост -- по сценарию."""

    def __init__(self, *, tail_ok: bool) -> None:
        self.tail_ok = tail_ok

    def stream(self, _method: str, _url: str, *, headers=None, **_kw):
        rng = (headers or {}).get("Range", "")
        if rng == "bytes=0-0":
            # Файл крупнее порога проверки хвоста (PROBE_TAIL_MIN).
            return _Resp(206, {"content-range": "bytes 0-0/200000"},
                         chunks=(b"x",))
        return _Resp(206, {}, chunks=(b"y",), fail=not self.tail_ok)


def test_probe_catches_truncated_files() -> None:
    """Проба не должна называть доступным файл с мёртвым концом.

    18 октября «Конспект лекций по ТАУ.pdf» проходил пробу (первый байт
    отдавался), а выгрузка умирала на 51910 из 1244840. Теперь проба
    проверяет и последний байт -- один запрос, зато «доступно» значит
    «скачивается».
    """
    from drydock import config
    from drydock.yandex import Disk

    assert config.PROBE_TAIL, "проверка хвоста выключена в конфиге"

    async def check(tail_ok: bool):
        disk = Disk("test-token-not-real")
        disk._client = _Storage(tail_ok=tail_ok)  # type: ignore[assignment]
        try:
            return await disk._probe_once("https://storage/x")
        finally:
            pass

    status, _location, body = asyncio.run(check(tail_ok=False))
    assert status == 500 and "обрезан" in body, (status, body)
    status, _location, body = asyncio.run(check(tail_ok=True))
    assert status == 206 and not body, (status, body)
    print("проба: обрезанный конец виден, живой файл проходит: ок")


def test_download_skips_present_and_records_verdicts() -> None:
    """Уже лежащее не качаем; провал выгрузки -- наблюдение о файле.

    18 октября задача #46 жгла время на 140 файлах: часть уже лежала
    локально как 'unverified' (перенесены вручную), часть облако уже не
    отдавало. Теперь такие не попадают в очередь, а «нет ссылки» и
    «обрезан» сразу пишутся в пробу.
    """
    import os
    import tempfile

    from drydock import config, db, download

    root = Path(tempfile.mkdtemp(prefix="cr-dl4-"))
    os.environ["DRYDOCK_ROOT"] = str(root)
    config.PATHS.ensure()
    conn = db.connect(config.PATHS.db)

    # 1. Лежит на диске как 'unverified' -- download_one пропускает.
    db.upsert_resource(conn, {"path": "disk:/have.pdf", "name": "have.pdf",
                              "type": "file", "size": 4})
    target = config.PATHS.files / "have.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"data")
    conn.execute("INSERT INTO local(path,local_path,bytes,verify,downloaded_at,released) "
                 "VALUES('disk:/have.pdf',?,4,'unverified',1,0)", (str(target),))

    plan = download.plan(conn, ["disk:/have.pdf"])
    assert plan["already"] == 1 and plan["available"] == 0, plan

    class _NoDisk:
        async def open_stream(self, *_a, **_k):
            raise OSError("нет ссылки на disk:/have.pdf: HTTP 404")

    res = asyncio.run(download.download_one(conn, _NoDisk(), "disk:/have.pdf"))
    assert res["state"] == "skipped", res

    # 2. Файла в облаке нет -- «нет ссылки» пишется как gone.
    db.upsert_resource(conn, {"path": "disk:/lost.pdf", "name": "lost.pdf",
                              "type": "file", "size": 10})
    res = asyncio.run(download.download_one(conn, _NoDisk(), "disk:/lost.pdf"))
    assert res["state"] == "failed", res
    probe = conn.execute("SELECT state FROM probe WHERE path='disk:/lost.pdf'").fetchone()
    assert probe and probe["state"] == "gone", dict(probe or {})

    # 3. Обрез на машине хранилища -- unavailable, а не «ошибка и всё».
    db.upsert_resource(conn, {"path": "disk:/cut.pdf", "name": "cut.pdf",
                              "type": "file", "size": 100})

    class _CutDisk:
        async def open_stream(self, *_a, **_k):
            raise OSError("хранилище отдаёт только первые 0 из 100 байт -- "
                          "файл обрезан на машине хранилища")

    res = asyncio.run(download.download_one(conn, _CutDisk(), "disk:/cut.pdf"))
    assert res["state"] == "failed", res
    probe = conn.execute("SELECT state FROM probe WHERE path='disk:/cut.pdf'").fetchone()
    assert probe and probe["state"] == "unavailable", dict(probe or {})
    print("выгрузка: уже лежащее пропускается, провалы пишутся в пробу: ок")


def main() -> int:
    test_walk_survives_network_flake()
    test_walk_stops_on_cancel_during_retry()
    test_scan_checkpoint_and_resume()
    test_launcher_window_decision()
    test_preview_name_within_component_limit()
    test_harvest_survives_single_bad_file()
    test_download_retries_and_resumes()
    test_download_gives_up_but_keeps_part()
    test_download_survives_server_ignoring_range()
    test_probe_catches_truncated_files()
    test_download_skips_present_and_records_verdicts()
    print("\nвсе проверки прошли")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
