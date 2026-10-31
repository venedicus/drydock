"""Тесты для обнаружения и безопасного переноса базы данных."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

try:
    import pytest
except ImportError:
    pytest = None

ROOT = Path(tempfile.mkdtemp(prefix="cr-dbmig-"))
os.environ["DRYDOCK_ROOT"] = str(ROOT)
os.environ["DRYDOCK_SECRETS"] = str(ROOT / "secrets.bin")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from drydock import config, db, server

if pytest is not None:

    @pytest.fixture(autouse=True, scope="module")
    def _own_root():
        config.set_root(ROOT)
        yield


def test_inspect_and_discover_databases() -> None:
    config.set_root(ROOT)
    config.PATHS.ensure()
    conn = db.connect(config.PATHS.db)
    db.upsert_resource(conn, {"path": "disk:/test.pdf", "name": "test.pdf", "type": "file", "size": 123})
    conn.execute("INSERT INTO local(path, local_path, bytes, verify, downloaded_at, released) VALUES(?, 'x', 123, 'ok', 1, 0)",
                 ("disk:/test.pdf",))

    info = config.inspect_db(config.PATHS.db)
    assert info is not None
    assert info["files_count"] == 1
    assert info["saved_count"] == 1

    # Запоминаем корень в истории
    config.record_known_root(ROOT)
    discovered = config.discover_databases()
    assert any(d["root"] == str(ROOT) for d in discovered)


def test_settings_check_and_copy_db() -> None:
    config.set_root(ROOT)
    config.PATHS.ensure()
    conn = db.connect(config.PATHS.db)
    db.upsert_resource(conn, {"path": "disk:/important.pdf", "name": "important.pdf", "type": "file", "size": 500})

    client = TestClient(server.app)

    new_root = Path(tempfile.mkdtemp(prefix="cr-newroot-"))

    # 1. Проверяем путь: базы там нет
    check = client.post("/api/settings/check", json={"save_root": str(new_root)}).json()
    assert check["target_has_db"] is False
    assert check["current_has_db"] is True
    assert check["current_files"] >= 1

    # 2. Выбираем с action='copy_current'
    resp = client.post("/api/settings", json={"save_root": str(new_root), "action": "copy_current"}).json()
    assert resp["chosen_root"] == str(new_root)
    assert resp["target_has_db"] is True

    # 3. Проверяем, что catalog.db действительно появился в new_root и содержит данные
    copied_db = new_root / "catalog.db"
    assert copied_db.is_file()
    copied_info = config.inspect_db(copied_db)
    assert copied_info is not None
    assert copied_info["files_count"] >= 1
