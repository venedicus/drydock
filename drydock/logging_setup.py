"""Лог в файл -- иначе отладка невозможна в принципе.

Приложение запускается через pythonw, у которого нет консоли: всё, что
программа пишет в stdout и stderr, исчезает. Один раз это уже стоило дорого --
httpx падал на кириллице в User-Agent, задача умирала молча, а в интерфейсе
висела полоска без единого слова о причине.

Поэтому:

* пишем в файл, с ротацией, чтобы за недели работы не раздуть диск;
* кладём рядом со спасаемым (`<корень>/logs/`), а не в папку программы:
  логи относятся к этой операции спасения, и уезжают вместе с ней;
* подхватываем чужие логгеры (uvicorn, httpx) в тот же файл;
* ловим то, что не поймал никто: sys.excepthook, unraisable и
  необработанные исключения asyncio;
* уровень задаётся DRYDOCK_LOG=DEBUG, по умолчанию INFO.

DEBUG включает заголовки и коды ответов httpx -- при разборе того, почему
конкретный файл не отдаётся, это главный источник правды.
"""

from __future__ import annotations

import asyncio
import logging
import logging.handlers
import os
import sys
import threading
from pathlib import Path

_READY = False
_LOCK = threading.Lock()

FORMAT = "%(asctime)s %(levelname)-7s %(name)-22s %(message)s"
DATEFMT = "%Y-%m-%d %H:%M:%S"


def log_dir() -> Path:
    from . import config
    return config.PATHS.root / "logs"


def log_file() -> Path:
    return log_dir() / "drydock.log"


def setup(level: str | None = None, *, console: bool = True) -> Path:
    """Включить логирование. Повторные вызовы безвредны."""
    global _READY
    with _LOCK:
        if _READY:
            return log_file()
        _READY = True

    level_name = (level or os.environ.get("DRYDOCK_LOG") or "INFO").upper()
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    path = log_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=8 * 1024 * 1024, backupCount=5, encoding="utf-8")
        handler.setFormatter(logging.Formatter(FORMAT, DATEFMT))
        handler.setLevel(getattr(logging, level_name, logging.INFO))
        root.addHandler(handler)
    except OSError:
        pass  # некуда писать -- не повод не работать

    # Консоль: только когда она есть. Под pythonw stderr может быть None.
    if console and sys.stderr is not None:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(logging.Formatter("%(levelname)-7s %(message)s"))
        stream.setLevel(getattr(logging, level_name, logging.INFO))
        root.addHandler(stream)

    debug = level_name == "DEBUG"
    # Чужие логгеры -- в тот же файл, но без болтовни.
    for name, lvl in (("uvicorn", logging.INFO), ("uvicorn.error", logging.INFO),
                      ("uvicorn.access", logging.WARNING),
                      # httpx на DEBUG даёт по строке на запрос -- это полезно.
                      ("httpx", logging.DEBUG if debug else logging.WARNING),
                      # httpcore на DEBUG сыплет внутренностями сокетов и
                      # топит в них всё остальное. Пользы ноль.
                      ("httpcore", logging.WARNING)):
        logging.getLogger(name).setLevel(lvl)

    _catch_everything()
    logging.getLogger("drydock").info(
        "лог начат, уровень %s, файл %s", level_name, path)
    return path


def capture_uvicorn() -> None:
    """Забрать логи uvicorn в наш файл.

    uvicorn применяет свой LOGGING_CONFIG уже после нашей настройки и
    ставит `propagate = False`, подвешивая собственный обработчик на
    stderr. Под pythonw stderr нет, поэтому трейсбек любой ошибки 500
    исчезал бесследно -- включаем передачу наверх, к нашему файлу.
    """
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        logging.getLogger(name).propagate = True


def _catch_everything() -> None:
    """Перехват того, что иначе уйдёт в несуществующую консоль."""
    log = logging.getLogger("drydock.unhandled")

    def on_exception(exc_type, exc, tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            return
        log.critical("необработанное исключение", exc_info=(exc_type, exc, tb))

    sys.excepthook = on_exception

    def on_unraisable(args) -> None:
        log.error("unraisable: %s в %r", args.exc_value, args.object)

    sys.unraisablehook = on_unraisable

    def on_threading(args) -> None:
        log.error("исключение в потоке %s", args.thread.name if args.thread else "?",
                  exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    threading.excepthook = on_threading


def install_asyncio_handler(loop: asyncio.AbstractEventLoop | None = None) -> None:
    """Исключения из задач asyncio тоже должны оказаться в логе."""
    log = logging.getLogger("drydock.asyncio")

    def handler(_loop, context: dict) -> None:
        exc = context.get("exception")
        message = context.get("message") or "ошибка в event loop"
        if exc is not None:
            log.error("%s", message, exc_info=exc)
        else:
            log.error("%s | %s", message, context)

    try:
        (loop or asyncio.get_running_loop()).set_exception_handler(handler)
    except RuntimeError:
        pass


def tail(lines: int = 300, *, level: str | None = None) -> list[str]:
    """Последние строки лога -- для показа в интерфейсе."""
    path = log_file()
    if not path.is_file():
        return []
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            block = min(size, max(lines * 200, 64 * 1024))
            fh.seek(size - block)
            text = fh.read().decode("utf-8", "replace")
    except OSError:
        return []
    rows = text.splitlines()
    if block < size and rows:
        rows = rows[1:]  # первая строка почти наверняка обрезана
    if level:
        wanted = level.upper()
        rows = [r for r in rows if f" {wanted:<7}" in r or wanted in r[:40]]
    return rows[-lines:]
