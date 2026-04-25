"""message features search and pin

Revision ID: 0006_message_features
Revises: 0005_user_profiles_app
Create Date: 2026-04-25 00:30:00
"""

from alembic import op

revision = "0006_message_features"
down_revision = "0005_user_profiles_app"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE messages
        ADD COLUMN IF NOT EXISTS forward_from_message_id BIGINT NULL
        REFERENCES messages(id) ON DELETE SET NULL;
        """
    )
    op.execute(
        """
        ALTER TABLE conversations
        ADD COLUMN IF NOT EXISTS pinned_message_id BIGINT NULL
        REFERENCES messages(id) ON DELETE SET NULL;
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_messages_forward_from_message_id
        ON messages(forward_from_message_id);
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_messages_reply_to_message_id
        ON messages(reply_to_message_id);
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_conversations_pinned_message_id
        ON conversations(pinned_message_id);
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_enum
                WHERE enumlabel = 'message_forwarded'
                AND enumtypid = 'event_type_enum'::regtype
            ) THEN
                ALTER TYPE event_type_enum ADD VALUE 'message_forwarded';
            END IF;
        END
        $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_enum
                WHERE enumlabel = 'message_pinned'
                AND enumtypid = 'event_type_enum'::regtype
            ) THEN
                ALTER TYPE event_type_enum ADD VALUE 'message_pinned';
            END IF;
        END
        $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_enum
                WHERE enumlabel = 'message_unpinned'
                AND enumtypid = 'event_type_enum'::regtype
            ) THEN
                ALTER TYPE event_type_enum ADD VALUE 'message_unpinned';
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_conversations_pinned_message_id;")
    op.execute("DROP INDEX IF EXISTS ix_messages_reply_to_message_id;")
    op.execute("DROP INDEX IF EXISTS ix_messages_forward_from_message_id;")
    op.execute(
        """
        ALTER TABLE conversations
        DROP COLUMN IF EXISTS pinned_message_id;
        """
    )
    op.execute(
        """
        ALTER TABLE messages
        DROP COLUMN IF EXISTS forward_from_message_id;
        """
    )
