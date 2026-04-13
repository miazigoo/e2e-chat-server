from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_enums import EncryptionMode, MessageType, ProtectionMode
from app.models.conversation import Conversation, ConversationParticipant
from app.models.device import Device
from app.models.device_prekey import DevicePreKey
from app.models.message import Message
from app.models.user import User


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


async def create_user(
    session: AsyncSession,
    *,
    nickname: str,
    password_hash: str = "hashed-password",
    email: str | None = None,
    email_2fa_enabled: bool = False,
) -> User:
    user = User(
        nickname=nickname,
        password_hash=password_hash,
        email=email,
        email_2fa_enabled=email_2fa_enabled,
    )
    session.add(user)
    await session.flush()
    return user


async def create_device(
    session: AsyncSession,
    *,
    user_id: int,
    device_uuid: str | None = None,
    device_name: str = "Android",
    platform: str = "android",
    app_version: str = "1.0.0",
    fcm_token: str | None = None,
    is_active: bool = True,
) -> Device:
    real_device_uuid = device_uuid or str(uuid4())

    device = Device(
        user_id=user_id,
        device_uuid=real_device_uuid,
        device_name=device_name,
        platform=platform,
        app_version=app_version,
        fcm_token=fcm_token,
        public_identity_key=f"identity-{real_device_uuid}",
        public_signing_key=f"signing-{real_device_uuid}",
        signed_prekey=f"signed-{real_device_uuid}",
        signed_prekey_signature=f"signature-{real_device_uuid}",
        is_active=is_active,
    )
    session.add(device)
    await session.flush()
    return device


async def create_prekey(
    session: AsyncSession,
    *,
    device_id: int,
    prekey_id: int,
    public_prekey: str,
    is_used: bool = False,
) -> DevicePreKey:
    prekey = DevicePreKey(
        device_id=device_id,
        prekey_id=prekey_id,
        public_prekey=public_prekey,
        is_used=is_used,
    )
    session.add(prekey)
    await session.flush()
    return prekey


async def create_conversation(
    session: AsyncSession,
    *,
    user_a_id: int,
    user_b_id: int,
    created_by_user_id: int,
    title: str | None = None,
    protection_mode: ProtectionMode = ProtectionMode.NORMAL,
    message_ttl_days: int | None = 60,
    delete_after_read_seconds: int | None = None,
) -> Conversation:
    conversation = Conversation(
        user_a_id=min(user_a_id, user_b_id),
        user_b_id=max(user_a_id, user_b_id),
        created_by_user_id=created_by_user_id,
        title=title,
        protection_mode=protection_mode,
        message_ttl_days=message_ttl_days,
        delete_after_read_seconds=delete_after_read_seconds,
    )
    session.add(conversation)
    await session.flush()

    session.add(
        ConversationParticipant(
            conversation_id=conversation.id,
            user_id=user_a_id,
        )
    )
    session.add(
        ConversationParticipant(
            conversation_id=conversation.id,
            user_id=user_b_id,
        )
    )
    await session.flush()

    return conversation


async def create_message(
    session: AsyncSession,
    *,
    conversation_id: int,
    sender_user_id: int,
    sender_device_id: int,
    recipient_user_id: int,
    recipient_device_id: int,
    ciphertext: str = "ciphertext",
) -> Message:
    message = Message(
        conversation_id=conversation_id,
        sender_user_id=sender_user_id,
        sender_device_id=sender_device_id,
        recipient_user_id=recipient_user_id,
        recipient_device_id=recipient_device_id,
        message_type=MessageType.TEXT,
        ciphertext=ciphertext,
        ciphertext_version=1,
        encryption_mode=EncryptionMode.SIGNAL,
        nonce="nonce",
        client_created_at=now_utc(),
        expires_at=now_utc(),
        has_attachments=False,
    )
    session.add(message)
    await session.flush()
    return message
