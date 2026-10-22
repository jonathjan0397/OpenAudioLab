"""Durable fleet-node identity + exclusive-training state machine.

Revision ID: 0045
Revises: 0044
Create Date: 2026-10-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0045"
down_revision: Union[str, None] = "0044"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "fleet_nodes",
        sa.Column("id", sa.String(length=120), nullable=False),
        sa.Column("instance_id", sa.String(length=60), nullable=True),
        sa.Column("worker_id", sa.String(length=120), nullable=True),
        sa.Column("state", sa.String(length=20), nullable=False,
                  server_default="shared_ready"),
        sa.Column("exclusive_attempt_id", sa.String(length=36), nullable=True),
        sa.Column("in_flight_jobs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(length=300), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_fleet_nodes_state", "fleet_nodes", ["state"])


def downgrade() -> None:
    op.drop_index("ix_fleet_nodes_state", table_name="fleet_nodes")
    op.drop_table("fleet_nodes")
