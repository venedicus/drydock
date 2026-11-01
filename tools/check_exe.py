"""Проверить собранный файл: запустить сервером и дождаться ответа.

    .venv/Scripts/python tools/check_exe.py      # Windows
    .venv/bin/python tools/check_exe.py          # macOS, Linux

Окно не открываем: `Drydock serve` поднимает только сервер, поэтому
проверка годится и для CI, где нет рабочего стола.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

# Консоль Windows бывает cp1252: без этого первый же print с
# кириллицей падает ещё до сборки.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"
DIST = Path(__file__).resolve().parent.parent / "dist"
if IS_WINDOWS:
    EXE = DIST / "Drydock.exe"
elif IS_MACOS:
    EXE = DIST / "Drydock.app" / "Contents" / "MacOS" / "Drydock"
else:
    EXE = DIST / "Drydock"
PORT = 8799
URL = f"http://127.0.0.1:{PORT}/api/state"


def _stop(proc: subprocess.Popen) -> None:
    """Снять сборку целиком, вместе с дочерним сервером.

    PyInstaller onefile запускает настоящий сервер дочерним процессом:
    terminate() снимает только распаковщик, а `serve` остаётся висеть на
    порту и ломает следующий прогон. На Windows поэтому taskkill /T, на
    POSIX -- сигнал всей группе процессов.
    """
    if proc.poll() is not None:
        return
    if IS_WINDOWS:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except OSError:
            proc.kill()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def main() -> int:
    if not EXE.is_file():
        print("нет файла:", EXE)
        return 1

    root = Path(tempfile.mkdtemp(prefix="drydock-exe-"))
    env = dict(os.environ, DRYDOCK_ROOT=str(root), PYTHONUTF8="1")
    proc = subprocess.Popen(  # свой же собранный файл
        [str(EXE), "serve", "--port", str(PORT)],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        # Своя группа: тогда сигнал снимает и распаковщик, и сервер.
        start_new_session=not IS_WINDOWS)
    try:
        for _ in range(60):
            if proc.poll() is not None:
                out = (proc.stdout.read() or b"").decode("utf-8", "replace")
                print("сборка завершилась раньше времени:\n" + out[-1500:])
                return 1
            try:
                with urllib.request.urlopen(URL, timeout=2) as resp:
                    if resp.status == 200:
                        print(f"сборка отвечает: {URL} -> 200")
                        return 0
            except (urllib.error.URLError, OSError):
                time.sleep(1)
        print("сборка не ответила за 60 секунд")
        return 1
    finally:
        _stop(proc)
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
