#!/bin/sh
# Drydock для macOS и Linux.
#   без аргументов  -- окно приложения
#   с аргументами   -- CLI: ./Drydock.sh status | scan | probe | archive
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
  echo "Нет .venv. Сначала: python3 -m venv .venv && .venv/bin/python -m pip install -e ." >&2
  exit 1
fi
if [ "$#" -eq 0 ]; then
  exec .venv/bin/python -m drydock.cli app
fi
exec .venv/bin/python -m drydock.cli "$@"
