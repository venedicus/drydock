"""Общие фикстуры тестов.

Файлы тестов рассчитаны и на запуск напрямую (`python tests/test_x.py`), и
на pytest. Всё, что общее для нескольких файлов, лежит здесь: свой
корень DRYDOCK_ROOT каждый файл задаёт при импорте, а процессы
разделены через `--dist=loadfile` в pyproject -- иначе config.PATHS
связался бы с корнем первого импортировавшегося файла.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


@pytest.fixture()
def tmp() -> Path:
    """Временная папка: под неё тесты кладут свои базы и «папки клиента»."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        yield Path(d)
