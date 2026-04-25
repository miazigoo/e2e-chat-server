"""user profiles and app releases

Revision ID: 0005_user_profiles_app
Revises: 0004_signal_registration_fields
Create Date: 2026-04-25 00:00:00
"""

from alembic import op

revision = "0005_user_profiles_app"
down_revision = "0004_signal_registration_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS full_name TEXT NULL,
        ADD COLUMN IF NOT EXISTS bio TEXT NULL,
        ADD COLUMN IF NOT EXISTS avatar_bucket_name TEXT NULL,
        ADD COLUMN IF NOT EXISTS avatar_storage_key TEXT NULL,
        ADD COLUMN IF NOT EXISTS avatar_content_type VARCHAR(255) NULL,
        ADD COLUMN IF NOT EXISTS language_code VARCHAR(16) NOT NULL DEFAULT 'ru',
        ADD COLUMN IF NOT EXISTS theme VARCHAR(16) NOT NULL DEFAULT 'system',
        ADD COLUMN IF NOT EXISTS push_notifications_enabled BOOLEAN NOT NULL DEFAULT TRUE,
        ADD COLUMN IF NOT EXISTS apk_update_notifications_enabled BOOLEAN NOT NULL DEFAULT TRUE,
        ADD COLUMN IF NOT EXISTS avatar_updated_at TIMESTAMPTZ NULL;
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS app_releases (
            id BIGSERIAL PRIMARY KEY,
            platform VARCHAR(32) NOT NULL,
            version_name VARCHAR(64) NOT NULL,
            version_code INTEGER NOT NULL,
            file_name TEXT NOT NULL,
            bucket_name TEXT NOT NULL,
            storage_key TEXT NOT NULL UNIQUE,
            content_type VARCHAR(255) NOT NULL,
            file_size BIGINT NOT NULL,
            sha256 VARCHAR(64) NOT NULL,
            changelog TEXT NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_app_releases_platform_active
        ON app_releases(platform, is_active, version_code DESC);
        """
    )

    op.execute("DROP TRIGGER IF EXISTS trg_app_releases_updated_at ON app_releases;")
    op.execute(
        """
        CREATE TRIGGER trg_app_releases_updated_at
        BEFORE UPDATE ON app_releases
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS app_releases CASCADE;")
    op.execute(
        """
        ALTER TABLE users
        DROP COLUMN IF EXISTS avatar_updated_at,
        DROP COLUMN IF EXISTS apk_update_notifications_enabled,
        DROP COLUMN IF EXISTS push_notifications_enabled,
        DROP COLUMN IF EXISTS theme,
        DROP COLUMN IF EXISTS language_code,
        DROP COLUMN IF EXISTS avatar_content_type,
        DROP COLUMN IF EXISTS avatar_storage_key,
        DROP COLUMN IF EXISTS avatar_bucket_name,
        DROP COLUMN IF EXISTS bio,
        DROP COLUMN IF EXISTS full_name;
        """
    )
