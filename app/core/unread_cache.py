from __future__ import annotations

import logging

import redis.asyncio as redis

from app.core.config import settings

logger = logging.getLogger(__name__)


class UnreadCache:
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

    async def set_conversation_unread(
        self,
        *,
        user_id: int,
        conversation_id: int,
        unread_count: int,
    ) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.set(
                f"unread:user:{user_id}:conversation:{conversation_id}",
                unread_count,
                ex=3600,
            )
        except Exception:
            logger.exception(
                "Failed to set conversation unread",
                extra={"user_id": user_id, "conversation_id": conversation_id},
            )

    async def set_total_unread(
        self,
        *,
        user_id: int,
        unread_count: int,
    ) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.set(
                f"unread:user:{user_id}:total",
                unread_count,
                ex=3600,
            )
        except Exception:
            logger.exception(
                "Failed to set total unread",
                extra={"user_id": user_id},
            )

    async def get_total_unread(self, *, user_id: int) -> int | None:
        if self._redis is None:
            return None
        value = await self._redis.get(f"unread:user:{user_id}:total")
        return int(value) if value is not None else None


unread_cache = UnreadCache()
