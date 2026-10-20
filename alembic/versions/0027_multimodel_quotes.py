"""multi-model: durable server-issued quotes

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0027"
down_revision: Union[str, None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "quotes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(80), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("model_selection", sa.String(80), nullable=False),
        sa.Column("engine_model", sa.String(120), nullable=False),
        sa.Column("execution_profile_id", sa.String(80), nullable=False),
        sa.Column("controls_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("context_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("takes", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("reserved_credits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("compute_factor", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("policy_version", sa.String(80), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("consumed_job_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_quotes_owner_id", "quotes", ["owner_id"])
    op.create_index("ix_quotes_request_hash", "quotes", ["request_hash"])
    op.create_index("ix_quotes_status", "quotes", ["status"])


def downgrade() -> None:
    op.drop_index("ix_quotes_status", table_name="quotes")
    op.drop_index("ix_quotes_request_hash", table_name="quotes")
    op.drop_index("ix_quotes_owner_id", table_name="quotes")
    op.drop_table("quotes")
