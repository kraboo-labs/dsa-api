import asyncio
import secrets

import pytest_asyncio
import redis.asyncio as aioredis

from core.config import get_settings
from core.ratelimit import LimitConfig, check_limit


@pytest_asyncio.fixture
async def redis_client():
    settings = get_settings()
    client = aioredis.from_url(settings.redis_url, decode_responses=False)
    try:
        yield client
    finally:
        await client.aclose()


def _isolated_prefix() -> str:
    """Unique prefix per test so concurrent tests don't share state."""
    return f"rl-test-{secrets.token_hex(4)}"


async def test_allows_first_request_and_increments_counter(redis_client):
    cfg = LimitConfig("min", 60, 5)
    prefix = _isolated_prefix()
    decision = await check_limit(redis_client, "1.1.1.1", cfg, key_prefix=prefix)
    assert decision.allowed is True
    assert decision.current == 1
    assert decision.retry_after == 0


async def test_blocks_when_limit_reached(redis_client):
    cfg = LimitConfig("min", 60, 3)
    prefix = _isolated_prefix()
    for _ in range(3):
        assert (await check_limit(redis_client, "2.2.2.2", cfg, key_prefix=prefix)).allowed
    blocked = await check_limit(redis_client, "2.2.2.2", cfg, key_prefix=prefix)
    assert blocked.allowed is False
    assert blocked.retry_after >= 1
    assert blocked.config.name == "min"


async def test_isolated_by_ip(redis_client):
    cfg = LimitConfig("min", 60, 1)
    prefix = _isolated_prefix()
    a = await check_limit(redis_client, "3.3.3.3", cfg, key_prefix=prefix)
    b = await check_limit(redis_client, "4.4.4.4", cfg, key_prefix=prefix)
    assert a.allowed and b.allowed


async def test_window_expires(redis_client):
    cfg = LimitConfig("min", 1, 2)  # 1-second window, 2 requests
    prefix = _isolated_prefix()
    assert (await check_limit(redis_client, "5.5.5.5", cfg, key_prefix=prefix)).allowed
    assert (await check_limit(redis_client, "5.5.5.5", cfg, key_prefix=prefix)).allowed
    assert not (await check_limit(redis_client, "5.5.5.5", cfg, key_prefix=prefix)).allowed
    await asyncio.sleep(1.2)
    # After the window passes, previous timestamps fall out of the sorted set
    # and we should be allowed again.
    assert (await check_limit(redis_client, "5.5.5.5", cfg, key_prefix=prefix)).allowed
