"""Точка входа при запуске модуля: python -m drydock [аргументы]."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
