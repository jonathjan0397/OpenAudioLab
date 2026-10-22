"""Worker-built library folder index (hub out of the data path).

Revision ID: 0049
Revises: 0048
Create Date: 2026-10-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0049"
down_revision: Union[str, None] = "0048"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ml_dir_index",
        sa.Column("path", sa.String(length=700), primary_key=True),
        sa.Column("parent", sa.String(length=700), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("n_audio", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("n_dirs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("has_nfo", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("has_lrc", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("files_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_ml_dir_index_parent", "ml_dir_index", ["parent"])


def downgrade() -> None:
    op.drop_index("ix_ml_dir_index_parent", table_name="ml_dir_index")
    op.drop_table("ml_dir_index")
