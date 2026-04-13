from typing import Any

from fastapi import APIRouter

router = APIRouter()


@router.get("/conversations/{conversation_id}/events")
async def get_events(
    conversation_id: int,
    after_event_id: int | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    return {
        "ok": True,
        "data": {
            "conversation_id": conversation_id,
            "after_event_id": after_event_id,
            "limit": limit,
            "items": [],
        },
        "meta": {},
    }
