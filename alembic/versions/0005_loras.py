"""loras registry

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "loras",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("tags_json", sa.JSON(), nullable=False),
        sa.Column("storage_prefix", sa.String(length=500), nullable=False),
        sa.Column("files_json", sa.JSON(), nullable=False),
        sa.Column("base_model_id", sa.String(length=80), nullable=False),
        sa.Column("base_revision", sa.String(length=120), nullable=False),
        sa.Column("default_scale", sa.Float(), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("provenance", sa.String(length=20), nullable=False),
        sa.Column("profile_version_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )


def downgrade() -> None:
    op.drop_table("loras")
