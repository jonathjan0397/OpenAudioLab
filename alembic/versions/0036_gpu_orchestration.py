"""GPU orchestration M1: workers.loaded_model (Smart Queue dashboard)

Revision ID: 0036
Revises: 0035
Create Date: 2026-10-21

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0036"
down_revision: Union[str, None] = "0035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("workers", sa.Column("loaded_model", sa.String(120), nullable=True))


def downgrade() -> None:
    op.drop_column("workers", "loaded_model")
