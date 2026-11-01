"""Собрать Drydock одним файлом -- без Python у пользователя.

    .venv/Scripts/python tools/build_exe.py      # Windows
    .venv/bin/python tools/build_exe.py          # macOS, Linux

Кладёт dist/Drydock.exe (Windows) или dist/Drydock (Linux) или
dist/Drydock.app (macOS). Иконка берётся из assets/drydock.ico и только на
Windows: PyInstaller на macOS ждёт .icns, а на Linux иконка файлу не нужна.
Страницы интерфейса упаковываются внутрь: server.WEB ищет их рядом с собой,
а в сборке это распакованный _MEIPASS.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

# Консоль Windows бывает cp1252: без этого первый же print с
# кириллицей падает ещё до сборки.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
ICON = ROOT / "assets" / "drydock.ico"
ENTRY = ROOT / "tools" / "entry.py"
IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"

if IS_WINDOWS:
    OUT = ROOT / "dist" / "Drydock.exe"
elif IS_MACOS:
    OUT = ROOT / "dist" / "Drydock.app"
else:
    OUT = ROOT / "dist" / "Drydock"


def main() -> int:
    if IS_WINDOWS and not ICON.is_file():
        print("нет иконки:", ICON, "-- запусти tools/make_icon.py")
        return 1

    for junk in (ROOT / "build", ROOT / "dist"):
        shutil.rmtree(junk, ignore_errors=True)

    # Разделитель в --add-data свой у каждой системы: ';' на Windows,
    # ':' на остальных. Ошибка здесь даёт сборку без web/ и пустое окно.
    sep = os.pathsep
    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--log-level=WARN",
        "--onefile",
        "--name", "Drydock",
        # Интерфейс и иконка -- внутрь файла.
        "--add-data", f"{ROOT / 'web'}{sep}web",
        "--add-data", f"{ROOT / 'assets'}{sep}assets",
        # uvicorn подтягивает реализации через строки, статический анализ
        # их не видит.
        "--collect-submodules", "uvicorn",
        "--hidden-import", "uvicorn.logging",
        "--hidden-import", "uvicorn.loops.auto",
        "--hidden-import", "uvicorn.protocols.http.auto",
        "--hidden-import", "uvicorn.protocols.websockets.auto",
        "--hidden-import", "uvicorn.lifespan.on",
        # httpx[http2] -- свои зависимости у h2.
        "--collect-submodules", "h2",
    ]
    if IS_WINDOWS:
        # На Windows это «без окна консоли» + иконка exe.
        args += ["--windowed", f"--icon={ICON}"]
    elif IS_MACOS:
        # .app-пакет: без него из Finder не запустить.
        args += ["--windowed"]
    args.append(str(ENTRY))

    print("сборка...")
    result = subprocess.run(args, cwd=ROOT, check=False)
    if result.returncode != 0:
        print("PyInstaller завершился с кодом", result.returncode)
        return result.returncode

    if not OUT.exists():
        print("файл не появился:", OUT)
        return 1
    size = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file()) \
        if OUT.is_dir() else OUT.stat().st_size
    print(f"готово: {OUT} ({size / 1024 / 1024:.1f} МБ)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
