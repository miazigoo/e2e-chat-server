"""chat settings and message reactions

Revision ID: 0003_chat_settings_and_reactions
Revises: 0002_auth_sessions_sid
Create Date: 2026-04-24 00:00:00
"""

from alembic import op

revision = "0003_chat_settings_and_reactions"
down_revision = "0002_auth_sessions_sid"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE conversation_participants
        ADD COLUMN IF NOT EXISTS shared_secret_enabled BOOLEAN NOT NULL DEFAULT FALSE,
        ADD COLUMN IF NOT EXISTS shared_secret_fingerprint TEXT NULL,
        ADD COLUMN IF NOT EXISTS shared_secret_updated_at TIMESTAMPTZ NULL;
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_enum
                WHERE enumlabel = 'message_reaction_set'
                AND enumtypid = 'event_type_enum'::regtype
            ) THEN
                ALTER TYPE event_type_enum ADD VALUE 'message_reaction_set';
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM pg_enum
                WHERE enumlabel = 'message_reaction_removed'
                AND enumtypid = 'event_type_enum'::regtype
            ) THEN
                ALTER TYPE event_type_enum ADD VALUE 'message_reaction_removed';
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM pg_enum
                WHERE enumlabel = 'conversation_settings_updated'
                AND enumtypid = 'event_type_enum'::regtype
            ) THEN
                ALTER TYPE event_type_enum ADD VALUE 'conversation_settings_updated';
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS message_reactions (
            id BIGSERIAL PRIMARY KEY,
            message_id BIGINT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            reaction VARCHAR(32) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_message_reactions_user UNIQUE(message_id, user_id)
        );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_message_reactions_message_id
        ON message_reactions(message_id);
        """
    )

    op.execute(
        """
        DROP TRIGGER IF EXISTS trg_message_reactions_updated_at ON message_reactions;
        CREATE TRIGGER trg_message_reactions_updated_at
        BEFORE UPDATE ON message_reactions
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS message_reactions CASCADE;")
    op.execute(
        """
        ALTER TABLE conversation_participants
        DROP COLUMN IF EXISTS shared_secret_updated_at,
        DROP COLUMN IF EXISTS shared_secret_fingerprint,
        DROP COLUMN IF EXISTS shared_secret_enabled;
        """
    )
