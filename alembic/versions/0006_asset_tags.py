"""asset tags

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("assets", sa.Column("tags_json", sa.JSON(), nullable=False, server_default="[]"))


def downgrade() -> None:
    op.drop_column("assets", "tags_json")
