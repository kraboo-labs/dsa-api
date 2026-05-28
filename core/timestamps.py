from datetime import datetime

import redis.asyncio as aioredis

# Last successful scrape completion time, written by the scraper and read by
# the API middleware. Keyspace is shared between scraper and API.
_KEY = "dsa:last_scrape_completed_at"


async def write_data_updated_at(redis: aioredis.Redis, when: datetime) -> None:
    await redis.set(_KEY, when.isoformat())


async def read_data_updated_at(redis: aioredis.Redis) -> str | None:
    raw = await redis.get(_KEY)
    if raw is None:
        return None
    if isinstance(raw, bytes):
        return raw.decode("utf-8")
    return raw
