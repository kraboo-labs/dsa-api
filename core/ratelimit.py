import secrets
import time
from dataclasses import dataclass

import redis.asyncio as aioredis


@dataclass(frozen=True, slots=True)
class LimitConfig:
    name: str
    window_seconds: int
    max_requests: int


@dataclass(frozen=True, slots=True)
class LimitDecision:
    allowed: bool
    config: LimitConfig
    current: int
    retry_after: int  # seconds until oldest request ages out; 0 when allowed


def _key(prefix: str, ip: str, cfg: LimitConfig) -> str:
    return f"{prefix}:{cfg.name}:{ip}"


async def check_limit(
    redis: aioredis.Redis,
    ip: str,
    cfg: LimitConfig,
    *,
    key_prefix: str = "rl",
) -> LimitDecision:
    """Sliding-window rate limit via sorted-set timestamps.

    Not strictly atomic — between the read (zcard) and write (zadd) two
    requests can sneak through over the cap. For 60/min that's an
    acceptable handful of overshoots; the alternative (Lua script) is
    deferred.
    """
    key = _key(key_prefix, ip, cfg)
    now = time.time()
    cutoff = now - cfg.window_seconds

    pipe = redis.pipeline(transaction=False)
    pipe.zremrangebyscore(key, "-inf", cutoff)
    pipe.zcard(key)
    _, count = await pipe.execute()

    if count >= cfg.max_requests:
        oldest = await redis.zrange(key, 0, 0, withscores=True)
        retry_after = (
            max(1, int(oldest[0][1] + cfg.window_seconds - now)) if oldest else cfg.window_seconds
        )
        return LimitDecision(False, cfg, int(count), retry_after)

    # Record this request. Uniquify the member so concurrent same-second
    # calls don't collapse into a single zset entry.
    member = f"{now}:{secrets.token_hex(4)}"
    pipe = redis.pipeline(transaction=False)
    pipe.zadd(key, {member: now})
    pipe.expire(key, cfg.window_seconds + 1)
    await pipe.execute()

    return LimitDecision(True, cfg, int(count) + 1, 0)
