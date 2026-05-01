"""message device payloads

Revision ID: 0011_message_device_payloads
Revises: 0010_multi_device_authorization
Create Date: 2026-05-01 13:55:00
"""

from alembic import op

revision = "0011_message_device_payloads"
down_revision = "0010_multi_device_authorization"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS message_device_payloads (
            id BIGSERIAL PRIMARY KEY,
            message_id BIGINT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
            device_id BIGINT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
            ciphertext TEXT NOT NULL,
            ciphertext_version INTEGER NOT NULL DEFAULT 1,
            nonce TEXT NOT NULL,
            aad_hash TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_message_device_payloads_message_device
        ON message_device_payloads(message_id, device_id);
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_message_device_payloads_device
        ON message_device_payloads(device_id);
        """
    )
    op.execute(
        """
        INSERT INTO message_device_payloads (
            message_id,
            device_id,
            ciphertext,
            ciphertext_version,
            nonce,
            aad_hash
        )
        SELECT
            id,
            recipient_device_id,
            ciphertext,
            ciphertext_version,
            nonce,
            aad_hash
        FROM messages
        ON CONFLICT (message_id, device_id) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS message_device_payloads;")
