"""GPU orchestration M2/M3: scale decisions, deployment intents, fleet events

Revision ID: 0037
Revises: 0036
Create Date: 2026-10-21

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0037"
down_revision: Union[str, None] = "0036"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "gpu_scale_decisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model_group", sa.String(80), nullable=True),
        sa.Column("queued_jobs", sa.Integer, nullable=False, server_default="0"),
        sa.Column("oldest_job_age_seconds", sa.Float, nullable=False, server_default="0"),
        sa.Column("est_local_wait_seconds", sa.Float, nullable=False, server_default="0"),
        sa.Column("est_remote_ready_seconds", sa.Float, nullable=False, server_default="0"),
        sa.Column("selected_offer_id", sa.String(64), nullable=True),
        sa.Column("est_cost_usd", sa.Float, nullable=True),
        sa.Column("swappiness", sa.Integer, nullable=False, server_default="50"),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(60), nullable=False),
    )
    op.create_index("ix_gpu_scale_decisions_created_at", "gpu_scale_decisions", ["created_at"])
    op.create_table(
        "gpu_deployments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("origin", sa.String(20), nullable=False),  # AUTO_BURST|MANUAL_ADMIN|BASELINE_FALLBACK|TRAINING_POOL
        sa.Column("purpose", sa.String(40), nullable=False),  # auto|turbo|sft|xl-turbo|xl-sft|training
        sa.Column("idempotency_key", sa.String(80), nullable=True),
        sa.Column("offer_id", sa.String(64), nullable=True),
        sa.Column("offer_snapshot_json", sa.JSON, nullable=True),
        sa.Column("state", sa.String(30), nullable=False, server_default="REQUESTED"),
        sa.Column("state_reason", sa.String(200), nullable=True),
        sa.Column("contract", sa.Integer, nullable=True),
        sa.Column("worker_id", sa.String(120), nullable=True),
        sa.Column("dph", sa.Float, nullable=True),
        sa.Column("max_spend_usd", sa.Float, nullable=True),
        sa.Column("automatic_shutdown", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("requested_by", sa.String(120), nullable=True),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_gpu_deployments_state", "gpu_deployments", ["state"])
    op.create_index("ix_gpu_deployments_idem", "gpu_deployments", ["idempotency_key"])
    op.create_table(
        "gpu_fleet_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(120), nullable=False),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("subject", sa.String(120), nullable=True),
        sa.Column("detail_json", sa.JSON, nullable=True),
    )
    op.create_index("ix_gpu_fleet_events_created_at", "gpu_fleet_events", ["created_at"])


def downgrade() -> None:
    op.drop_table("gpu_fleet_events")
    op.drop_table("gpu_deployments")
    op.drop_table("gpu_scale_decisions")
