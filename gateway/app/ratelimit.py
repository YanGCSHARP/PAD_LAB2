"""Fixed-window rate limiter backed by Redis (shared between gateway replicas)."""

import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Protocol

from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)


@dataclass
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    reset_seconds: int

    def headers(self) -> dict[str, str]:
        return {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(self.remaining),
            "X-RateLimit-Reset": str(self.reset_seconds),
        }


class RateLimiter(Protocol):
    async def hit(self, key: str, limit: int, window: int = 60) -> RateLimitResult: ...

    async def ping(self) -> None: ...

    async def close(self) -> None: ...


class RedisRateLimiter:
    def __init__(self, url: str) -> None:
        self.redis = Redis.from_url(url, socket_timeout=1.0, socket_connect_timeout=1.0)

    async def hit(self, key: str, limit: int, window: int = 60) -> RateLimitResult:
        now = time.time()
        bucket = int(now // window)
        redis_key = f"ratelimit:{key}:{bucket}"
        reset = window - int(now % window)
        try:
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.incr(redis_key)
                pipe.expire(redis_key, window + 1)
                count, _ = await pipe.execute()
        except (RedisError, OSError) as exc:
            # Fail-open: an outage of the limiter must not take the whole API down.
            logger.warning("Rate limiter unavailable, allowing request", extra={"error": repr(exc)})
            return RateLimitResult(True, limit, limit, reset)
        return RateLimitResult(count <= limit, limit, max(0, limit - count), reset)

    async def ping(self) -> None:
        await self.redis.ping()

    async def close(self) -> None:
        await self.redis.aclose()


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self.counters: dict[str, int] = defaultdict(int)

    async def hit(self, key: str, limit: int, window: int = 60) -> RateLimitResult:
        bucket_key = f"{key}:{int(time.time() // window)}"
        self.counters[bucket_key] += 1
        count = self.counters[bucket_key]
        return RateLimitResult(count <= limit, limit, max(0, limit - count), window)

    async def ping(self) -> None:
        return None

    async def close(self) -> None:
        return None
