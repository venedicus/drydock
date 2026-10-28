"""Проверить собранный exe: запустить сервером и дождаться ответа.

    .venv/Scripts/python tools/check_exe.py

Окно не открываем: `Drydock.exe serve` поднимает только сервер, поэтому
проверка годится и для CI, где нет рабочего стола.
"""
from __future__ import annotations

import os
import shutil
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

EXE = Path(__file__).resolve().parent.parent / "dist" / "Drydock.exe"
PORT = 8799
URL = f"http://127.0.0.1:{PORT}/api/state"


def main() -> int:
    if not EXE.is_file():
        print("нет файла:", EXE)
        return 1

    root = Path(tempfile.mkdtemp(prefix="drydock-exe-"))
    env = dict(os.environ, DRYDOCK_ROOT=str(root), PYTHONUTF8="1")
    proc = subprocess.Popen(  # свой же собранный файл
        [str(EXE), "serve", "--port", str(PORT)],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        for _ in range(60):
            if proc.poll() is not None:
                out = (proc.stdout.read() or b"").decode("utf-8", "replace")
                print("exe завершился раньше времени:\n" + out[-1500:])
                return 1
            try:
                with urllib.request.urlopen(URL, timeout=2) as resp:
                    if resp.status == 200:
                        print(f"exe отвечает: {URL} -> 200")
                        return 0
            except (urllib.error.URLError, OSError):
                time.sleep(1)
        print("exe не ответил за 60 секунд")
        return 1
    finally:
        # PyInstaller onefile запускает настоящий сервер дочерним процессом:
        # terminate() снимает только распаковщик, а `serve` остаётся висеть
        # на порту и ломает следующий прогон. Поэтому на Windows снимаем
        # всё дерево целиком.
        if os.name == "nt":
            subprocess.run(  # noqa: PLW1510 - код возврата здесь не важен
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            proc.kill()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
