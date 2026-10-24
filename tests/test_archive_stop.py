"""Паковка обязана слушаться «стоп».

19 октября задача архивации была отменена в 00:02:38 -- а запущенный ею
7z пережил и отмену, и закрытие приложения и работал ещё пятнадцать часов,
пока его не сняли вручную. Причина: subprocess.run нельзя прервать, а флаг
отмены проверялся только МЕЖДУ архивами, которых был один на всю коллекцию.

Здесь проверяется сама механика: долгий процесс, запущенный через _run,
снимается по сигналу и не остаётся сиротой.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

try:
    import pytest
except ImportError:
    pytest = None

ROOT = Path(tempfile.mkdtemp(prefix="cr-astop-"))
os.environ["DRYDOCK_ROOT"] = str(ROOT)
os.environ["DRYDOCK_SECRETS"] = str(ROOT / "secrets.bin")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from drydock import archive, config

if pytest is not None:

    @pytest.fixture(autouse=True, scope="module")
    def _own_root():
        config.set_root(ROOT)
        yield


SLEEPER = [sys.executable, "-c", "import time; time.sleep(120)"]


def test_stop_kills_the_process() -> None:
    """Долгий процесс снимается, а не ждёт своей смерти два часа."""
    stop = {"now": False}
    started = time.monotonic()

    import threading
    threading.Timer(1.0, lambda: stop.__setitem__("now", True)).start()

    code, _out = archive._run(SLEEPER, ROOT, lambda: stop["now"])
    spent = time.monotonic() - started

    assert code == archive.STOPPED, f"код {code}, ожидался STOPPED"
    assert spent < 20, f"остановка заняла {spent:.1f}с -- слишком долго"
    print(f"остановка сработала за {spent:.1f}с, код {code}")


def test_runs_to_the_end_without_stop() -> None:
    """Без запроса на остановку процесс доживает своё и отдаёт вывод."""
    # -X utf8: на CI консоль бывает cp1252, и печать кириллицы в дочернем
    # процессе падала с UnicodeEncodeError ещё до проверки.
    code, out = archive._run(
        [sys.executable, "-X", "utf8", "-c", "print('готово')"], ROOT,
        lambda: False)
    assert code == 0, (code, out)
    assert "готово" in out, out
    print("обычный запуск: код 0, вывод получен")


def test_no_orphan_left() -> None:
    """После остановки процесса-потомка не остаётся.

    Осиротевший 7z -- ровно то, что случилось: родительский python умер,
    а паковка продолжала жечь диск.
    """
    stop = {"now": False}
    import threading
    threading.Timer(0.8, lambda: stop.__setitem__("now", True)).start()
    archive._run(SLEEPER, ROOT, lambda: stop["now"])

    # Ни одного живого python с нашей меткой остаться не должно.
    probe = subprocess.run(  # noqa: PLW1510 - код возврата не важен
        ["powershell", "-NoProfile", "-NonInteractive", "-Command",
         ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" "
          "| Where-Object { $_.CommandLine -like '*time.sleep(120)*' } "
          "| Measure-Object | Select-Object -ExpandProperty Count")],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    left = (probe.stdout or "0").strip() or "0"
    assert left.isdigit() and int(left) == 0, f"осталось процессов: {left}"
    print("сирот не осталось")


def main() -> int:
    config.set_root(ROOT)
    test_stop_kills_the_process()
    test_runs_to_the_end_without_stop()
    test_no_orphan_left()
    print("\nостановка паковки: все проверки прошли")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
