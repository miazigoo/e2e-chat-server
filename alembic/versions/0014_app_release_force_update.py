"""add force update fields to app releases

Revision ID: 0014_app_release_force_update
Revises: 0013_media_tags
Create Date: 2026-05-02 10:40:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "0014_app_release_force_update"
down_revision = "0013_media_tags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_releases",
        sa.Column(
            "force_update",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
    )
    op.add_column(
        "app_releases",
        sa.Column("min_supported_version_code", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("app_releases", "min_supported_version_code")
    op.drop_column("app_releases", "force_update")
