"""Где мы запущены и чем пользуется система.

Программа выросла на Windows и долго могла позволить себе `%LOCALAPPDATA%`,
`explorer` и `\\?\\` напрямую. Теперь те же функции нужны на macOS и Linux,
поэтому все различия собраны здесь, в одном месте: остальной код спрашивает
«дай каталог для настроек» и «открой папку», а не выясняет, какая нынче ОС.

Правило: здесь нет ничего про Яндекс и про спасение файлов -- только про то,
чем системы отличаются друг от друга.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"
IS_POSIX = not IS_WINDOWS

# Имя приложения в системных каталогах. Менять нельзя: по нему лежат уже
# выбранные настройки и сохранённый токен.
APP_NAME = "Drydock"
# Прежнее имя проекта: настройки и токен, сохранённые до переименования,
# должны остаться доступными.
LEGACY_NAME = "CloudRecovery"


def _env_path(name: str) -> Path | None:
    value = os.environ.get(name)
    return Path(value) if value else None


def app_dir() -> Path:
    """Каталог приложения для настроек, токена, профиля окна и лога.

    Windows -- `%LOCALAPPDATA%\\Drydock`; macOS -- `~/Library/Application
    Support/Drydock`; остальные -- `$XDG_CONFIG_HOME/Drydock` или
    `~/.config/Drydock`. Именно эти места принято чистить и бэкапить, и
    именно их не видно в репозитории.
    """
    if IS_WINDOWS:
        base = _env_path("LOCALAPPDATA") or Path.home()
        return base / APP_NAME
    if IS_MACOS:
        return Path.home() / "Library" / "Application Support" / APP_NAME
    base = _env_path("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return base / APP_NAME


def legacy_app_dir() -> Path:
    """Где приложение хранило данные под прежним именем."""
    return app_dir().parent / LEGACY_NAME


def no_window() -> int:
    """Флаги запуска дочернего процесса без окна консоли.

    На Windows это CREATE_NO_WINDOW; на остальных систем такого понятия нет,
    и Popen ждёт ноль -- ненулевое значение там просто не поддерживается.
    """
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WINDOWS else 0


def _first_existing(paths: list[str]) -> Path | None:
    for raw in paths:
        if raw and Path(raw).is_file():
            return Path(raw)
    return None


def file_manager() -> list[str] | None:
    """Команда, открывающая папку (и, если умеет, выделяющая файл).

    Возвращает программу без аргументов: `open` на macOS умеет `-R`,
    проводник -- `/select,`, `xdg-open` умеет только открыть папку.
    """
    if IS_WINDOWS:
        return ["explorer"]
    if IS_MACOS:
        return ["open"]
    for name in ("xdg-open", "gio"):
        if shutil.which(name):
            return [shutil.which(name) or name]
    return None


def reveal(path: Path) -> None:
    """Показать путь в файловом менеджере. Бросает OSError, если не вышло."""
    target = Path(path)
    manager = file_manager()
    if manager is None:
        raise OSError("не найден файловый менеджер (xdg-open или gio)")
    name = Path(manager[0]).name
    if name == "explorer":
        args = (["explorer", str(target)] if target.is_dir()
                else ["explorer", "/select,", str(target)])
    elif name == "open":
        args = (["open", str(target)] if target.is_dir()
                else ["open", "-R", str(target)])
    elif name == "gio":
        # gio open -- то же, что xdg-open; отдельной команды «показать» нет.
        args = ["gio", "open", str(target if target.is_dir() else target.parent)]
    else:
        # xdg-open не умеет выделять файл: открываем папку, где он лежит.
        args = ["xdg-open", str(target if target.is_dir() else target.parent)]
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def browser_candidates() -> list[str]:
    """Chromium-браузеры, которые умеют `--app` (окно без адресной строки).

    Пути перечислены явно, потому что на macOS программа лежит внутри
    .app-пакета, а в PATH её нет; на Linux наоборот -- ищем по имени.
    """
    if IS_WINDOWS:
        return [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        ]
    if IS_MACOS:
        return [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
    found: list[str] = []
    for name in ("google-chrome", "google-chrome-stable", "chromium",
                 "chromium-browser", "microsoft-edge", "brave-browser"):
        path = shutil.which(name)
        if path:
            found.append(path)
    return found


def browser_processes(marker: str) -> bool:
    """Есть ли живой процесс, в командной строке которого есть marker.

    Нужно лаунчеру: браузер с нашим профилем может отдать адрес уже
    открытому окну и выйти, и по одному лишь коду возврата не понять,
    закрыл человек окно или оно осталось жить.

    Windows спрашивает WMI (другого способа нет), POSIX -- `ps`: на macOS
    и в Linux он показывает полную командную строку для своих процессов.
    """
    if IS_WINDOWS:
        for exe in ("msedge.exe", "chrome.exe", "brave.exe"):
            try:
                out = subprocess.run(
                    ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                     (f"Get-CimInstance Win32_Process -Filter \"Name='{exe}'\" "
                      "| Select-Object -ExpandProperty CommandLine")],
                    capture_output=True, text=True, timeout=20, check=False,
                    creationflags=no_window())
            except (OSError, subprocess.SubprocessError):
                return False
            if marker.lower() in (out.stdout or "").lower():
                return True
        return False
    try:
        out = subprocess.run(["ps", "-axo", "command"], check=False,
                             capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return False
    return marker in (out.stdout or "")
