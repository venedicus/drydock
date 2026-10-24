"""Точка входа для собранного exe.

Без аргументов -- окно приложения. С аргументами -- обычная командная
строка, чтобы `Drydock.exe serve --port 8766` работал там, где окно не
нужно (сервер, проверка сборки в CI).

В сборке без консоли sys.stdout и sys.stderr равны None, и первый же
print на аварийной ветке уронил бы лаунчер. Подменяем их заглушкой.
"""
from __future__ import annotations

import os
import sys


def _quiet_streams() -> None:
    if sys.stdout is None:
        # Поток живёт всё время работы: закрывать его некому.
        sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115


def main() -> int:
    _quiet_streams()
    from drydock.cli import main as cli

    if len(sys.argv) <= 1:
        sys.argv = [sys.argv[0], "app"]
    return cli()


if __name__ == "__main__":
    raise SystemExit(main())
