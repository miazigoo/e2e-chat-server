import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import redis.asyncio as redis

from app.core.config import settings

logger = logging.getLogger(__name__)

UserEventHandler = Callable[[int, dict[str, Any]], Awaitable[None]]
ConversationEventHandler = Callable[[int, dict[str, Any]], Awaitable[None]]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RealtimeHub:
    def __init__(self) -> None:
        self._redis: redis.Redis | None = None
        self._pubsub: redis.client.PubSub | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._on_user_event: UserEventHandler | None = None
        self._on_conversation_event: ConversationEventHandler | None = None

    def configure(
        self,
        *,
        on_user_event: UserEventHandler,
        on_conversation_event: ConversationEventHandler,
    ) -> None:
        self._on_user_event = on_user_event
        self._on_conversation_event = on_conversation_event

    async def start(self) -> None:
        if self._reader_task is not None:
            return

        self._redis = redis.from_url(settings.redis_url, decode_responses=True)
        self._pubsub = self._redis.pubsub()

        await self._pubsub.psubscribe("realtime:user:*", "realtime:conversation:*")
        self._reader_task = asyncio.create_task(self._reader_loop())

        logger.info("Realtime hub started")

    async def stop(self) -> None:
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None

        if self._pubsub is not None:
            await self._pubsub.close()
            self._pubsub = None

        if self._redis is not None:
            await self._redis.close()
            self._redis = None

        logger.info("Realtime hub stopped")

    async def _reader_loop(self) -> None:
        assert self._pubsub is not None

        try:
            while True:
                message = await self._pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0,
                )
                if message is None:
                    await asyncio.sleep(0.05)
                    continue

                channel = message.get("channel")
                raw_data = message.get("data")

                if not isinstance(channel, str) or not isinstance(raw_data, str):
                    continue

                try:
                    payload = json.loads(raw_data)
                except json.JSONDecodeError:
                    logger.warning(
                        "Invalid realtime payload", extra={"channel": channel}
                    )
                    continue

                try:
                    if channel.startswith("realtime:user:"):
                        user_id = int(channel.rsplit(":", 1)[-1])
                        if self._on_user_event is not None:
                            await self._on_user_event(user_id, payload)

                    elif channel.startswith("realtime:conversation:"):
                        conversation_id = int(channel.rsplit(":", 1)[-1])
                        if self._on_conversation_event is not None:
                            await self._on_conversation_event(conversation_id, payload)

                except Exception:
                    logger.exception(
                        "Failed to process realtime message",
                        extra={"channel": channel},
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Realtime reader loop crashed")
            raise

    async def publish_user_event(
        self,
        user_id: int,
        payload: dict[str, Any],
    ) -> None:
        if self._redis is None:
            return

        try:
            await self._redis.publish(
                f"realtime:user:{user_id}",
                json.dumps(payload, default=str, ensure_ascii=False),
            )
        except Exception:
            logger.exception(
                "Failed to publish user realtime event",
                extra={"user_id": user_id},
            )

    async def publish_conversation_event(
        self,
        conversation_id: int,
        payload: dict[str, Any],
    ) -> None:
        if self._redis is None:
            return

        try:
            await self._redis.publish(
                f"realtime:conversation:{conversation_id}",
                json.dumps(payload, default=str, ensure_ascii=False),
            )
        except Exception:
            logger.exception(
                "Failed to publish conversation realtime event",
                extra={"conversation_id": conversation_id},
            )

    async def refresh_presence(
        self,
        *,
        user_id: int,
        device_id: int,
    ) -> None:
        if self._redis is None:
            return

        try:
            async with self._redis.pipeline(transaction=False) as pipe:
                pipe.set(f"presence:user:{user_id}", "online", ex=90)
                pipe.set(f"presence:device:{device_id}", "online", ex=90)
                pipe.set(
                    f"presence:last_seen:{user_id}", _now_iso(), ex=60 * 60 * 24 * 7
                )
                pipe.sadd("presence:active_users", user_id)
                await pipe.execute()
        except Exception:
            logger.exception(
                "Failed to refresh presence",
                extra={"user_id": user_id, "device_id": device_id},
            )

    async def mark_offline(
        self,
        *,
        user_id: int,
        device_id: int,
    ) -> None:
        if self._redis is None:
            return

        try:
            async with self._redis.pipeline(transaction=False) as pipe:
                pipe.delete(f"presence:user:{user_id}")
                pipe.delete(f"presence:device:{device_id}")
                pipe.srem("presence:active_users", user_id)
                pipe.set(
                    f"presence:last_seen:{user_id}",
                    _now_iso(),
                    ex=60 * 60 * 24 * 7,
                )
                await pipe.execute()
        except Exception:
            logger.exception(
                "Failed to mark offline",
                extra={"user_id": user_id, "device_id": device_id},
            )

    async def list_active_user_ids(self) -> list[int]:
        if self._redis is None:
            return []

        try:
            raw_values = await self._redis.smembers("presence:active_users")
            return [int(value) for value in raw_values]
        except Exception:
            logger.exception("Failed to list active users")
            return []

    async def get_last_seen(self, user_id: int) -> str | None:
        if self._redis is None:
            return None

        try:
            return await self._redis.get(f"presence:last_seen:{user_id}")
        except Exception:
            logger.exception(
                "Failed to get presence:last_seen", extra={"user_id": user_id}
            )
            return None


realtime_hub = RealtimeHub()
