"""signal registration fields

Revision ID: 0004_signal_registration_fields
Revises: 0003_chat_settings_and_reactions
Create Date: 2026-04-24 00:00:00
"""

from alembic import op

revision = "0004_signal_registration_fields"
down_revision = "0003_chat_settings_and_reactions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE devices
        ADD COLUMN IF NOT EXISTS registration_id INTEGER NOT NULL DEFAULT 0,
        ADD COLUMN IF NOT EXISTS signed_prekey_id INTEGER NOT NULL DEFAULT 1;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE devices
        DROP COLUMN IF EXISTS signed_prekey_id,
        DROP COLUMN IF EXISTS registration_id;
        """
    )
