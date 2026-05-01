"""media tags

Revision ID: 0013_media_tags
Revises: 0012_conversation_pin_and_delete
Create Date: 2026-05-02 12:10:00
"""

from alembic import op

revision = "0013_media_tags"
down_revision = "0012_conversation_pin_and_delete"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS conversation_media_tags (
            id BIGSERIAL PRIMARY KEY,
            conversation_id BIGINT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            color TEXT NULL,
            created_by_user_id BIGINT NULL REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_conversation_media_tags_name
                UNIQUE (conversation_id, normalized_name)
        );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_conversation_media_tags_conversation
        ON conversation_media_tags(conversation_id);
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS attachment_media_tags (
            id BIGSERIAL PRIMARY KEY,
            attachment_id BIGINT NOT NULL REFERENCES attachments(id) ON DELETE CASCADE,
            tag_id BIGINT NOT NULL REFERENCES conversation_media_tags(id) ON DELETE CASCADE,
            tagged_by_user_id BIGINT NULL REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_attachment_media_tags_attachment_tag
                UNIQUE (attachment_id, tag_id)
        );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_attachment_media_tags_tag
        ON attachment_media_tags(tag_id);
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_attachment_media_tags_attachment
        ON attachment_media_tags(attachment_id);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS attachment_media_tags;")
    op.execute("DROP TABLE IF EXISTS conversation_media_tags;")
