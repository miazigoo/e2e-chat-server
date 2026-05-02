from types import SimpleNamespace
from typing import Any, cast

import pytest

import app.services.attachment_service as attachment_service
from app.core.exceptions import NotFoundError


@pytest.mark.asyncio
async def test_get_attachment_metadata_returns_presigned_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attachment = SimpleNamespace(
        id=1,
        attachment_uuid="att-1",
        message_id=10,
        encrypted_file_name="f.enc",
        encrypted_metadata={"k": "v"},
        file_size=123,
        mime_hint="application/octet-stream",
        sha256_encrypted_blob="a" * 64,
        bucket_name="bucket",
        storage_key="attachments/key",
        upload_status=SimpleNamespace(value="linked"),
        created_at="2026-01-01T00:00:00+00:00",
        expires_at=None,
        deleted_at=None,
    )

    async def fake_get_attachment_for_user(
        session: Any,
        attachment_id: int,
        user_id: int,
    ) -> Any:
        return attachment

    class FakeMinio:
        def presigned_get_object(
            self,
            bucket_name: str,
            object_name: str,
            expires: int,
        ) -> str:
            return f"https://minio.local/{bucket_name}/{object_name}?exp={expires}"

    monkeypatch.setattr(
        attachment_service.files_repo,
        "get_attachment_for_user",
        fake_get_attachment_for_user,
    )

    async def fake_build_presigned_get_url(
        *,
        bucket_name: str,
        object_name: str,
    ) -> str:
        return f"https://minio.local/{bucket_name}/{object_name}"

    monkeypatch.setattr(
        attachment_service,
        "build_presigned_get_url",
        fake_build_presigned_get_url,
    )

    async def fake_list_tags_for_attachments(
        session: Any,
        attachment_ids: list[int],
    ) -> dict[int, list[Any]]:
        return {}

    monkeypatch.setattr(
        attachment_service.media_tags_repo,
        "list_tags_for_attachments",
        fake_list_tags_for_attachments,
    )

    result = await attachment_service.get_attachment_metadata(
        cast(Any, SimpleNamespace()),
        current_user=cast(Any, SimpleNamespace(id=1)),
        attachment_id=1,
    )

    assert result.can_download is True
    assert result.download_url is not None
    assert "https://minio.local/" in result.download_url


@pytest.mark.asyncio
async def test_list_attachments_for_messages_groups_by_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attachment_a = SimpleNamespace(
        id=11,
        attachment_uuid="att-11",
        message_id=100,
        encrypted_file_name="a.enc",
        encrypted_metadata=None,
        file_size=10,
        mime_hint="text/plain",
        sha256_encrypted_blob="a" * 64,
        bucket_name="bucket",
        storage_key="a",
        upload_status=SimpleNamespace(value="linked"),
        created_at="2026-01-01T00:00:00+00:00",
        expires_at=None,
        deleted_at=None,
    )
    attachment_b = SimpleNamespace(
        id=12,
        attachment_uuid="att-12",
        message_id=101,
        encrypted_file_name="b.enc",
        encrypted_metadata=None,
        file_size=20,
        mime_hint="image/png",
        sha256_encrypted_blob="b" * 64,
        bucket_name="bucket",
        storage_key="b",
        upload_status=SimpleNamespace(value="linked"),
        created_at="2026-01-01T00:00:00+00:00",
        expires_at=None,
        deleted_at=None,
    )

    async def fake_list_message_attachments_for_user_batch(
        session: Any,
        message_ids: list[int],
        user_id: int,
    ) -> list[Any]:
        assert message_ids == [100, 101, 102]
        return [attachment_a, attachment_b]

    async def fake_list_tags_for_attachments(
        session: Any,
        attachment_ids: list[int],
    ) -> dict[int, list[Any]]:
        return {}

    monkeypatch.setattr(
        attachment_service.files_repo,
        "list_message_attachments_for_user_batch",
        fake_list_message_attachments_for_user_batch,
    )
    monkeypatch.setattr(
        attachment_service.media_tags_repo,
        "list_tags_for_attachments",
        fake_list_tags_for_attachments,
    )

    result = await attachment_service.list_attachments_for_messages(
        cast(Any, SimpleNamespace()),
        current_user=cast(Any, SimpleNamespace(id=1)),
        message_ids=[100, 101, 102],
    )

    assert [group.message_id for group in result.items] == [100, 101, 102]
    assert [item.attachment_id for item in result.items[0].items] == [11]
    assert [item.attachment_id for item in result.items[1].items] == [12]
    assert result.items[2].items == []


@pytest.mark.asyncio
async def test_get_attachment_metadata_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_attachment_for_user(
        session: Any,
        attachment_id: int,
        user_id: int,
    ) -> Any:
        return None

    monkeypatch.setattr(
        attachment_service.files_repo,
        "get_attachment_for_user",
        fake_get_attachment_for_user,
    )

    with pytest.raises(NotFoundError) as exc:
        await attachment_service.get_attachment_metadata(
            cast(Any, SimpleNamespace()),
            current_user=cast(Any, SimpleNamespace(id=1)),
            attachment_id=999,
        )

    assert exc.value.code == "ATTACHMENT_NOT_FOUND"
