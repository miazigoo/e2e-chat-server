"""multi device authorization

Revision ID: 0010_multi_device_authorization
Revises: 0009_scope_device_uuid_per_user
Create Date: 2026-05-01 13:20:00
"""

from alembic import op

revision = "0010_multi_device_authorization"
down_revision = "0009_scope_device_uuid_per_user"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_devices_one_active_per_user;")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS device_authorization_requests (
            id BIGSERIAL PRIMARY KEY,
            request_id VARCHAR(36) NOT NULL,
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            device_uuid VARCHAR(128) NOT NULL,
            device_name TEXT NULL,
            platform VARCHAR(32) NULL,
            app_version VARCHAR(64) NULL,
            ip_address INET NULL,
            user_agent TEXT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'pending',
            requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMPTZ NOT NULL,
            resolved_at TIMESTAMPTZ NULL,
            resolved_by_device_id BIGINT NULL REFERENCES devices(id) ON DELETE SET NULL
        );
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ix_device_auth_requests_request_id
        ON device_authorization_requests(request_id);
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_device_auth_requests_user_status
        ON device_authorization_requests(user_id, status);
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_device_auth_requests_user_device
        ON device_authorization_requests(user_id, device_uuid);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS device_authorization_requests;")
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_devices_one_active_per_user
        ON devices(user_id)
        WHERE is_active = TRUE AND revoked_at IS NULL;
        """
    )
