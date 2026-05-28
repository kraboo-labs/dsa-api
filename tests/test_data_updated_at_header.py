from datetime import UTC, datetime

import httpx
import pytest_asyncio
import redis.asyncio as aioredis
from httpx import ASGITransport

from apps.api.deps import get_db_session
from apps.api.main import create_app
from core.config import get_settings
from core.timestamps import write_data_updated_at


@pytest_asyncio.fixture
async def app_with_db(db_session_factory):
    async def _override():
        async with db_session_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db_session] = _override
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_header_present_when_scraper_wrote_timestamp(app_with_db):
    settings = get_settings()
    redis = aioredis.from_url(settings.redis_url)
    try:
        when = datetime(2026, 5, 28, 10, 0, 0, tzinfo=UTC)
        await write_data_updated_at(redis, when)
    finally:
        await redis.aclose()

    response = await app_with_db.get("/v1/version")
    assert response.headers["X-Data-Updated-At"] == when.isoformat()


async def test_header_absent_when_no_scrape_has_run(app_with_db):
    response = await app_with_db.get("/v1/version")
    assert "X-Data-Updated-At" not in response.headers


async def test_header_set_on_all_v1_endpoints(app_with_db):
    settings = get_settings()
    redis = aioredis.from_url(settings.redis_url)
    try:
        await write_data_updated_at(redis, datetime(2026, 5, 28, tzinfo=UTC))
    finally:
        await redis.aclose()

    for path in ("/v1/health", "/v1/version", "/v1/trusted-flaggers", "/v1/changes", "/v1/stats"):
        response = await app_with_db.get(path)
        assert "X-Data-Updated-At" in response.headers, f"missing on {path}"
