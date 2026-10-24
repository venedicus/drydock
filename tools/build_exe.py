"""Собрать Drydock.exe -- один файл, без Python у пользователя.

    .venv/Scripts/python tools/build_exe.py

Кладёт dist/Drydock.exe. Иконка берётся из assets/drydock.ico, страницы
интерфейса упаковываются внутрь: server.WEB ищет их рядом с собой, а в
сборке это распакованный _MEIPASS.
"""
from __future__ import annotations

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
OUT = ROOT / "dist" / "Drydock.exe"


def main() -> int:
    if not ICON.is_file():
        print("нет иконки:", ICON, "-- запусти tools/make_icon.py")
        return 1

    for junk in (ROOT / "build", ROOT / "dist"):
        shutil.rmtree(junk, ignore_errors=True)

    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--log-level=WARN",
        "--onefile", "--windowed",
        "--name", "Drydock",
        f"--icon={ICON}",
        # Интерфейс и иконка -- внутрь файла.
        "--add-data", f"{ROOT / 'web'};web",
        "--add-data", f"{ROOT / 'assets'};assets",
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
        str(ENTRY),
    ]
    print("сборка...")
    result = subprocess.run(args, cwd=ROOT, check=False)
    if result.returncode != 0:
        print("PyInstaller завершился с кодом", result.returncode)
        return result.returncode

    if not OUT.is_file():
        print("файл не появился:", OUT)
        return 1
    size = OUT.stat().st_size / 1024 / 1024
    print(f"готово: {OUT} ({size:.1f} МБ)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
