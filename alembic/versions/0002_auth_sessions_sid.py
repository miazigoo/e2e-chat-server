from alembic import op

revision = "0002_auth_sessions_sid"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE auth_sessions
        ADD COLUMN IF NOT EXISTS session_id VARCHAR(36);
        """
    )
    op.execute(
        """
        UPDATE auth_sessions
        SET session_id = gen_random_uuid()::text
        WHERE session_id IS NULL;
        """
    )
    op.execute(
        """
        ALTER TABLE auth_sessions
        ALTER COLUMN session_id SET NOT NULL;
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ix_auth_sessions_session_id
        ON auth_sessions(session_id);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ix_auth_sessions_session_id;
        """
    )
    op.execute(
        """
        ALTER TABLE auth_sessions
        DROP COLUMN IF EXISTS session_id;
        """
    )
