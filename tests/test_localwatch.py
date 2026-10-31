"""Тесты для модуля localwatch: сверка зеркала с диском.

Проверяет:
1. Файлы с запрещенными в Windows символами (двоеточие и т.д.), сохраненные
   с заменой на Unicode, не теряются, не помечаются missing=1 и не дублируются.
2. Файлы со статусом released=1 (оригинал убран после архивации) не помечаются missing.
3. Реально удаленные файлы помечаются missing=1.
4. Вернувшиеся файлы снимают отметку missing=0.
5. Новые файлы на диске регистрируются с type='file' и unverified.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

try:
    import pytest
except ImportError:
    pytest = None

ROOT = Path(tempfile.mkdtemp(prefix="cr-lw-"))
os.environ["DRYDOCK_ROOT"] = str(ROOT)
os.environ["DRYDOCK_SECRETS"] = str(ROOT / "secrets.bin")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from drydock import config, db, localpath, localwatch

if pytest is not None:

    @pytest.fixture(autouse=True, scope="module")
    def _own_root():
        config.set_root(ROOT)
        yield


def test_localwatch_special_characters_not_duplicated_or_missing() -> None:
    config.set_root(ROOT)
    config.PATHS.ensure()
    conn = db.connect(config.PATHS.db)

    # Создаем файл с двоеточием в имени
    cloud_path = "disk:/Lectures/Math: Part 1.pdf"
    target = localpath.local_for(cloud_path, config.PATHS.files)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"pdf-content-12345")

    db.upsert_resource(conn, {
        "path": cloud_path, "name": "Math: Part 1.pdf",
        "type": "file", "size": 17,
    })
    conn.execute(
        """INSERT INTO local(path, local_path, bytes, verify, downloaded_at, released, missing)
           VALUES(?, ?, 17, 'ok', ?, 0, 0)""",
        (cloud_path, str(target), db.now())
    )

    # Запускаем сверку
    res = localwatch.sync(conn)
    assert res["added"] == 0, f"Файл не должен был добавиться как дубликат: {res}"
    assert res["vanished"] == 0, f"Файл не должен был стать missing: {res}"

    row = conn.execute("SELECT missing FROM local WHERE path=?", (cloud_path,)).fetchone()
    assert row is not None and row["missing"] == 0

    # Проверяем, что не создалось ложного ресурса с \uf03a
    fake = conn.execute("SELECT COUNT(*) as n FROM resources WHERE path LIKE '%\\uf03a%'").fetchone()
    assert fake["n"] == 0


def test_localwatch_missing_and_restored() -> None:
    config.set_root(ROOT)
    config.PATHS.ensure()
    conn = db.connect(config.PATHS.db)

    cloud_path = "disk:/Docs/report.docx"
    target = localpath.local_for(cloud_path, config.PATHS.files)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"content")

    db.upsert_resource(conn, {"path": cloud_path, "name": "report.docx", "type": "file", "size": 7})
    conn.execute(
        """INSERT INTO local(path, local_path, bytes, verify, downloaded_at, released, missing)
           VALUES(?, ?, 7, 'ok', ?, 0, 0)""",
        (cloud_path, str(target), db.now())
    )

    # Удаляем файл с диска
    target.unlink()

    res = localwatch.sync(conn)
    assert res["vanished"] == 1
    row = conn.execute("SELECT missing FROM local WHERE path=?", (cloud_path,)).fetchone()
    assert row["missing"] == 1

    # Возвращаем файл обратно
    target.write_bytes(b"content")
    res2 = localwatch.sync(conn)
    assert res2["restored"] == 1
    row2 = conn.execute("SELECT missing FROM local WHERE path=?", (cloud_path,)).fetchone()
    assert row2["missing"] == 0


def test_localwatch_released_file_not_marked_missing() -> None:
    config.set_root(ROOT)
    config.PATHS.ensure()
    conn = db.connect(config.PATHS.db)

    cloud_path = "disk:/Archive/old_video.mp4"
    target = localpath.local_for(cloud_path, config.PATHS.files)

    db.upsert_resource(conn, {"path": cloud_path, "name": "old_video.mp4", "type": "file", "size": 100})
    conn.execute(
        """INSERT INTO local(path, local_path, bytes, verify, downloaded_at, released, missing)
           VALUES(?, ?, 100, 'ok', ?, 1, 0)""",
        (cloud_path, str(target), db.now())
    )

    # Файла нет на диске, но он released=1 (упакован в 7z)
    res = localwatch.sync(conn)
    assert res["vanished"] == 0
    row = conn.execute("SELECT missing FROM local WHERE path=?", (cloud_path,)).fetchone()
    assert row["missing"] == 0


def test_localwatch_registers_new_manual_file() -> None:
    config.set_root(ROOT)
    config.PATHS.ensure()
    conn = db.connect(config.PATHS.db)

    # Пользователь вручную положил файл в files/Manual/manual.txt
    manual_file = config.PATHS.files / "Manual" / "manual.txt"
    manual_file.parent.mkdir(parents=True, exist_ok=True)
    manual_file.write_bytes(b"hello world")

    res = localwatch.sync(conn)
    assert res["added"] == 1

    expected_cloud = "disk:/Manual/manual.txt"
    row = conn.execute("SELECT verify, missing, bytes FROM local WHERE path=?", (expected_cloud,)).fetchone()
    assert row is not None
    assert row["verify"] == "unverified"
    assert row["missing"] == 0
    assert row["bytes"] == 11
