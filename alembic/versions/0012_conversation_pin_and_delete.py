"""conversation pin and delete

Revision ID: 0012_conversation_pin_and_delete
Revises: 0011_message_device_payloads
Create Date: 2026-05-01 18:20:00
"""

from alembic import op

revision = "0012_conversation_pin_and_delete"
down_revision = "0011_message_device_payloads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TYPE event_type_enum ADD VALUE IF NOT EXISTS 'conversation_pinned';
        """
    )
    op.execute(
        """
        ALTER TYPE event_type_enum ADD VALUE IF NOT EXISTS 'conversation_unpinned';
        """
    )
    op.execute(
        """
        ALTER TYPE event_type_enum ADD VALUE IF NOT EXISTS 'conversation_deleted';
        """
    )
    op.execute(
        """
        ALTER TABLE conversation_participants
        ADD COLUMN IF NOT EXISTS is_pinned BOOLEAN NOT NULL DEFAULT FALSE;
        """
    )
    op.execute(
        """
        ALTER TABLE conversation_participants
        ADD COLUMN IF NOT EXISTS pinned_at TIMESTAMPTZ NULL;
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_conversation_participants_user_pinned
        ON conversation_participants(user_id, is_pinned, pinned_at);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ix_conversation_participants_user_pinned;
        """
    )
    op.execute(
        """
        ALTER TABLE conversation_participants
        DROP COLUMN IF EXISTS pinned_at;
        """
    )
    op.execute(
        """
        ALTER TABLE conversation_participants
        DROP COLUMN IF EXISTS is_pinned;
        """
    )
