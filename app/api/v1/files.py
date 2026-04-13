from typing import Any

from fastapi import APIRouter

router = APIRouter()


@router.post("/upload/init")
async def init_upload() -> dict[str, Any]:
    return {
        "ok": True,
        "data": {
            "upload_session_id": 1,
            "files": [],
        },
        "meta": {},
    }


@router.post("/upload/complete")
async def complete_upload() -> dict[str, Any]:
    return {
        "ok": True,
        "data": {
            "completed": True,
        },
        "meta": {},
    }


@router.get("/{attachment_id}/download")
async def download_file(attachment_id: int) -> dict[str, Any]:
    return {
        "ok": True,
        "data": {
            "attachment_id": attachment_id,
            "download_url": "https://example.com/demo",
        },
        "meta": {},
    }


@router.delete("/{attachment_id}")
async def delete_file(attachment_id: int) -> dict[str, Any]:
    return {
        "ok": True,
        "data": {
            "attachment_id": attachment_id,
            "deleted": True,
        },
        "meta": {},
    }
