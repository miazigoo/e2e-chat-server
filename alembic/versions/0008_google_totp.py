"""google totp

Revision ID: 0008_google_totp
Revises: 0007_saved_messages
Create Date: 2026-04-25 04:00:00
"""

from alembic import op

revision = "0008_google_totp"
down_revision = "0007_saved_messages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS google_2fa_enabled BOOLEAN NOT NULL DEFAULT FALSE,
        ADD COLUMN IF NOT EXISTS google_2fa_secret TEXT NULL,
        ADD COLUMN IF NOT EXISTS google_2fa_pending_secret TEXT NULL,
        ADD COLUMN IF NOT EXISTS google_2fa_confirmed_at TIMESTAMPTZ NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE users
        DROP COLUMN IF EXISTS google_2fa_confirmed_at,
        DROP COLUMN IF EXISTS google_2fa_pending_secret,
        DROP COLUMN IF EXISTS google_2fa_secret,
        DROP COLUMN IF EXISTS google_2fa_enabled;
        """
    )
