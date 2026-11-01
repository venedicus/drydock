"""Запуск как настольного приложения: двойной клик -- окно -- закрыл -- всё.

Окно -- это Chromium-браузер в режиме `--app`: без адресной строки,
вкладок и кнопок, со своей записью на панели задач. Почему не Tauri, как в
TagConveyor, и не pywebview: обе требуют отдельного тулчейна (Rust с npm
или .NET с pythonnet), а здесь надо, чтобы работало сегодня и не ломалось
от версии зависимости. Chromium есть почти везде: Edge на Windows, Chrome,
Chromium, Brave -- на macOS и Linux; если ни одного нет, открываем обычную
вкладку системного браузера.

Ключевая деталь: отдельный профиль браузера (`--user-data-dir`). Без него
браузер отдаёт адрес уже запущенному процессу и наш Popen завершается
сразу, то есть "дождаться закрытия окна" не работает. Со своим профилем
процесс наш, и его закрытие честно означает "пользователь закрыл
приложение".

Повторный запуск не поднимает второй сервер: если порт уже отвечает, просто
открываем ещё одно окно к тому, что работает.

Тонкость, стоявшая приложения 16 октября: браузер с нашим профилем, получив
команду открыть URL, отдаёт адрес УЖЕ запущенному окну того же профиля и
тут же выходит -- Popen.wait() возвращается за миллисекунды. Раньше лаунчер
почитал это «пользователь закрыл приложение» и гасил свой же свежий сервер.
Теперь мгновенное закрытие окна проверяется: если живое окно нашего профиля
есть, сервер не трогается -- лончер берёт на себя ожидание того окна.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

from . import hostos

ROOT = Path(__file__).resolve().parent.parent
PROFILE = hostos.app_dir() / "window"
LOG = hostos.app_dir() / "launch.log"

# Окно, закрывшееся быстрее, чем через столько секунд после запуска, --
# почти наверняка не человек: браузер ещё выбирает, в какое окно открывать.
WINDOW_GRACE = 5.0


def log(message: str) -> None:
    """Пишем в файл: под pythonw консоли нет, и упавший запуск иначе немой."""
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {message}\n")
    except OSError:
        pass


def port_busy(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.4)
        return sock.connect_ex((host, port)) == 0


def ours(port: int, tries: int = 3) -> bool:
    """На порту именно мы, а не чужая программа.

    Сервер с зажат событийным циклом (долгий ретрай к облаку) отвечает
    /api/state дольше двух секунд -- и один медленный ответ однажды
    сделал живое приложение «чужим»: повторный запуск отказался
    поднимать окно. Поэтому спрашиваем три раза, прежде чем сдаться.
    """
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/state", timeout=2) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, OSError, ValueError):
            pass
        if attempt + 1 < tries:
            time.sleep(1.0)
    return False


def next_port(start: int, span: int = 20) -> int | None:
    """Первый порт от start, который свободен или занят нашим же сервером.

    Нужен, когда порт по умолчанию держит чужая программа: подниматься на
    случайном порту из чужого диапазона хуже, чем не подняться вовсе, а
    молча умирать -- хуже всего.
    """
    for port in range(start, start + span):
        if not port_busy(port) or ours(port):
            return port
    return None


def profile_browser_alive() -> bool:
    """Живёт ли хоть одно окно браузера с нашим профилем.

    Признак -- командная строка процесса: --user-data-dir=<профиль> есть
    только у наших окон (и их дочерних процессов). Именно этим профилем
    браузер и «отдаёт адрес» уже запущенному окну, выходя мгновенно.
    """
    return hostos.browser_processes(str(PROFILE))


def decide_after_window_closed(elapsed: float, *, window_alive: bool,
                               server_ours: bool) -> str:
    """Что делать, когда окно закрылось.

    "shutdown" -- окно действительно закрыли, гасим сервер за собой;
    "adopt"    -- окно отдало адрес другому окну нашего профиля: сервер
                  оставляем работать и ждём закрытия ТОГО окна;
    "leave"    -- сервер и так мёртв, чинить нечего.
    """
    if not server_ours:
        return "leave"
    if elapsed < WINDOW_GRACE and window_alive:
        return "adopt"
    return "shutdown"


def find_browser() -> Path | None:
    for raw in hostos.browser_candidates():
        if Path(raw).is_file():
            return Path(raw)
    return None


def open_window(port: int, *, separate_profile: bool = True) -> subprocess.Popen | None:
    url = f"http://127.0.0.1:{port}/"
    exe = find_browser()
    if exe is None:
        import webbrowser
        log("Chromium-браузер не найден -- открываю обычной вкладкой")
        webbrowser.open(url)
        return None
    args = [str(exe), f"--app={url}", "--window-size=1460,920",
            "--no-first-run", "--no-default-browser-check"]
    if separate_profile:
        PROFILE.mkdir(parents=True, exist_ok=True)
        args.append(f"--user-data-dir={PROFILE}")
    log(f"окно: {exe.name}")
    return subprocess.Popen(args, creationflags=hostos.no_window(),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _serve(port: int):
    """Сервер в этом же процессе, в фоновом потоке."""
    import uvicorn

    from . import server as server_mod
    server_mod.SERVE_PORT = port
    config = uvicorn.Config(server_mod.app, host="127.0.0.1", port=port,
                            log_level="warning")
    srv = uvicorn.Server(config)
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    return srv, thread


def wait_ready(port: int, timeout: float = 30) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if ours(port):
            return True
        time.sleep(0.25)
    return False


def run(port: int = 8765, *, keep_running: bool = False) -> int:
    """Поднять приложение и держать его, пока открыто окно."""
    log(f"запуск, порт {port}")
    try:
        return _run(port, keep_running=keep_running)
    except BaseException:
        # pythonw не имеет консоли: без этой записи падение лаунчера --
        # а с ним и сервера, и всех идущих задач -- протекает молча,
        # в логе не остаётся даже намёка на смерть процесса.
        log("лаунчер упал:\n" + traceback.format_exc())
        raise
    finally:
        # Ровно эта строка отсутствовала, когда приложение «мигнуло» и
        # умерло: её тишина в launch.log и означает необъяснимую смерть.
        log("лаунчер завершён")


def _run(port: int, *, keep_running: bool) -> int:
    if port_busy(port):
        if ours(port):
            log("уже работает -- открываю ещё одно окно")
            open_window(port)
            return 0

        # Порт занят чужой программой. Раньше здесь был return 2 с print в
        # stderr, но окна ещё нет, а из-под pythonw stderr никто не видит:
        # запуск выглядел как падение -- ни окна, ни сообщения, в логе одна
        # строка. Берём ближайший свободный порт: для человека, который
        # просто запустил программу, ничего не меняется.
        alt = next_port(port + 1)
        if alt is None:
            log(f"порт {port} занят чужой программой, свободного рядом нет")
            print(f"Порт {port} занят другой программой. Укажи другой: --port",
                  file=sys.stderr)
            return 2
        if ours(alt):
            log(f"порт {port} занят чужой программой -- открываю окно к {alt}")
            open_window(alt)
            return 0
        log(f"порт {port} занят чужой программой -- беру {alt}")
        port = alt

    srv, thread = _serve(port)
    if not wait_ready(port):
        log("сервер не поднялся за отведённое время")
        print("Сервер не запустился, смотри " + str(LOG), file=sys.stderr)
        return 1
    log("сервер поднялся")

    window = open_window(port)
    if window is None or keep_running:
        # Нечего ждать (открыли обычной вкладкой) либо попросили не
        # закрываться вместе с окном -- держим сервер до Ctrl+C.
        try:
            while thread.is_alive():
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        return 0

    started = time.monotonic()
    try:
        window.wait()
    except KeyboardInterrupt:
        window.terminate()
    elapsed = time.monotonic() - started

    # Окно закрылось мгновенно -- это почти всегда Edge, отдавший адрес
    # уже запущенному окну того же профиля (прошлый лончер умер, окно
    # осталось висеть). Гасить по такому закрытию живой сервер нельзя:
    # приложение «мигнуло» и умерло при повторном запуске. Проверяем,
    # и если окно профиля живо -- берём его под ответственность и ждём.
    decision = "shutdown"
    if elapsed < WINDOW_GRACE:
        decision = decide_after_window_closed(
            elapsed, window_alive=profile_browser_alive(),
            server_ours=ours(port))
    if decision == "adopt":
        log("окно отдало адрес существующему окну нашего профиля -- "
            "сервер оставлен работать, жду закрытия того окна")
        while profile_browser_alive() and ours(port):
            time.sleep(3.0)
    log("окно закрыто -- останавливаю сервер")
    srv.should_exit = True
    thread.join(timeout=10)
    return 0
