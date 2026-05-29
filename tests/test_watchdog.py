from datetime import UTC, datetime, timedelta

import pytest_asyncio
import redis.asyncio as aioredis

from apps.scraper import watchdog
from core.config import get_settings
from core.timestamps import write_data_updated_at


@pytest_asyncio.fixture
async def redis_client():
    client = aioredis.from_url(get_settings().redis_url)
    try:
        yield client
    finally:
        await client.aclose()


async def test_watchdog_warns_when_no_scrape_recorded(monkeypatch, redis_client):
    # FLUSHDB is done by the autouse conftest fixture; no key set here.
    notified: list[str] = []

    async def fake_notify(url, message, **_kw):
        notified.append(message)
        return True

    monkeypatch.setattr(watchdog, "notify_slack", fake_notify)
    rc = await watchdog._amain()
    assert rc == 0
    assert any("no successful scrape" in m for m in notified)


async def test_watchdog_silent_when_scrape_is_fresh(monkeypatch, redis_client):
    await write_data_updated_at(redis_client, datetime.now(UTC) - timedelta(hours=1))
    notified: list[str] = []

    async def fake_notify(url, message, **_kw):
        notified.append(message)
        return True

    monkeypatch.setattr(watchdog, "notify_slack", fake_notify)
    rc = await watchdog._amain()
    assert rc == 0
    assert notified == []


async def test_watchdog_warns_when_scrape_is_stale(monkeypatch, redis_client):
    await write_data_updated_at(redis_client, datetime.now(UTC) - timedelta(hours=30))
    notified: list[str] = []

    async def fake_notify(url, message, **_kw):
        notified.append(message)
        return True

    monkeypatch.setattr(watchdog, "notify_slack", fake_notify)
    rc = await watchdog._amain()
    assert rc == 0
    assert any("last successful scrape was" in m for m in notified)


async def test_watchdog_warns_on_unparseable_timestamp(monkeypatch, redis_client):
    await redis_client.set("dsa:last_scrape_completed_at", "not-a-date")
    notified: list[str] = []

    async def fake_notify(url, message, **_kw):
        notified.append(message)
        return True

    monkeypatch.setattr(watchdog, "notify_slack", fake_notify)
    rc = await watchdog._amain()
    assert rc == 0
    assert any("unparseable" in m for m in notified)
