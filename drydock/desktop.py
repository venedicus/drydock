"""Запуск как настольного приложения: двойной клик -- окно -- закрыл -- всё.

Окно -- это Edge в режиме `--app`: без адресной строки, вкладок и кнопок,
со своей записью на панели задач. Почему не Tauri, как в TagConveyor, и не
pywebview: обе требуют отдельного тулчейна (Rust с npm или .NET с
pythonnet), а здесь надо, чтобы работало сегодня и не ломалось от версии
зависимости. WebView2 и так лежит в каждой Windows 11 -- берём его напрямую.

Ключевая деталь: отдельный профиль браузера (`--user-data-dir`). Без него
Edge отдаёт адрес уже запущенному процессу и наш Popen завершается сразу,
то есть "дождаться закрытия окна" не работает. Со своим профилем процесс
наш, и его закрытие честно означает "пользователь закрыл приложение".

Повторный запуск не поднимает второй сервер: если порт уже отвечает, просто
открываем ещё одно окно к тому, что работает.

Тонкость, стоявшая приложения 16 октября: Edge с нашим профилем, получив
команду открыть URL, отдаёт адрес УЖЕ запущенному окну того же профиля и
тут же выходит -- Popen.wait() возвращается за миллисекунды. Раньше лаунчер
почитал это «пользователь закрыл приложение» и гасил свой же свежий сервер.
Теперь мгновенное закрытие окна проверяется: если живое окно нашего профиля
есть, сервер не трогается -- лончер берёт на себя ожидание того окна.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILE = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Drydock" / "window"
LOG = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Drydock" / "launch.log"

BROWSERS = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
)

# Окно, закрывшееся быстрее, чем через столько секунд после запуска, --
# почти наверняка не человек: Edge ещё выбирает, в какое окно открывать.
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


def profile_browser_alive() -> bool:
    """Живёт ли хоть одно окно браузера с нашим профилем.

    Признак -- командная строка процесса: --user-data-dir=<профиль> есть
    только у наших окон (и их дочерних процессов). Именно этим профилем
    Edge и «отдаёт адрес» уже запущенному окну, выходя мгновенно.
    """
    marker = str(PROFILE).lower()
    for exe in ("msedge.exe", "chrome.exe", "brave.exe"):
        try:
            out = subprocess.run(  # noqa: PLW1510 - разбираем вывод сами
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 (f"Get-CimInstance Win32_Process -Filter \"Name='{exe}'\" "
                  "| Select-Object -ExpandProperty CommandLine")],
                capture_output=True, text=True, timeout=20,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError):
            return False
        if marker in (out.stdout or "").lower():
            return True
    return False


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
    for path in BROWSERS:
        if Path(path).is_file():
            return Path(path)
    return None


def open_window(port: int, *, separate_profile: bool = True) -> subprocess.Popen | None:
    url = f"http://127.0.0.1:{port}/"
    exe = find_browser()
    if exe is None:
        import webbrowser
        log("браузер на основе Chromium не найден -- открываю обычной вкладкой")
        webbrowser.open(url)
        return None
    args = [str(exe), f"--app={url}", "--window-size=1460,920",
            "--no-first-run", "--no-default-browser-check"]
    if separate_profile:
        PROFILE.mkdir(parents=True, exist_ok=True)
        args.append(f"--user-data-dir={PROFILE}")
    log(f"окно: {exe.name}")
    return subprocess.Popen(args, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


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
        log(f"порт {port} занят чужой программой")
        print(f"Порт {port} занят другой программой. Укажи другой: --port", file=sys.stderr)
        return 2

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
