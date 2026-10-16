"""track identity (title/shared), favorites, credit ledger

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("assets", sa.Column("title", sa.String(length=200), nullable=True))
    op.add_column("assets", sa.Column("shared", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table(
        "favorites",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=80), nullable=False),
        sa.Column("asset_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "asset_id"),
    )
    op.create_index("ix_favorites_owner_id", "favorites", ["owner_id"])
    op.create_index("ix_favorites_asset_id", "favorites", ["asset_id"])
    op.create_table(
        "credit_entries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=80), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=60), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_credit_entries_owner_id", "credit_entries", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_credit_entries_owner_id", table_name="credit_entries")
    op.drop_table("credit_entries")
    op.drop_index("ix_favorites_asset_id", table_name="favorites")
    op.drop_index("ix_favorites_owner_id", table_name="favorites")
    op.drop_table("favorites")
    op.drop_column("assets", "shared")
    op.drop_column("assets", "title")
