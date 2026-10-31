"""Проверки безопасной замены при переносе из папки клиента Яндекс.Диска."""
from __future__ import annotations

import hashlib
import os
import sys
import tempfile
from pathlib import Path

try:
    import pytest
except ImportError:
    pytest = None

ROOT = Path(tempfile.mkdtemp(prefix="cr-adopt-test-"))
os.environ["DRYDOCK_ROOT"] = str(ROOT)
os.environ["DRYDOCK_SECRETS"] = str(ROOT / "secrets.bin")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from drydock import adopt, config, db
from drydock.localpath import local_for

if pytest is not None:

    @pytest.fixture(autouse=True, scope="module")
    def _own_root():
        config.set_root(ROOT)
        yield


def _conn(name: str):
    return db.connect(ROOT / f"{name}.db")


def test_hash_mismatch_preserves_existing_copy_and_source() -> None:
    """Новый файл с неверным хешем не затирает прежний локальный файл."""
    conn = _conn("mismatch")
    cloud_path = "disk:/Books/book.pdf"
    db.upsert_resource(conn, {"path": cloud_path, "name": "book.pdf",
                              "type": "file", "size": 9,
                              "sha256": hashlib.sha256(b"expected").hexdigest()})

    dest = local_for(cloud_path, config.PATHS.files)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"old-copy")
    conn.execute(
        "INSERT INTO local(path,local_path,bytes,verify,downloaded_at,released) "
        "VALUES(?,?,8,'mismatch',1,0)", (cloud_path, str(dest)))

    src = ROOT / "client" / "book.pdf"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(b"new-wrong")
    result = adopt.adopt_one(conn, {
        "path": cloud_path, "src": src, "size": 9,
        "sha256": hashlib.sha256(b"expected").hexdigest(), "md5": None,
    }, mode="move", verify=True)

    assert result["state"] == "mismatch", result
    assert dest.read_bytes() == b"old-copy"
    assert src.read_bytes() == b"new-wrong"
    row = conn.execute("SELECT verify, bytes FROM local WHERE path=?",
                       (cloud_path,)).fetchone()
    assert row and row["verify"] == "mismatch" and row["bytes"] == 8, dict(row or {})
    assert not list(dest.parent.glob("_cr_adopt_*.tmp"))


def test_verified_adopt_replaces_destination_atomically() -> None:
    """Проверенная новая копия заменяет старую, затем завершается move."""
    conn = _conn("verified")
    cloud_path = "disk:/Books/new.pdf"
    content = b"verified-new-file"
    sha = hashlib.sha256(content).hexdigest()
    db.upsert_resource(conn, {"path": cloud_path, "name": "new.pdf",
                              "type": "file", "size": len(content), "sha256": sha})

    dest = local_for(cloud_path, config.PATHS.files)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"old-copy")
    src = ROOT / "client" / "new.pdf"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(content)

    result = adopt.adopt_one(conn, {
        "path": cloud_path, "src": src, "size": len(content),
        "sha256": sha, "md5": None,
    }, mode="move", verify=True)

    assert result["state"] == "ok", result
    assert dest.read_bytes() == content
    assert not src.exists()
    row = conn.execute("SELECT verify, bytes FROM local WHERE path=?",
                       (cloud_path,)).fetchone()
    assert row and row["verify"] == "ok" and row["bytes"] == len(content), dict(row or {})
    assert not list(dest.parent.glob("_cr_adopt_*.tmp"))
