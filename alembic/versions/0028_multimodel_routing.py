"""multi-model: worker capability + GPU lease records

Revision ID: 0028
Revises: 0027
Create Date: 2026-10-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0028"
down_revision: Union[str, None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "worker_capabilities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("worker_id", sa.String(120), nullable=False),
        sa.Column("model_selection", sa.String(80), nullable=False),
        sa.Column("execution_profile_id", sa.String(80), nullable=False),
        sa.Column("engine_model", sa.String(120), nullable=False),
        sa.Column("planner_model", sa.String(120), nullable=True),
        sa.Column("tasks_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("max_duration_seconds", sa.Integer(), nullable=False, server_default="600"),
        sa.Column("vram_total_mb", sa.Integer(), nullable=True),
        sa.Column("supports_staged_planner", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("worker_id", "model_selection", "execution_profile_id", name="uq_workercap_worker_profile"),
    )
    op.create_index("ix_workercap_worker_id", "worker_capabilities", ["worker_id"])
    op.create_index("ix_workercap_model_selection", "worker_capabilities", ["model_selection"])

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
    op.create_index("ix_gpu_lease_gpu_id", "gpu_leases", ["gpu_id"])
    op.create_index("ix_gpu_lease_status", "gpu_leases", ["status"])


def downgrade() -> None:
    op.drop_index("ix_gpu_lease_status", table_name="gpu_leases")
    op.drop_index("ix_gpu_lease_gpu_id", table_name="gpu_leases")
    op.drop_table("gpu_leases")
    op.drop_index("ix_workercap_model_selection", table_name="worker_capabilities")
    op.drop_index("ix_workercap_worker_id", table_name="worker_capabilities")
    op.drop_table("worker_capabilities")
