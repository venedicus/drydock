"""Ярлыки Drydock -- разовая настройка рабочего места.

    Windows:  .venv\\Scripts\\python tools/make_shortcut.py [--start-menu] [--remove]
    Linux:    .venv/bin/python tools/make_shortcut.py [--remove]
    macOS:    .venv/bin/python tools/make_shortcut.py [--remove]

Windows: ярлык указывает прямо на pythonw.exe, а не на .bat: .bat на
мгновение показывает окно консоли, и приложение выглядит самоделкой.
pythonw консоли не создаёт вовсе.

Linux: запись в меню (`~/.local/share/applications/drydock.desktop`) и,
если есть рабочий стол, копия туда же.

macOS: `~/Applications/Drydock.command` -- двойной клик из Finder.
Настоящий .app собирается только из готовой сборки (tools/build_exe.py).

Права администратора не нужны: всё делается для текущего пользователя.
"""

from __future__ import annotations

import argparse
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"

if IS_WINDOWS:
    PYTHONW = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
    ICON = ROOT / "assets" / "drydock.ico"
    NAME = "Drydock.lnk"
else:
    PYTHONW = ROOT / ".venv" / "bin" / "python"
    PYTHON = PYTHONW
    ICON = ROOT / "assets" / "drydock.png"
    NAME = "drydock.desktop" if not IS_MACOS else "Drydock.command"

PS_CREATE = r"""
$sh = New-Object -ComObject WScript.Shell
$lnk = $sh.CreateShortcut('{dest}')
$lnk.TargetPath = '{target}'
$lnk.Arguments = '{args}'
$lnk.WorkingDirectory = '{cwd}'
$lnk.IconLocation = '{icon}'
$lnk.Description = 'Drydock -- спасение коллекции с Яндекс.Диска'
$lnk.WindowStyle = 1
$lnk.Save()
"""

DESKTOP_ENTRY = """[Desktop Entry]
Type=Application
Version=1.0
Name=Drydock
Comment=Спасение коллекции с Яндекс.Диска
Exec={python} -m drydock.cli app
Path={cwd}
Icon={icon}
Terminal=false
Categories=Utility;FileTools;
StartupWMClass=Drydock
"""

MAC_COMMAND = """#!/bin/sh
# Запуск Drydock из Finder. Окно терминала закроется вместе с приложением.
cd "{cwd}" || exit 1
exec "{python}" -m drydock.cli app "$@"
"""


def _ps(script: str) -> None:
    proc = subprocess.run(  # noqa: PLW1510 - код возврата проверяем ниже
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise OSError(proc.stdout + proc.stderr)


def _folders(start_menu: bool) -> list[Path]:
    if not IS_WINDOWS:
        if IS_MACOS:
            return [p for p in (Path.home() / "Applications",) if p.is_dir()]
        apps = Path.home() / ".local" / "share" / "applications"
        apps.mkdir(parents=True, exist_ok=True)
        out = [apps]
        desktop = Path.home() / "Desktop"
        if desktop.is_dir():
            out.append(desktop)
        return out
    out = [Path.home() / "Desktop"]
    # OneDrive переносит рабочий стол к себе -- кладём туда, где он реально есть.
    onedrive = Path.home() / "OneDrive" / "Desktop"
    if onedrive.is_dir():
        out = [onedrive]
    if start_menu:
        out.append(Path.home() / "AppData" / "Roaming" / "Microsoft"
                   / "Windows" / "Start Menu" / "Programs")
    return [p for p in out if p.is_dir()]


def _write_executable(dest: Path, text: str) -> None:
    dest.write_text(text, encoding="utf-8")
    dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def create(start_menu: bool) -> int:
    if not PYTHONW.is_file():
        print(f"Нет {PYTHONW}. Сначала: uv venv && uv pip install -e .", file=sys.stderr)
        return 1
    if not ICON.is_file():
        print("Иконки нет, делаю...")
        subprocess.run([sys.executable, str(ROOT / "tools" / "make_icon.py")], check=True)
    made = 0
    for folder in _folders(start_menu):
        dest = folder / NAME
        if IS_WINDOWS:
            _ps(PS_CREATE.format(
                dest=dest, target=PYTHONW, args="-m drydock.cli app",
                cwd=ROOT, icon=ICON))
        elif IS_MACOS:
            _write_executable(dest, MAC_COMMAND.format(cwd=ROOT, python=PYTHON))
        else:
            _write_executable(dest, DESKTOP_ENTRY.format(
                python=PYTHON, cwd=ROOT, icon=ICON))
        print(f"Ярлык: {dest}")
        made += 1
    if not made:
        print("Не нашёл, куда положить ярлык.", file=sys.stderr)
        return 1
    return 0


def remove(start_menu: bool) -> int:
    for folder in _folders(start_menu):
        dest = folder / NAME
        if dest.is_file():
            dest.unlink()
            print(f"Убрано: {dest}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Ярлыки Drydock")
    ap.add_argument("--start-menu", action="store_true", help="ещё и в меню Пуск")
    ap.add_argument("--remove", action="store_true", help="убрать ярлыки")
    args = ap.parse_args()
    if not IS_WINDOWS and args.start_menu:
        # На Linux меню и так одно, на macOS -- папка Applications.
        print("--start-menu имеет смысл только на Windows")
    return remove(args.start_menu) if args.remove else create(args.start_menu)


if __name__ == "__main__":
    raise SystemExit(main())
