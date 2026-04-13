"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-04-10 09:30:00
"""

from alembic import op

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")
    op.execute("CREATE EXTENSION IF NOT EXISTS citext;")

    op.execute(
        """
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'protection_mode_enum') THEN
            CREATE TYPE protection_mode_enum AS ENUM ('normal', 'shared_secret');
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'message_type_enum') THEN
            CREATE TYPE message_type_enum AS ENUM ('text', 'file', 'service');
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'encryption_mode_enum') THEN
            CREATE TYPE encryption_mode_enum AS ENUM ('signal', 'signal_plus_shared_secret');
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'delivery_status_enum') THEN
            CREATE TYPE delivery_status_enum AS ENUM (
                'server_received', 'pushed', 'delivered', 'read',
                'failed', 'deleted_global', 'expired', 'purged'
            );
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'visibility_reason_enum') THEN
            CREATE TYPE visibility_reason_enum AS ENUM ('user_deleted', 'conversation_cleared_local');
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'event_type_enum') THEN
            CREATE TYPE event_type_enum AS ENUM (
                'message_created',
                'message_deleted_global',
                'message_hidden_for_user',
                'conversation_cleared_local',
                'conversation_cleared_global',
                'message_delivered',
                'message_read',
                'file_uploaded',
                'file_deleted',
                'participant_key_changed',
                'conversation_purged'
            );
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'attachment_status_enum') THEN
            CREATE TYPE attachment_status_enum AS ENUM ('init', 'uploaded', 'linked', 'deleted');
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'upload_session_status_enum') THEN
            CREATE TYPE upload_session_status_enum AS ENUM ('init', 'uploading', 'completed', 'expired', 'aborted');
        END IF;
    END $$;
    """
    )

    op.execute(
        """
    CREATE TABLE IF NOT EXISTS users (
        id BIGSERIAL PRIMARY KEY,
        public_id UUID NOT NULL DEFAULT gen_random_uuid(),
        nickname CITEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        email CITEXT UNIQUE,
        email_2fa_enabled BOOLEAN NOT NULL DEFAULT FALSE,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        is_frozen BOOLEAN NOT NULL DEFAULT FALSE,
        pending_deletion BOOLEAN NOT NULL DEFAULT FALSE,
        is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
        failed_login_stage SMALLINT NOT NULL DEFAULT 0,
        lock_until TIMESTAMPTZ NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        deleted_at TIMESTAMPTZ NULL
    );
    """
    )

    op.execute(
        """
    CREATE TABLE IF NOT EXISTS devices (
        id BIGSERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        device_uuid VARCHAR(128) NOT NULL UNIQUE,
        device_name TEXT NOT NULL,
        platform TEXT NOT NULL CHECK (platform IN ('android')),
        app_version TEXT NOT NULL,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        revoked_at TIMESTAMPTZ NULL,
        fcm_token TEXT NULL,
        public_identity_key TEXT NOT NULL,
        public_signing_key TEXT NOT NULL,
        signed_prekey TEXT NOT NULL,
        signed_prekey_signature TEXT NOT NULL,
        prekeys_count INTEGER NOT NULL DEFAULT 0,
        registered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        last_seen_at TIMESTAMPTZ NULL
    );
    """
    )

    op.execute(
        """
    CREATE UNIQUE INDEX IF NOT EXISTS ux_devices_one_active_per_user
    ON devices(user_id)
    WHERE is_active = TRUE AND revoked_at IS NULL;
    """
    )

    op.execute(
        """
    CREATE TABLE IF NOT EXISTS device_prekeys (
        id BIGSERIAL PRIMARY KEY,
        device_id BIGINT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
        prekey_id INTEGER NOT NULL,
        public_prekey TEXT NOT NULL,
        is_used BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        used_at TIMESTAMPTZ NULL,
        UNIQUE(device_id, prekey_id)
    );
    """
    )

    op.execute(
        """
    CREATE TABLE IF NOT EXISTS auth_sessions (
        id BIGSERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        device_id BIGINT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
        refresh_token_hash TEXT NOT NULL,
        user_agent TEXT NULL,
        ip_address INET NULL,
        issued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        expires_at TIMESTAMPTZ NOT NULL,
        revoked_at TIMESTAMPTZ NULL
    );
    """
    )

    op.execute(
        """
    CREATE TABLE IF NOT EXISTS auth_email_codes (
        id BIGSERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        login_challenge_id UUID NOT NULL,
        code_hash TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        expires_at TIMESTAMPTZ NOT NULL,
        consumed_at TIMESTAMPTZ NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(login_challenge_id)
    );
    """
    )

    op.execute(
        """
    CREATE TABLE IF NOT EXISTS login_attempts (
        id BIGSERIAL PRIMARY KEY,
        nickname CITEXT NOT NULL,
        user_id BIGINT NULL REFERENCES users(id) ON DELETE SET NULL,
        ip_address INET NULL,
        device_fingerprint TEXT NULL,
        success BOOLEAN NOT NULL,
        failure_reason TEXT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """
    )

    op.execute(
        """
    CREATE TABLE IF NOT EXISTS conversations (
        id BIGSERIAL PRIMARY KEY,
        conversation_uuid UUID NOT NULL DEFAULT gen_random_uuid(),
        user_a_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        user_b_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_by_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
        title TEXT NULL,
        protection_mode protection_mode_enum NOT NULL DEFAULT 'normal',
        message_ttl_days INTEGER NULL CHECK (message_ttl_days BETWEEN 1 AND 60),
        delete_after_read_seconds INTEGER NULL CHECK (delete_after_read_seconds > 0),
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        is_purged BOOLEAN NOT NULL DEFAULT FALSE,
        purged_at TIMESTAMPTZ NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(conversation_uuid)
    );
    """
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_conversations_user_a ON conversations(user_a_id);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_conversations_user_b ON conversations(user_b_id);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_conversations_pair ON conversations(user_a_id, user_b_id);"
    )

    op.execute(
        """
    CREATE TABLE IF NOT EXISTS conversation_participants (
        id BIGSERIAL PRIMARY KEY,
        conversation_id BIGINT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
        user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        last_read_message_id BIGINT NULL,
        last_read_at TIMESTAMPTZ NULL,
        cleared_at TIMESTAMPTZ NULL,
        UNIQUE(conversation_id, user_id)
    );
    """
    )

    op.execute(
        """
    CREATE TABLE IF NOT EXISTS messages (
        id BIGSERIAL PRIMARY KEY,
        message_uuid UUID NOT NULL DEFAULT gen_random_uuid(),
        conversation_id BIGINT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
        sender_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
        sender_device_id BIGINT NOT NULL REFERENCES devices(id) ON DELETE RESTRICT,
        recipient_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
        recipient_device_id BIGINT NOT NULL REFERENCES devices(id) ON DELETE RESTRICT,
        reply_to_message_id BIGINT NULL REFERENCES messages(id) ON DELETE SET NULL,
        message_type message_type_enum NOT NULL,
        ciphertext TEXT NOT NULL,
        ciphertext_version INTEGER NOT NULL DEFAULT 1,
        encryption_mode encryption_mode_enum NOT NULL,
        nonce TEXT NOT NULL,
        aad_hash TEXT NULL,
        client_created_at TIMESTAMPTZ NOT NULL,
        server_received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        delivered_at TIMESTAMPTZ NULL,
        read_at TIMESTAMPTZ NULL,
        is_deleted_global BOOLEAN NOT NULL DEFAULT FALSE,
        deleted_global_at TIMESTAMPTZ NULL,
        deleted_by_user_id BIGINT NULL REFERENCES users(id) ON DELETE SET NULL,
        expires_at TIMESTAMPTZ NOT NULL,
        auto_delete_after_read_seconds INTEGER NULL CHECK (auto_delete_after_read_seconds > 0),
        has_attachments BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(message_uuid)
    );
    """
    )

    op.execute(
        """
    CREATE INDEX IF NOT EXISTS ix_messages_conversation_created
    ON messages(conversation_id, created_at DESC);
    """
    )
    op.execute(
        """
    CREATE INDEX IF NOT EXISTS ix_messages_recipient_read
    ON messages(recipient_user_id, read_at);
    """
    )
    op.execute(
        """
    CREATE INDEX IF NOT EXISTS ix_messages_expires_at
    ON messages(expires_at);
    """
    )
    op.execute(
        """
    CREATE INDEX IF NOT EXISTS ix_messages_sender
    ON messages(sender_user_id, created_at DESC);
    """
    )

    op.execute(
        """
    CREATE TABLE IF NOT EXISTS message_recipient_states (
        id BIGSERIAL PRIMARY KEY,
        message_id BIGINT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
        recipient_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        recipient_device_id BIGINT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
        delivery_status delivery_status_enum NOT NULL DEFAULT 'server_received',
        delivered_at TIMESTAMPTZ NULL,
        read_at TIMESTAMPTZ NULL,
        last_push_at TIMESTAMPTZ NULL,
        failure_reason TEXT NULL,
        UNIQUE(message_id, recipient_device_id)
    );
    """
    )

    op.execute(
        """
    CREATE TABLE IF NOT EXISTS message_visibility_overrides (
        id BIGSERIAL PRIMARY KEY,
        message_id BIGINT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
        user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        hidden_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        reason visibility_reason_enum NOT NULL,
        UNIQUE(message_id, user_id)
    );
    """
    )

    op.execute(
        """
    CREATE TABLE IF NOT EXISTS conversation_events (
        id BIGSERIAL PRIMARY KEY,
        event_uuid UUID NOT NULL DEFAULT gen_random_uuid(),
        conversation_id BIGINT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
        actor_user_id BIGINT NULL REFERENCES users(id) ON DELETE SET NULL,
        actor_device_id BIGINT NULL REFERENCES devices(id) ON DELETE SET NULL,
        event_type event_type_enum NOT NULL,
        target_message_id BIGINT NULL REFERENCES messages(id) ON DELETE SET NULL,
        payload JSONB NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(event_uuid)
    );
    """
    )

    op.execute(
        """
    CREATE INDEX IF NOT EXISTS ix_conversation_events_conversation_id
    ON conversation_events(conversation_id, id);
    """
    )
    op.execute(
        """
    CREATE INDEX IF NOT EXISTS ix_conversation_events_created_at
    ON conversation_events(created_at);
    """
    )

    op.execute(
        """
    CREATE TABLE IF NOT EXISTS upload_sessions (
        id BIGSERIAL PRIMARY KEY,
        session_uuid UUID NOT NULL DEFAULT gen_random_uuid(),
        user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        conversation_id BIGINT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
        status upload_session_status_enum NOT NULL DEFAULT 'init',
        files_expected_count INTEGER NOT NULL CHECK (files_expected_count BETWEEN 1 AND 20),
        files_uploaded_count INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        expires_at TIMESTAMPTZ NOT NULL,
        completed_at TIMESTAMPTZ NULL,
        UNIQUE(session_uuid)
    );
    """
    )

    op.execute(
        """
    CREATE TABLE IF NOT EXISTS attachments (
        id BIGSERIAL PRIMARY KEY,
        attachment_uuid UUID NOT NULL DEFAULT gen_random_uuid(),
        message_id BIGINT NULL REFERENCES messages(id) ON DELETE SET NULL,
        upload_session_id BIGINT NULL REFERENCES upload_sessions(id) ON DELETE SET NULL,
        storage_key TEXT NOT NULL UNIQUE,
        bucket_name TEXT NOT NULL,
        encrypted_file_name TEXT NULL,
        encrypted_metadata JSONB NULL,
        file_size BIGINT NOT NULL CHECK (file_size > 0),
        mime_hint TEXT NULL,
        sha256_encrypted_blob CHAR(64) NOT NULL,
        upload_status attachment_status_enum NOT NULL DEFAULT 'init',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        expires_at TIMESTAMPTZ NULL,
        deleted_at TIMESTAMPTZ NULL,
        UNIQUE(attachment_uuid)
    );
    """
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_attachments_message_id ON attachments(message_id);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_attachments_upload_session_id ON attachments(upload_session_id);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_attachments_expires_at ON attachments(expires_at);"
    )

    op.execute(
        """
    CREATE TABLE IF NOT EXISTS account_deletion_queue (
        id BIGSERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        scheduled_at TIMESTAMPTZ NOT NULL,
        reason TEXT NOT NULL,
        executed_at TIMESTAMPTZ NULL,
        cancelled_at TIMESTAMPTZ NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(user_id)
    );
    """
    )

    op.execute(
        """
    CREATE OR REPLACE FUNCTION set_updated_at()
    RETURNS TRIGGER AS $$
    BEGIN
        NEW.updated_at = NOW();
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """
    )

    op.execute(
        """
    DROP TRIGGER IF EXISTS trg_users_updated_at ON users;
    CREATE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    """
    )

    op.execute(
        """
    DROP TRIGGER IF EXISTS trg_conversations_updated_at ON conversations;
    CREATE TRIGGER trg_conversations_updated_at
    BEFORE UPDATE ON conversations
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    """
    )

    op.execute(
        """
    DROP TRIGGER IF EXISTS trg_messages_updated_at ON messages;
    CREATE TRIGGER trg_messages_updated_at
    BEFORE UPDATE ON messages
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS account_deletion_queue CASCADE;")
    op.execute("DROP TABLE IF EXISTS attachments CASCADE;")
    op.execute("DROP TABLE IF EXISTS upload_sessions CASCADE;")
    op.execute("DROP TABLE IF EXISTS conversation_events CASCADE;")
    op.execute("DROP TABLE IF EXISTS message_visibility_overrides CASCADE;")
    op.execute("DROP TABLE IF EXISTS message_recipient_states CASCADE;")
    op.execute("DROP TABLE IF EXISTS messages CASCADE;")
    op.execute("DROP TABLE IF EXISTS conversation_participants CASCADE;")
    op.execute("DROP TABLE IF EXISTS conversations CASCADE;")
    op.execute("DROP TABLE IF EXISTS login_attempts CASCADE;")
    op.execute("DROP TABLE IF EXISTS auth_email_codes CASCADE;")
    op.execute("DROP TABLE IF EXISTS auth_sessions CASCADE;")
    op.execute("DROP TABLE IF EXISTS device_prekeys CASCADE;")
    op.execute("DROP TABLE IF EXISTS devices CASCADE;")
    op.execute("DROP TABLE IF EXISTS users CASCADE;")

    op.execute("DROP FUNCTION IF EXISTS set_updated_at CASCADE;")

    op.execute("DROP TYPE IF EXISTS upload_session_status_enum CASCADE;")
    op.execute("DROP TYPE IF EXISTS attachment_status_enum CASCADE;")
    op.execute("DROP TYPE IF EXISTS event_type_enum CASCADE;")
    op.execute("DROP TYPE IF EXISTS visibility_reason_enum CASCADE;")
    op.execute("DROP TYPE IF EXISTS delivery_status_enum CASCADE;")
    op.execute("DROP TYPE IF EXISTS encryption_mode_enum CASCADE;")
    op.execute("DROP TYPE IF EXISTS message_type_enum CASCADE;")
    op.execute("DROP TYPE IF EXISTS protection_mode_enum CASCADE;")
