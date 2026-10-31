"""Проверка упаковки на настоящем 7z и настоящих файлах.

Проверяем именно то, что нельзя увидеть, читая код: что внутри архива
сохранилась структура папок (а не плоский список), что манифест и превью
туда попали, что sha256 томов считается и сходится, и что release не
трогает оригиналы, пока тома не проверены.

Том берём крошечный (1 МБ вместо 3900), чтобы набор реально разбился на
несколько частей -- иначе многотомность не проверить.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(tempfile.mkdtemp(prefix="cr-arch-"))
os.environ["DRYDOCK_ROOT"] = str(ROOT)
os.environ["DRYDOCK_VOLUME"] = "1m"
os.environ["DRYDOCK_RESERVE"] = "0"
os.environ["DRYDOCK_SECRETS"] = str(ROOT / "secrets.bin")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from drydock import archive, config, db
from drydock.scan import preview_dest

try:  # pytest есть не всегда: файл умеет запускаться и напрямую.
    import pytest
except ImportError:  # pragma: no cover - режим без pytest
    pytest = None

if pytest is not None:

    @pytest.fixture(autouse=True, scope="module")
    def _own_root():
        """Изолировать корень и настройки многотомного теста.

        xdist --dist=loadfile держит файл целиком на одном worker, но worker
        может до этого импортировать config через другой модуль; переменные
        окружения уже не перечитаются. Поэтому важные для теста значения
        устанавливаем после импорта и возвращаем исходные при завершении.
        """
        old_root = config.PATHS
        old_volume, old_reserve = config.VOLUME, config.RESERVE
        config.set_root(ROOT)
        config.VOLUME = "1m"
        config.RESERVE = 0
        yield
        config.PATHS = old_root
        config.VOLUME, config.RESERVE = old_volume, old_reserve

if pytest is not None:

    @pytest.fixture(scope="module")
    def conn():
        """Собранная папка и база с файлами.

        Область -- модуль: standalone-вариант тоже вызывает setup() один
        раз на оба теста, а на каждый тест вставка тех же строк в local
        падает на UNIQUE.
        """
        if archive.seven_zip() is None:
            pytest.skip("7-Zip не найден -- проверка пропущена")
        c = setup()
        yield c
        c.close()

    @pytest.fixture()
    def archive_id(conn):
        """Номер архива, который собрал test_build (он идёт первым).

        Собирать заново нельзя: имя тома уникально, второй сбор падает на
        ограничении базы. Если test_build ещё не бежал (запуск одного
        теста) -- собираем сами.
        """
        row = conn.execute("SELECT id FROM archives ORDER BY id DESC "
                           "LIMIT 1").fetchone()
        if row is None:
            result = archive.build(conn, None)
            assert result["files"] == 4, result
            row = conn.execute("SELECT id FROM archives ORDER BY id DESC "
                               "LIMIT 1").fetchone()
        assert row is not None, "архив не собрался"
        return int(row["id"])

FILES = [
    ("disk:/Library/Sorted/Наука/physics.pdf", 700_000),
    ("disk:/Library/Sorted/Наука/chem.pdf", 700_000),
    ("disk:/Library/Sorted/История/rome.djvu", 900_000),
    ("disk:/top level.txt", 1_000),
]


def setup() -> object:
    config.PATHS.ensure()
    conn = db.connect(config.PATHS.db)
    for cloud_path, size in FILES:
        rel = cloud_path.replace("disk:/", "")
        local = config.PATHS.files / rel
        local.parent.mkdir(parents=True, exist_ok=True)
        # Неслучайные, но несжимаемые данные: -mx0 всё равно не сжимает,
        # зато размер тома предсказуем.
        local.write_bytes(os.urandom(size))
        db.upsert_resource(conn, {"path": cloud_path, "name": Path(rel).name,
                                  "type": "file", "size": size})
        conn.execute(
            """INSERT INTO local(path,local_path,bytes,sha256,md5,verify,downloaded_at)
               VALUES(?,?,?,'s','m','ok',1)""", (cloud_path, str(local), size))
        prev = preview_dest(cloud_path)
        prev.parent.mkdir(parents=True, exist_ok=True)
        prev.write_bytes(b"\xff\xd8\xff" + b"preview" * 10)
    return conn


LAST_ARCHIVE: list[int] = []


def test_build(conn) -> None:
    pend = archive.pending(conn)
    assert len(pend) == 4, pend
    result = archive.build(conn, None)
    assert result["files"] == 4, result
    sets = result["archives"]
    assert len(sets) == 1, f"ожидался один набор томов, вышло {len(sets)}"
    info = sets[0]
    assert len(info["volumes"]) > 1, f"том не разбился: {info['volumes']}"
    print(f"упаковано: {info['files']} файлов, томов {len(info['volumes'])}")

    exe = archive.seven_zip()
    first = config.PATHS.archives / info["volumes"][0]
    # -sccUTF-8: без него 7z пишет в консоль в OEM-кодировке, и русские
    # имена не с чем сравнивать.
    listing = subprocess.run([str(exe), "l", "-y", "-sccUTF-8", str(first)],
                             check=False,
                             capture_output=True, text=True,
                             encoding="utf-8", errors="replace").stdout

    # Структура внутри архива -- та же, что на диске.
    for expect in ("files\\Library\\Sorted\\Наука\\physics.pdf",
                   "files\\Library\\Sorted\\История\\rome.djvu",
                   "meta\\previews\\Library\\Sorted\\Наука\\physics.pdf.jpg"):
        assert expect in listing, f"нет в архиве: {expect}\n{listing[-1500:]}"
    assert "_manifest.json" in listing, "манифест не попал в архив"
    print("структура и превью внутри архива: ок")

    # Манифест лежит и рядом с томами -- посмотреть содержимое набора можно
    # без распаковки.
    beside = list(config.PATHS.archives.glob("*_manifest.json"))
    assert beside, "манифеста рядом с томами нет"
    import json
    man = json.loads(beside[0].read_text(encoding="utf-8"))
    assert len(man["files"]) == 4, man
    assert man["files"][0]["cloud_meta"]["path"].startswith("disk:/")
    print("манифест рядом с томами: ок")

    # sha256 томов записан и сходится.
    check = archive.verify(conn, info["id"])
    assert len(check["ok"]) == len(info["volumes"]), check
    assert not check["bad"] and not check["missing"], check
    print(f"sha256 томов сходится ({len(check['ok'])} шт)")
    LAST_ARCHIVE.append(info["id"])


def test_release_guard(conn, archive_id: int) -> None:
    """Порча тома должна остановить удаление оригиналов."""
    vol = config.PATHS.archives / conn.execute(
        "SELECT volume FROM archive_volumes WHERE archive_id=? LIMIT 1",
        (archive_id,)).fetchone()["volume"]
    backup = vol.read_bytes()
    vol.write_bytes(backup[:-100] + b"X" * 100)
    try:
        archive.release(conn, archive_id)
    except ValueError as exc:
        assert "не сходятся" in str(exc), exc
        print("битый том остановил release: ок")
    else:
        raise AssertionError("release удалил оригиналы при битом томе!")
    # Все файлы на месте.
    alive = sum(1 for _p, _s in FILES
                if Path(conn.execute(
                    "SELECT local_path FROM local WHERE path=?", (_p,)
                ).fetchone()["local_path"]).is_file())
    assert alive == 4, f"оригиналов осталось {alive} из 4"
    vol.write_bytes(backup)

    result = archive.release(conn, archive_id)
    assert result["released"] == 4, result
    gone = sum(1 for _p, _s in FILES
               if not Path(conn.execute(
                   "SELECT local_path FROM local WHERE path=?", (_p,)
               ).fetchone()["local_path"]).is_file())
    assert gone == 4, "оригиналы не удалены после успешной проверки"
    print(f"release после проверки: убрано {result['released']}, "
          f"освобождено {result['freed_bytes'] / 2**20:.1f} МБ")

    # Повторная упаковка не должна хватать уже упакованное.
    assert archive.pending(conn) == [], "released файлы снова предложены к упаковке"
    print("повторная упаковка ничего не берёт: ок")


def main() -> int:
    if archive.seven_zip() is None:
        print("7-Zip не найден -- проверка пропущена")
        return 0
    conn = setup()
    test_build(conn)
    test_release_guard(conn, LAST_ARCHIVE[-1])
    conn.close()
    print("\nархивация: все проверки прошли")
    print(f"(рабочая папка проверки: {ROOT})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
