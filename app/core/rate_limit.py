from __future__ import annotations

import hashlib
import inspect
import logging
from collections.abc import Awaitable, Callable

import redis.asyncio as redis
from fastapi import Request

from app.core.config import settings
from app.core.exceptions import TooManyRequestsError

logger = logging.getLogger(__name__)

RateKeyBuilder = Callable[[Request], str | Awaitable[str]]


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def default_rate_limit_key_builder(request: Request) -> str:
    ip_address = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("User-Agent", "")
    device_fingerprint = request.headers.get("X-Device-Fingerprint", "")
    device_uuid = request.headers.get("X-Device-UUID", "")
    material = f"{ip_address}|{user_agent}|{device_fingerprint}|{device_uuid}"
    return f"{ip_address}:{_hash_text(material)}"


class RateLimiter:
    def __init__(self) -> None:
        self._redis: redis.Redis | None = None

    async def start(self) -> None:
        if self._redis is not None:
            return
        self._redis = redis.from_url(settings.redis_url, decode_responses=True)

    async def stop(self) -> None:
        if self._redis is not None:
            await self._redis.close()
            self._redis = None

    async def hit(
        self,
        *,
        key: str,
        limit: int,
        window_seconds: int,
    ) -> int:
        if self._redis is None:
            return 1

        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.incr(key)
                pipe.expire(key, window_seconds, nx=True)
                result = await pipe.execute()

            count = int(result[0])
            if count > limit:
                raise TooManyRequestsError(
                    code="RATE_LIMITED",
                    message="Too many requests. Please try again later.",
                    details={
                        "limit": limit,
                        "window_seconds": window_seconds,
                    },
                )
            return count
        except TooManyRequestsError:
            raise
        except Exception:
            logger.exception("Rate limiter backend failure", extra={"key": key})
            # fail-open
            return 0


rate_limiter = RateLimiter()


def rate_limit_dependency(
    *,
    prefix: str,
    limit: int,
    window_seconds: int,
    key_builder: RateKeyBuilder | None = None,
) -> Callable[[Request], Awaitable[None]]:
    async def dependency(request: Request) -> None:
        builder = key_builder or default_rate_limit_key_builder
        maybe_key = builder(request)
        key_suffix = await maybe_key if inspect.isawaitable(maybe_key) else maybe_key
        await rate_limiter.hit(
            key=f"rl:{prefix}:{key_suffix}",
            limit=limit,
            window_seconds=window_seconds,
        )

    return dependency
