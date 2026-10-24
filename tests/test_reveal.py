"""Проверка «открыть папку»: наружу -- только корень спасения.

Путь приходит из браузера, а открывать по нему произвольное место на диске
незачем. Всё, что не лежит внутри корня, должно схлопываться в корень --
включая попытки выйти наверх через `..`.
"""

from __future__ import annotations

try:  # pytest не нужен файлу для работы напрямую
    import pytest
except ImportError:  # pragma: no cover
    pytest = None

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(tempfile.mkdtemp(prefix="cr-reveal-"))
os.environ["DRYDOCK_ROOT"] = str(ROOT)
os.environ["DRYDOCK_SECRETS"] = str(ROOT / "secrets.bin")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from drydock import config, server

if pytest is not None:

    @pytest.fixture(autouse=True, scope="module")
    def _own_root():
        """Свой корень спасения для этого файла тестов.

        Файл задаёт DRYDOCK_ROOT при импорте, а PATHS связывается
        один раз на процесс. Если в одном воркере оказалось несколько
        файлов, они бы поделили корень и писали в чужую базу.
        """
        config.set_root(ROOT)
        yield


def main() -> int:
    config.PATHS.ensure()
    book = config.PATHS.files / "Library" / "Наука" / "book.pdf"
    book.parent.mkdir(parents=True, exist_ok=True)
    book.write_bytes(b"x")

    root = config.PATHS.root.resolve()

    # Пусто -- корень.
    assert server.reveal_target(None).resolve() == root

    # Существующий файл -- он сам (проводник выделит его в папке).
    got = server.reveal_target("disk:/Library/Наука/book.pdf").resolve()
    assert got == book.resolve(), got

    # Файл ещё не скачан -- показываем папку, куда он ляжет.
    got = server.reveal_target("disk:/Library/Наука/нет.pdf").resolve()
    assert got == book.parent.resolve(), got

    # Побег наверх не проходит ни в каком виде. Важно именно это: остаться
    # внутри корня. Куда конкретно схлопнется такой путь -- в сам корень или
    # в files/ -- неважно, лишь бы не наружу.
    for escape in ("disk:/../../../Windows", "disk:/..", "disk:/Library/../../..",
                   "disk:/C:/Windows/System32"):
        got = server.reveal_target(escape).resolve()
        assert got == root or root in got.parents, f"{escape} -> {got}"

    print("открыть папку: за пределы корня не выпускает")
    print("\nreveal: все проверки прошли")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
