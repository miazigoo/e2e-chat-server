"""scope device uuid per user

Revision ID: 0009_scope_device_uuid_per_user
Revises: 0008_google_totp
Create Date: 2026-04-30 19:30:00
"""

from alembic import op

revision = "0009_scope_device_uuid_per_user"
down_revision = "0008_google_totp"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE devices DROP CONSTRAINT IF EXISTS devices_device_uuid_key;")
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_devices_user_uuid
        ON devices(user_id, device_uuid);
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_devices_user_uuid;")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'devices_device_uuid_key'
                  AND conrelid = 'devices'::regclass
            ) THEN
                ALTER TABLE devices
                ADD CONSTRAINT devices_device_uuid_key UNIQUE (device_uuid);
            END IF;
        END $$;
        """
    )
