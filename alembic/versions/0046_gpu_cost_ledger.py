"""Durable GPU cost ledger entries.

Revision ID: 0046
Revises: 0045
Create Date: 2026-10-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0046"
down_revision: Union[str, None] = "0045"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "gpu_cost_ledger",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("vast_instance_id", sa.String(length=60), nullable=False),
        sa.Column("purpose", sa.String(length=40), nullable=False, server_default="auto"),
        sa.Column("dph", sa.Float(), nullable=True),
        sa.Column("state", sa.String(length=10), nullable=False, server_default="open"),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hours", sa.Float(), nullable=True),
        sa.Column("usd", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="deploy"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_gpu_cost_ledger_instance", "gpu_cost_ledger", ["vast_instance_id"])
    op.create_index("ix_gpu_cost_ledger_state", "gpu_cost_ledger", ["state"])


def downgrade() -> None:
    op.drop_index("ix_gpu_cost_ledger_state", table_name="gpu_cost_ledger")
    op.drop_index("ix_gpu_cost_ledger_instance", table_name="gpu_cost_ledger")
    op.drop_table("gpu_cost_ledger")
