import os
import subprocess

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


def pytest_sessionstart(session):
    """Ensure dsa_test database exists. Idempotent."""
    check = subprocess.run(
        [
            "docker",
            "exec",
            "dsa-postgres",
            "psql",
            "-U",
            "dsa",
            "-d",
            "dsa",
            "-tAc",
            "SELECT 1 FROM pg_database WHERE datname='dsa_test'",
        ],
        capture_output=True,
        text=True,
    )
    if check.returncode != 0:
        # docker isn't up or container missing — leave it to tests that need DB to fail loudly.
        return
    if not check.stdout.strip():
        subprocess.run(
            [
                "docker",
                "exec",
                "dsa-postgres",
                "psql",
                "-U",
                "dsa",
                "-d",
                "dsa",
                "-c",
                "CREATE DATABASE dsa_test",
            ],
            check=True,
        )

    # Wipe Redis db=1 so leftover rate-limit keys from prior runs don't bleed
    # into this session.
    subprocess.run(
        ["docker", "exec", "dsa-redis", "redis-cli", "-n", "1", "FLUSHDB"],
        capture_output=True,
        check=False,
    )


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
