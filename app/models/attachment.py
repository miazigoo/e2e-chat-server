from datetime import datetime

from sqlalchemy import BigInteger, DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Index, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.chat_enums import AttachmentStatus, UploadSessionStatus


class UploadSession(Base):
    __tablename__ = "upload_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_uuid: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        nullable=False,
        unique=True,
        server_default=text("gen_random_uuid()"),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )

    status: Mapped[UploadSessionStatus] = mapped_column(
        SAEnum(
            UploadSessionStatus,
            name="upload_session_status_enum",
            native_enum=True,
            validate_strings=True,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        default=UploadSessionStatus.INIT,
    )

    files_expected_count: Mapped[int] = mapped_column(Integer, nullable=False)
    files_uploaded_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        Index("ix_upload_sessions_user_id", "user_id"),
        Index("ix_upload_sessions_conversation_id", "conversation_id"),
        Index("ix_upload_sessions_expires_at", "expires_at"),
    )


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    attachment_uuid: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        nullable=False,
        unique=True,
        server_default=text("gen_random_uuid()"),
    )

    message_id: Mapped[int | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    upload_session_id: Mapped[int | None] = mapped_column(
        ForeignKey("upload_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )

    storage_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    bucket_name: Mapped[str] = mapped_column(Text, nullable=False)

    encrypted_file_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    encrypted_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime_hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    sha256_encrypted_blob: Mapped[str] = mapped_column(Text, nullable=False)

    upload_status: Mapped[AttachmentStatus] = mapped_column(
        SAEnum(
            AttachmentStatus,
            name="attachment_status_enum",
            native_enum=True,
            validate_strings=True,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        default=AttachmentStatus.INIT,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        Index("ix_attachments_message_id", "message_id"),
        Index("ix_attachments_upload_session_id", "upload_session_id"),
        Index("ix_attachments_expires_at", "expires_at"),
    )
