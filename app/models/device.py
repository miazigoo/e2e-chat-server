from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    device_uuid: Mapped[str] = mapped_column(String(128), nullable=False)
    device_name: Mapped[str] = mapped_column(Text, nullable=False)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    app_version: Mapped[str] = mapped_column(String(64), nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    fcm_token: Mapped[str | None] = mapped_column(Text, nullable=True)

    registration_id: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    public_identity_key: Mapped[str] = mapped_column(Text, nullable=False)
    public_signing_key: Mapped[str] = mapped_column(Text, nullable=False)
    signed_prekey_id: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    signed_prekey: Mapped[str] = mapped_column(Text, nullable=False)
    signed_prekey_signature: Mapped[str] = mapped_column(Text, nullable=False)

    prekeys_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("uq_devices_user_uuid", "user_id", "device_uuid", unique=True),
        Index(
            "ux_devices_one_active_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("is_active = TRUE AND revoked_at IS NULL"),
        ),
    )
