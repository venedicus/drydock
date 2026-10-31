from unittest.mock import AsyncMock, MagicMock

import pytest

from drydock import server
from drydock.download import SpeedMeter


def test_speed_meter():
    meter = SpeedMeter(window_s=1.0)
    assert meter.speed() == 0.0
    meter.record(1024 * 1024)
    assert meter.speed() > 0.0

    meter.reset(total_bytes=5 * 1024 * 1024)
    meter.record(1024 * 1024)
    stats = meter.stats()
    assert stats["bytes_total"] == 5 * 1024 * 1024
    assert stats["bytes_done"] == 1024 * 1024
    assert stats["speed_bps"] > 0.0
    assert stats["eta_s"] is not None


@pytest.mark.anyio
async def test_events_sse_endpoint():
    req = MagicMock()
    req.is_disconnected = AsyncMock(return_value=False)
    resp = await server.events_sse(req)
    assert resp.status_code == 200
    assert resp.media_type == "text/event-stream"
    items = []
    async for chunk in resp.body_iterator:
        items.append(chunk)
        if len(items) >= 1:
            break
    assert len(items) == 1
    assert "event: jobs" in items[0]
    assert "data:" in items[0]
