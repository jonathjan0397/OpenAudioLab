"""Drop dead GpuLease table (serial GPU ownership is enforced by serialized claiming, not leases)

Revision ID: 0035
Revises: 0034
Create Date: 2026-10-21

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0035"
down_revision: Union[str, None] = "0034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("gpu_leases")


def downgrade() -> None:
    op.create_table(
        "gpu_leases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("gpu_id", sa.String(40), nullable=False),
        sa.Column("holder", sa.String(120), nullable=True),
        sa.Column("model_selection", sa.String(80), nullable=True),
        sa.Column("fence_token", sa.String(64), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="free"),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_gpu_leases_gpu_id", "gpu_leases", ["gpu_id"])
    op.create_index("ix_gpu_leases_status", "gpu_leases", ["status"])
