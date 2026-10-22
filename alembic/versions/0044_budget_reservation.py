"""Budget reservations: atomic pre-dispatch spend commitments.

Revision ID: 0044
Revises: 0043
Create Date: 2026-10-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0044"
down_revision: Union[str, None] = "0043"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ml_budgets", sa.Column("reserved_usd", sa.Float(), nullable=False,
                                          server_default="0"))
    op.add_column("ml_training_attempts", sa.Column("reserved_usd", sa.Float(),
                                                    nullable=False, server_default="0"))
    op.add_column("ml_training_attempts", sa.Column("settled", sa.Boolean(),
                                                    nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("ml_training_attempts", "settled")
    op.drop_column("ml_training_attempts", "reserved_usd")
    op.drop_column("ml_budgets", "reserved_usd")
