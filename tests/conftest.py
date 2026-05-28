import asyncio
import os
import urllib.parse

import pytest_asyncio

# Point tests at a dedicated dsa_test database in the local docker postgres so
# integration tests never wipe the dev DB. Non-integration tests don't actually
# open a connection — dependency overrides take care of that.
os.environ.setdefault("DSA_DATABASE_URL", "postgresql+asyncpg://dsa:dsa@localhost:5433/dsa_test")
os.environ.setdefault("DSA_REDIS_URL", "redis://localhost:6379/1")
# Endpoint tests share Redis db=1; bump rate limits so the middleware doesn't
# trip during normal test runs. Rate-limit *behavior* is exercised in
# tests/test_ratelimit.py with explicit small limits.
os.environ.setdefault("DSA_RATE_LIMIT_PER_MINUTE", "100000")
os.environ.setdefault("DSA_RATE_LIMIT_PER_DAY", "100000")


def _split_db_url(url: str) -> tuple[str, str]:
    """(admin_url_pointing_at_'dsa'_db, test_db_name).

    Connect to a different DB to issue CREATE DATABASE; we use 'dsa' as the
    admin DB since both local docker-compose and the CI postgres service set
    it up as POSTGRES_DB.
    """
    sync_url = url.replace("postgresql+asyncpg://", "postgresql://")
    parsed = urllib.parse.urlparse(sync_url)
    test_db = parsed.path.lstrip("/") or "dsa_test"
    admin = parsed._replace(path="/dsa").geturl()
    return admin, test_db


async def _ensure_test_db(url: str) -> None:
    import asyncpg

    admin_url, test_db = _split_db_url(url)
    if not test_db.endswith("_test"):
        # Refuse to touch anything that isn't clearly a test DB.
        return
    try:
        conn = await asyncpg.connect(admin_url)
    except Exception as e:
        print(f"[conftest] could not connect to postgres for test-db setup: {e}")
        return
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", test_db)
        if not exists:
            # asyncpg can't parameterise DDL identifiers; we control test_db.
            await conn.execute(f'CREATE DATABASE "{test_db}"')
    finally:
        await conn.close()


async def _flush_redis(url: str) -> None:
    import redis.asyncio as aioredis

    client = aioredis.from_url(url)
    try:
        await client.flushdb()
    except Exception as e:
        print(f"[conftest] could not flush redis: {e}")
    finally:
        await client.aclose()


def pytest_sessionstart(session):
    """Ensure dsa_test database exists and Redis test db is clean."""
    asyncio.run(_ensure_test_db(os.environ["DSA_DATABASE_URL"]))
    asyncio.run(_flush_redis(os.environ["DSA_REDIS_URL"]))


@pytest_asyncio.fixture(autouse=True)
async def _reset_redis_cache():
    """Each test gets a fresh redis client on its own event loop AND a clean
    Redis db, so leftover rate-limit and X-Data-Updated-At state doesn't bleed
    across tests.

    redis.asyncio.Redis is loop-bound; the lru_cache in apps.api.deps.get_redis
    would otherwise serve a stale client created on the first test's loop to
    every subsequent test, producing 'attached to a different loop' errors.
    """
    import redis.asyncio as aioredis

    from apps.api import deps
    from core.config import get_settings

    deps.get_redis.cache_clear()
    client = aioredis.from_url(get_settings().redis_url)
    try:
        await client.flushdb()
    finally:
        await client.aclose()
    yield
    deps.get_redis.cache_clear()


@pytest_asyncio.fixture
async def db_session_factory():
    """Drops and recreates the schema for each test. Returns an async_sessionmaker."""
    from core.config import get_settings
    from core.db import Base, make_engine, make_session_factory

    settings = get_settings()
    engine = make_engine(settings.database_url, pool_size=1, max_overflow=0)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    factory = make_session_factory(engine)
    try:
        yield factory
    finally:
        await engine.dispose()
