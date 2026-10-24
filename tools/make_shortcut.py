"""Ярлыки Drydock -- разовая настройка рабочего места.

    .venv/Scripts/python tools/make_shortcut.py                # рабочий стол
    .venv/Scripts/python tools/make_shortcut.py --start-menu   # и меню Пуск
    .venv/Scripts/python tools/make_shortcut.py --remove       # убрать

Ярлык указывает прямо на pythonw.exe, а не на .bat: .bat на мгновение
показывает окно консоли, и приложение выглядит самоделкой. pythonw консоли
не создаёт вовсе.

Права администратора не нужны: всё делается для текущего пользователя.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHONW = ROOT / ".venv" / "Scripts" / "pythonw.exe"
ICON = ROOT / "assets" / "drydock.ico"
NAME = "Drydock.lnk"

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


def _ps(script: str) -> None:
    proc = subprocess.run(  # noqa: PLW1510 - код возврата проверяем ниже
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise OSError(proc.stdout + proc.stderr)


def _folders(start_menu: bool) -> list[Path]:
    out = [Path.home() / "Desktop"]
    # OneDrive переносит рабочий стол к себе -- кладём туда, где он реально есть.
    onedrive = Path.home() / "OneDrive" / "Desktop"
    if onedrive.is_dir():
        out = [onedrive]
    if start_menu:
        out.append(Path.home() / "AppData" / "Roaming" / "Microsoft"
                   / "Windows" / "Start Menu" / "Programs")
    return [p for p in out if p.is_dir()]


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
        _ps(PS_CREATE.format(
            dest=dest, target=PYTHONW, args="-m drydock.cli app",
            cwd=ROOT, icon=ICON))
        print(f"Ярлык: {dest}")
        made += 1
    if not made:
        print("Не нашёл ни рабочего стола, ни меню Пуск.", file=sys.stderr)
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
    return remove(args.start_menu) if args.remove else create(args.start_menu)


if __name__ == "__main__":
    raise SystemExit(main())
