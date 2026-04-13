from typing import Any

from fastapi import APIRouter

router = APIRouter()


@router.get("/search")
async def search_users(nickname: str) -> dict[str, Any]:
    return {
        "ok": True,
        "data": {
            "items": [
                {
                    "user_id": 1,
                    "nickname": nickname,
                    "is_online": False,
                    "last_seen_at": None,
                }
            ]
        },
        "meta": {},
    }


@router.get("/{user_id}")
async def get_user(user_id: int) -> dict[str, Any]:
    return {
        "ok": True,
        "data": {
            "user_id": user_id,
            "nickname": "@demo",
        },
        "meta": {},
    }


@router.get("/{user_id}/safety")
async def get_safety(user_id: int) -> dict[str, Any]:
    return {
        "ok": True,
        "data": {
            "user_id": user_id,
            "fingerprint": "ABCD-EFGH-IJKL-MNOP",
            "safety_code": "12345 67890 11223 44556",
        },
        "meta": {},
    }
