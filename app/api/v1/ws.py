from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.db import AsyncSessionLocal
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.realtime import realtime_hub
from app.dependencies.auth import resolve_access_session
from app.repositories.conversations import ConversationsRepository
from app.repositories.devices import DevicesRepository
from app.repositories.users import UsersRepository

router = APIRouter()

users_repo = UsersRepository()
devices_repo = DevicesRepository()
conversations_repo = ConversationsRepository()


class WebSocketManager:
    def __init__(self) -> None:
        self._user_connections: dict[int, set[WebSocket]] = defaultdict(set)
        self._conversation_connections: dict[int, set[WebSocket]] = defaultdict(set)
        self._meta: dict[WebSocket, dict[str, int]] = {}

    async def connect(
        self,
        websocket: WebSocket,
        *,
        user_id: int,
        device_id: int,
    ) -> None:
        await websocket.accept()
        self._user_connections[user_id].add(websocket)
        self._meta[websocket] = {
            "user_id": user_id,
            "device_id": device_id,
        }

    def disconnect(self, websocket: WebSocket) -> dict[str, int] | None:
        meta = self._meta.pop(websocket, None)
        if meta is None:
            return None

        user_id = meta["user_id"]
        if user_id in self._user_connections:
            self._user_connections[user_id].discard(websocket)
            if not self._user_connections[user_id]:
                self._user_connections.pop(user_id, None)

        to_cleanup: list[int] = []
        for conversation_id, connections in self._conversation_connections.items():
            connections.discard(websocket)
            if not connections:
                to_cleanup.append(conversation_id)

        for conversation_id in to_cleanup:
            self._conversation_connections.pop(conversation_id, None)

        return meta

    def subscribe(self, websocket: WebSocket, conversation_id: int) -> None:
        self._conversation_connections[conversation_id].add(websocket)

    def unsubscribe(self, websocket: WebSocket, conversation_id: int) -> None:
        if conversation_id in self._conversation_connections:
            self._conversation_connections[conversation_id].discard(websocket)
            if not self._conversation_connections[conversation_id]:
                self._conversation_connections.pop(conversation_id, None)

    async def send_personal(self, user_id: int, payload: dict[str, Any]) -> None:
        for websocket in list(self._user_connections.get(user_id, set())):
            await websocket.send_json(payload)

    async def send_conversation(
        self,
        conversation_id: int,
        payload: dict[str, Any],
    ) -> None:
        for websocket in list(
            self._conversation_connections.get(conversation_id, set())
        ):
            await websocket.send_json(payload)


manager = WebSocketManager()


def bind_realtime_handlers() -> None:
    realtime_hub.configure(
        on_user_event=manager.send_personal,
        on_conversation_event=manager.send_conversation,
    )


def _extract_bearer_token(websocket: WebSocket) -> str | None:
    token = websocket.query_params.get("token")
    if token:
        return token

    auth_header = websocket.headers.get("Authorization")
    if not auth_header:
        return None

    prefix = "Bearer "
    if auth_header.startswith(prefix):
        return auth_header[len(prefix) :]

    return None


async def _close_unauthorized(websocket: WebSocket, code: int, reason: str) -> None:
    await websocket.close(code=code, reason=reason)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    token = _extract_bearer_token(websocket)
    device_uuid = websocket.headers.get("X-Device-UUID") or websocket.query_params.get(
        "device_uuid"
    )

    if not token:
        await _close_unauthorized(websocket, 4401, "Access token is required")
        return

    if not device_uuid:
        await _close_unauthorized(websocket, 4400, "device_uuid is required")
        return

    connected_meta: dict[str, int] | None = None

    try:
        async with AsyncSessionLocal() as session:
            auth_session, _ = await resolve_access_session(session, token)

            user = await users_repo.get_by_id(session, auth_session.user_id)
            if (
                user is None
                or user.is_deleted
                or user.pending_deletion
                or not user.is_active
                or user.is_frozen
            ):
                raise ForbiddenError(
                    code="ACCOUNT_UNAVAILABLE",
                    message="Account unavailable",
                )

            device = await devices_repo.get_by_user_and_uuid(
                session,
                user_id=user.id,
                device_uuid=device_uuid,
            )
            if (
                device is None
                or not device.is_active
                or device.revoked_at is not None
                or device.id != auth_session.device_id
            ):
                raise ForbiddenError(
                    code="DEVICE_SESSION_MISMATCH",
                    message="Device does not match active session",
                )

            await manager.connect(
                websocket,
                user_id=user.id,
                device_id=device.id,
            )
            connected_meta = {"user_id": user.id, "device_id": device.id}

            await realtime_hub.refresh_presence(
                user_id=user.id,
                device_id=device.id,
            )

            await websocket.send_json(
                {
                    "type": "connected",
                    "user_id": user.id,
                    "device_id": device.id,
                    "session_id": auth_session.session_id,
                }
            )

            while True:
                data = await websocket.receive_json()
                event_type = data.get("type")

                if event_type == "ping":
                    await realtime_hub.refresh_presence(
                        user_id=user.id,
                        device_id=device.id,
                    )
                    await websocket.send_json({"type": "pong"})
                    continue

                if event_type == "whoami":
                    await websocket.send_json(
                        {
                            "type": "whoami",
                            "user_id": user.id,
                            "device_id": device.id,
                            "session_id": auth_session.session_id,
                        }
                    )
                    continue

                if event_type == "subscribe_conversation":
                    conversation_id_raw = data.get("conversation_id")
                    if not isinstance(conversation_id_raw, int):
                        await websocket.send_json(
                            {
                                "type": "error",
                                "code": "INVALID_CONVERSATION_ID",
                                "message": "conversation_id must be an integer",
                            }
                        )
                        continue

                    async with AsyncSessionLocal() as check_session:
                        conversation = await conversations_repo.get_for_user(
                            check_session,
                            conversation_id=conversation_id_raw,
                            user_id=user.id,
                        )
                        if conversation is None:
                            await websocket.send_json(
                                {
                                    "type": "error",
                                    "code": "CONVERSATION_NOT_FOUND",
                                    "message": "Conversation not found",
                                }
                            )
                            continue

                    manager.subscribe(websocket, conversation_id_raw)
                    await websocket.send_json(
                        {
                            "type": "subscribed",
                            "conversation_id": conversation_id_raw,
                        }
                    )
                    continue

                if event_type == "unsubscribe_conversation":
                    conversation_id_raw = data.get("conversation_id")
                    if isinstance(conversation_id_raw, int):
                        manager.unsubscribe(websocket, conversation_id_raw)

                    await websocket.send_json(
                        {
                            "type": "unsubscribed",
                            "conversation_id": conversation_id_raw,
                        }
                    )
                    continue

                await websocket.send_json(
                    {
                        "type": "error",
                        "code": "UNKNOWN_EVENT_TYPE",
                        "message": "Unsupported websocket message type",
                    }
                )

    except (UnauthorizedError, ForbiddenError) as exc:
        await _close_unauthorized(websocket, 4403, exc.message)
    except WebSocketDisconnect:
        pass
    except Exception:
        try:
            await websocket.close(code=1011, reason="Internal websocket error")
        except RuntimeError:
            pass
    finally:
        meta = manager.disconnect(websocket) or connected_meta
        if meta is not None:
            await realtime_hub.mark_offline(
                user_id=meta["user_id"],
                device_id=meta["device_id"],
            )
