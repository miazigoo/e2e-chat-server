import asyncio
from datetime import datetime, timezone

from sqlalchemy import delete, select

from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.core.push import (
    build_device_approval_push_payload,
    build_new_message_push_payload,
    send_push_data_message,
)
from app.core.realtime import realtime_hub
from app.core.storage import delete_object_if_exists, move_object
from app.core.unread_cache import unread_cache
from app.models.attachment import Attachment, UploadSession
from app.models.auth_email_code import AuthEmailCode
from app.models.chat_enums import AttachmentStatus, UploadSessionStatus
from app.models.message import Message
from app.repositories.auth_sessions import AuthSessionsRepository
from app.repositories.conversations import ConversationsRepository
from app.repositories.devices import DevicesRepository
from app.services.account_purge_service import purge_account
from app.worker.celery_app import celery_app

auth_sessions_repo = AuthSessionsRepository()
devices_repo = DevicesRepository()
conversations_repo = ConversationsRepository()


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _cleanup_expired_auth_sessions_impl() -> int:
    async with AsyncSessionLocal() as session:
        deleted = await auth_sessions_repo.delete_expired(
            session,
            now_dt=_now(),
        )
        await session.commit()
        return deleted


@celery_app.task(name="app.worker.tasks.cleanup_expired_auth_sessions")
def cleanup_expired_auth_sessions() -> int:
    return asyncio.run(_cleanup_expired_auth_sessions_impl())


async def _cleanup_expired_email_codes_impl() -> int:
    async with AsyncSessionLocal() as session:
        stmt = (
            delete(AuthEmailCode)
            .where(AuthEmailCode.expires_at <= _now())
            .returning(AuthEmailCode.id)
        )
        result = await session.execute(stmt)
        deleted = len(result.scalars().all())
        await session.commit()
        return deleted


@celery_app.task(name="app.worker.tasks.cleanup_expired_email_codes")
def cleanup_expired_email_codes() -> int:
    return asyncio.run(_cleanup_expired_email_codes_impl())


async def _cleanup_expired_upload_sessions_impl() -> dict[str, int]:
    async with AsyncSessionLocal() as session:
        now_dt = _now()

        result = await session.execute(
            select(UploadSession).where(
                UploadSession.completed_at.is_(None),
                UploadSession.expires_at <= now_dt,
                UploadSession.status.in_(
                    [
                        UploadSessionStatus.INIT,
                        UploadSessionStatus.UPLOADING,
                    ]
                ),
            )
        )
        sessions = list(result.scalars().all())

        expired_session_ids = [item.id for item in sessions]

        for upload_session in sessions:
            upload_session.status = UploadSessionStatus.EXPIRED

        attachments_result = await session.execute(
            select(Attachment).where(
                Attachment.upload_session_id.in_(expired_session_ids or [-1]),
                Attachment.message_id.is_(None),
                Attachment.deleted_at.is_(None),
            )
        )
        attachments = list(attachments_result.scalars().all())

        for attachment in attachments:
            attachment.deleted_at = now_dt
            attachment.upload_status = AttachmentStatus.DELETED

        await session.commit()

        return {
            "expired_sessions": len(sessions),
            "marked_deleted_attachments": len(attachments),
        }


@celery_app.task(name="app.worker.tasks.cleanup_expired_upload_sessions")
def cleanup_expired_upload_sessions() -> dict[str, int]:
    return asyncio.run(_cleanup_expired_upload_sessions_impl())


async def _mark_expired_messages_impl() -> dict[str, int]:
    async with AsyncSessionLocal() as session:
        now_dt = _now()

        result = await session.execute(
            select(Message).where(
                Message.expires_at <= now_dt,
                Message.is_deleted_global.is_(False),
            )
        )
        messages = list(result.scalars().all())
        message_ids = [message.id for message in messages]

        for message in messages:
            message.is_deleted_global = True
            message.deleted_global_at = now_dt

        attachments: list[Attachment] = []
        if message_ids:
            attachments_result = await session.execute(
                select(Attachment).where(
                    Attachment.message_id.in_(message_ids),
                    Attachment.deleted_at.is_(None),
                )
            )
            attachments = list(attachments_result.scalars().all())

            for attachment in attachments:
                attachment.deleted_at = now_dt
                attachment.upload_status = AttachmentStatus.DELETED

        await session.commit()
        return {
            "expired_messages": len(messages),
            "deleted_attachments": len(attachments),
        }


@celery_app.task(name="app.worker.tasks.mark_expired_messages")
def mark_expired_messages() -> dict[str, int]:
    return asyncio.run(_mark_expired_messages_impl())


async def _purge_account_impl(user_id: int, reason: str) -> dict[str, int | bool]:
    async with AsyncSessionLocal() as session:
        result = await purge_account(
            session,
            user_id=user_id,
            reason=reason,
        )
        await session.commit()
        return result


@celery_app.task(name="app.worker.tasks.purge_account_task")
def purge_account_task(user_id: int, reason: str) -> dict[str, int | bool]:
    return asyncio.run(_purge_account_impl(user_id, reason))


async def _send_new_message_push_impl(
    user_id: int,
    conversation_id: int,
    message_id: int,
) -> dict[str, str | bool | int]:
    async with AsyncSessionLocal() as session:
        devices = await devices_repo.list_active_by_user_id(
            session,
            user_id=user_id,
        )
        devices = [device for device in devices if device.fcm_token]
        if not devices:
            return {
                "sent": False,
                "user_id": user_id,
                "reason": "device_not_ready",
            }

        sent = 0
        for device in devices:
            push_id = send_push_data_message(
                token=device.fcm_token or "",
                data=build_new_message_push_payload(
                    conversation_id=conversation_id,
                    message_id=message_id,
                ),
            )
            if push_id is not None:
                sent += 1

        return {
            "sent": sent > 0,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "devices_targeted": len(devices),
            "devices_sent": sent,
        }


