"""Тесты для механизма резервирования дискового пространства SpaceClaim в download.py."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

try:
    import pytest
except ImportError:
    pytest = None

ROOT = Path(tempfile.mkdtemp(prefix="cr-space-"))
os.environ["DRYDOCK_ROOT"] = str(ROOT)
os.environ["DRYDOCK_SECRETS"] = str(ROOT / "secrets.bin")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from drydock import config, download

if pytest is not None:

    @pytest.fixture(autouse=True, scope="module")
    def _own_root():
        config.set_root(ROOT)
        yield


def test_space_claim_deducts_on_written() -> None:
    # Исходное состояние: _inflight = 0
    download._inflight = 0

    claim = download.SpaceClaim(10_000_000)
    ok = claim.claim()
    assert ok is True
    assert download._inflight == 10_000_000
    assert claim.remaining == 10_000_000

    # Записано 4 МБ
    claim.on_bytes_written(4_000_000)
    assert claim.remaining == 6_000_000
    assert download._inflight == 6_000_000

    # Записано еще 6 МБ
    claim.on_bytes_written(6_000_000)
    assert claim.remaining == 0
    assert download._inflight == 0

    # Завершение
    claim.release()
    assert download._inflight == 0


def test_space_claim_releases_on_error() -> None:
    download._inflight = 0
    claim = download.SpaceClaim(5_000_000)
    assert claim.claim() is True
    assert download._inflight == 5_000_000

    # Записано 1 МБ, потом сбой
    claim.on_bytes_written(1_000_000)
    assert download._inflight == 4_000_000

    claim.release()
    assert download._inflight == 0


def test_space_claims_are_atomic_across_threads(monkeypatch) -> None:
    """Параллельные претензии не могут обе потратить один запас диска."""
    from concurrent.futures import ThreadPoolExecutor

    download._inflight = 0
    monkeypatch.setattr(download, "free_space", lambda _path: 150)
    monkeypatch.setattr(config, "RESERVE", 50)
    claims = [download.SpaceClaim(60), download.SpaceClaim(60)]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda claim: claim.claim(), claims))

    assert sorted(results) == [False, True], results
    assert download._inflight == 60
    for claim in claims:
        claim.release()
    assert download._inflight == 0

