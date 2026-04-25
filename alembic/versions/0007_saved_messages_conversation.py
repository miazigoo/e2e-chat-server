"""saved messages conversation

Revision ID: 0007_saved_messages
Revises: 0006_message_features
Create Date: 2026-04-25 02:00:00
"""

from alembic import op

revision = "0007_saved_messages"
down_revision = "0006_message_features"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE conversations
        ADD COLUMN IF NOT EXISTS is_saved_messages BOOLEAN NOT NULL DEFAULT FALSE;
        """
    )
    op.execute(
        """
        ALTER TABLE conversations
        DROP CONSTRAINT IF EXISTS ck_conversations_distinct_users;
        """
    )
    op.execute(
        """
        ALTER TABLE conversations
        DROP CONSTRAINT IF EXISTS ck_conversations_user_shape;
        """
    )
    op.execute(
        """
        ALTER TABLE conversations
        ADD CONSTRAINT ck_conversations_user_shape
        CHECK (
            (is_saved_messages = TRUE AND user_a_id = user_b_id)
            OR
            (is_saved_messages = FALSE AND user_a_id <> user_b_id)
        );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_conversations_is_saved_messages
        ON conversations(is_saved_messages);
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_conversations_saved_messages_user
        ON conversations(user_a_id)
        WHERE is_saved_messages = TRUE;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_conversations_saved_messages_user;")
    op.execute("DROP INDEX IF EXISTS ix_conversations_is_saved_messages;")
    op.execute(
        """
        ALTER TABLE conversations
        DROP CONSTRAINT IF EXISTS ck_conversations_user_shape;
        """
    )
    op.execute(
        """
        ALTER TABLE conversations
        ADD CONSTRAINT ck_conversations_distinct_users
        CHECK (user_a_id <> user_b_id);
        """
    )
    op.execute(
        """
        ALTER TABLE conversations
        DROP COLUMN IF EXISTS is_saved_messages;
        """
    )