@celery_app.task(name="app.worker.tasks.send_new_message_push_task")
def send_new_message_push_task(
    user_id: int,
    conversation_id: int,
    message_id: int,
) -> dict[str, str | bool | int]:
    return asyncio.run(
        _send_new_message_push_impl(user_id, conversation_id, message_id)
    )


async def _send_device_approval_push_impl(
    user_id: int,
    request_id: str,
) -> dict[str, str | bool | int]:
    async with AsyncSessionLocal() as session:
        devices = await devices_repo.list_active_by_user_id(
            session,
            user_id=user_id,
        )
        devices = [device for device in devices if device.fcm_token]
        if not devices:
            return {
                "sent": False,
                "user_id": user_id,
                "request_id": request_id,
                "reason": "device_not_ready",
            }

        sent = 0
        for device in devices:
            push_id = send_push_data_message(
                token=device.fcm_token or "",
                data=build_device_approval_push_payload(request_id=request_id),
            )
            if push_id is not None:
                sent += 1

        return {
            "sent": sent > 0,
            "user_id": user_id,
            "request_id": request_id,
            "devices_targeted": len(devices),
            "devices_sent": sent,
        }


@celery_app.task(name="app.worker.tasks.send_device_approval_push_task")
def send_device_approval_push_task(
    user_id: int,
    request_id: str,
) -> dict[str, str | bool | int]:
    return asyncio.run(_send_device_approval_push_impl(user_id, request_id))


async def _recompute_unread_counters_for_user_impl(user_id: int) -> dict[str, int]:
    async with AsyncSessionLocal() as session:
        await unread_cache.start()
        try:
            overview = await conversations_repo.list_overview_for_user(
                session,
                user_id=user_id,
            )
            total = 0
            for row in overview:
                conversation = row["conversation"]
                unread_count = int(row["unread_count"])
                total += unread_count
                await unread_cache.set_conversation_unread(
                    user_id=user_id,
                    conversation_id=conversation.id,
                    unread_count=unread_count,
                )

            await unread_cache.set_total_unread(
                user_id=user_id,
                unread_count=total,
            )
            return {
                "user_id": user_id,
                "total_unread": total,
                "conversation_count": len(overview),
            }
        finally:
            await unread_cache.stop()


@celery_app.task(name="app.worker.tasks.recompute_unread_counters_for_user_task")
def recompute_unread_counters_for_user_task(user_id: int) -> dict[str, int]:
    return asyncio.run(_recompute_unread_counters_for_user_impl(user_id))


async def _reconcile_presence_last_seen_impl() -> int:
    await realtime_hub.start()
    try:
        async with AsyncSessionLocal() as session:
            user_ids = await realtime_hub.list_active_user_ids()
            updated = 0

            for user_id in user_ids:
                last_seen_raw = await realtime_hub.get_last_seen(user_id)
                if not last_seen_raw:
                    continue

                device = await devices_repo.get_active_by_user_id(
                    session,
                    user_id=user_id,
                )
                if device is None:
                    continue

                try:
                    last_seen_dt = datetime.fromisoformat(last_seen_raw)
                except ValueError:
                    continue

                await devices_repo.touch_last_seen(
                    session,
                    device=device,
                    seen_at=last_seen_dt,
                )
                updated += 1

            await session.commit()
            return updated
    finally:
        await realtime_hub.stop()


@celery_app.task(name="app.worker.tasks.reconcile_presence_last_seen")
def reconcile_presence_last_seen() -> int:
    return asyncio.run(_reconcile_presence_last_seen_impl())


async def _delete_marked_attachment_objects_impl() -> dict[str, int]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Attachment).where(Attachment.deleted_at.is_not(None))
        )
        attachments = list(result.scalars().all())

        deleted_objects = 0
        for attachment in attachments:
            removed = await delete_object_if_exists(
                bucket_name=attachment.bucket_name,
                object_name=attachment.storage_key,
            )
            if removed:
                deleted_objects += 1

        return {
            "attachments_checked": len(attachments),
            "objects_deleted": deleted_objects,
        }


@celery_app.task(name="app.worker.tasks.delete_marked_attachment_objects")
def delete_marked_attachment_objects() -> dict[str, int]:
    return asyncio.run(_delete_marked_attachment_objects_impl())


async def _migrate_legacy_temp_attachments_impl() -> dict[str, int]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Attachment).where(
                Attachment.bucket_name == settings.minio_bucket_temp,
                Attachment.deleted_at.is_(None),
            )
        )
        attachments = list(result.scalars().all())

        migrated = 0
        for attachment in attachments:
            await move_object(
                src_bucket_name=attachment.bucket_name,
                src_object_name=attachment.storage_key,
                dst_bucket_name=settings.minio_bucket_attachments,
                dst_object_name=attachment.storage_key,
            )
            attachment.bucket_name = settings.minio_bucket_attachments
            migrated += 1

        await session.commit()

        return {
            "checked": len(attachments),
            "migrated": migrated,
        }


@celery_app.task(name="app.worker.tasks.migrate_legacy_temp_attachments")
def migrate_legacy_temp_attachments() -> dict[str, int]:
    return asyncio.run(_migrate_legacy_temp_attachments_impl())
