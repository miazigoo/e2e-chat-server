from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Index, Integer, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.chat_enums import EventType, ProtectionMode


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_uuid: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        nullable=False,
        unique=True,
        server_default=text("gen_random_uuid()"),
    )

    user_a_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_b_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    protection_mode: Mapped[ProtectionMode] = mapped_column(
        SAEnum(
            ProtectionMode,
            name="protection_mode_enum",
            native_enum=True,
            validate_strings=True,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        default=ProtectionMode.NORMAL,
    )
    message_ttl_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delete_after_read_seconds: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    pinned_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_saved_messages: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    is_purged: Mapped[bool] = mapped_column(nullable=False, default=False)
    purged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "("
            "(is_saved_messages = TRUE AND user_a_id = user_b_id)"
            " OR "
            "(is_saved_messages = FALSE AND user_a_id <> user_b_id)"
            ")",
            name="ck_conversations_user_shape",
        ),
        Index("ix_conversations_user_a", "user_a_id"),
        Index("ix_conversations_user_b", "user_b_id"),
        Index("ix_conversations_pair", "user_a_id", "user_b_id"),
        Index("ix_conversations_updated_at", "updated_at"),
        Index("ix_conversations_pinned_message_id", "pinned_message_id"),
        Index("ix_conversations_is_saved_messages", "is_saved_messages"),
    )


class ConversationParticipant(Base):
    __tablename__ = "conversation_participants"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    last_read_message_id: Mapped[int | None] = mapped_column(nullable=True)
    last_read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cleared_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    shared_secret_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    shared_secret_fingerprint: Mapped[str | None] = mapped_column(Text, nullable=True)
    shared_secret_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "conversation_id", "user_id", name="uq_conversation_participants"
        ),
        Index(
            "ix_conversation_participants_user_conversation",
            "user_id",
            "conversation_id",
        ),
    )


class ConversationEvent(Base):
    __tablename__ = "conversation_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_uuid: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        nullable=False,
        unique=True,
        server_default=text("gen_random_uuid()"),
    )
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_device_id: Mapped[int | None] = mapped_column(
        ForeignKey("devices.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_type: Mapped[EventType] = mapped_column(
        SAEnum(
            EventType,
            name="event_type_enum",
            native_enum=True,
            validate_strings=True,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
    )
    target_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_conversation_events_conversation_id", "conversation_id", "id"),
        Index("ix_conversation_events_created_at", "created_at"),
    )
