"""Model Lab M4: datasets, budgets, training attempts, merges, bundles, evaluations, channels

Revision ID: 0042
Revises: 0041
Create Date: 2026-10-22

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0042"
down_revision: Union[str, None] = "0041"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ml_datasets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("frozen_sha256", sa.String(64), nullable=False),
        sa.Column("manifest_json", sa.JSON(), nullable=False),
        sa.Column("report_json", sa.JSON(), nullable=False),
        sa.Column("recording_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_seconds", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "ml_budgets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(60), nullable=False, unique=True),
        sa.Column("max_hours", sa.Float(), nullable=False, server_default="6"),
        sa.Column("max_spend_usd", sa.Float(), nullable=False, server_default="3"),
        sa.Column("used_hours", sa.Float(), nullable=False, server_default="0"),
        sa.Column("spent_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("state", sa.String(12), nullable=False, server_default="open"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "ml_training_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("dataset_id", sa.String(36), nullable=False),
        sa.Column("budget_id", sa.String(36), nullable=False),
        sa.Column("job_id", sa.String(36), nullable=True),
        sa.Column("state", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("instance_id", sa.String(60), nullable=True),
        sa.Column("worker_id", sa.String(120), nullable=True),
        sa.Column("recipe_json", sa.JSON(), nullable=False),
        sa.Column("hours", sa.Float(), nullable=True),
        sa.Column("spend_usd", sa.Float(), nullable=True),
        sa.Column("error", sa.String(300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_mlta_dataset", "ml_training_attempts", ["dataset_id"])
    op.create_table(
        "ml_merge_recipes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("base_model", sa.String(120), nullable=False),
        sa.Column("adapter_ids_json", sa.JSON(), nullable=False),
        sa.Column("method", sa.String(20), nullable=False, server_default="slerp"),
        sa.Column("params_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "ml_model_bundles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("version", sa.String(40), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("base_model", sa.String(120), nullable=False),
        sa.Column("revision", sa.String(120), nullable=True),
        sa.Column("artifact_key", sa.String(300), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("state", sa.String(12), nullable=False, server_default="candidate"),
        sa.Column("bundle_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "ml_evaluations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("bundle_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("scores_json", sa.JSON(), nullable=False),
        sa.Column("verdict", sa.String(16), nullable=True),
        sa.Column("evaluator", sa.String(120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_mle_bundle", "ml_evaluations", ["bundle_id"])
    op.create_table(
        "ml_release_channels",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(30), nullable=False, unique=True),
        sa.Column("bundle_id", sa.String(36), nullable=True),
        sa.Column("min_credits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    for t in ("ml_release_channels", "ml_evaluations", "ml_model_bundles",
              "ml_merge_recipes", "ml_training_attempts", "ml_budgets", "ml_datasets"):
        op.drop_table(t)
