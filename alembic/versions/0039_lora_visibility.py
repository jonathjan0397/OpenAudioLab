"""Model Lab M1: loras.visibility (public|private) for suggestion hygiene

Revision ID: 0039
Revises: 0038
Create Date: 2026-10-22

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0039"
down_revision: Union[str, None] = "0038"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("loras", sa.Column("visibility", sa.String(length=12), nullable=False, server_default="public"))


def downgrade() -> None:
    op.drop_column("loras", "visibility")
