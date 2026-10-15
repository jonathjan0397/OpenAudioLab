"""initial jobs and idempotency records

Revision ID: 0001
Revises:
Create Date: 2026-10-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("seq", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=80), nullable=False),
        sa.Column("operation", sa.String(length=40), nullable=False),
        sa.Column("model_id", sa.String(length=80), nullable=False),
        sa.Column("model_revision", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("lyrics", sa.Text(), nullable=True),
        sa.Column("lyrics_sha256", sa.String(length=64), nullable=True),
        sa.Column("lyrics_origin", sa.String(length=20), nullable=True),
        sa.Column("client_reference", sa.String(length=200), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=60), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("assets_expired_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("seq"),
        sa.UniqueConstraint("id"),
    )
    op.create_index("ix_jobs_owner_id", "jobs", ["owner_id"])
    op.create_index("ix_jobs_owner_seq", "jobs", ["owner_id", "seq"])

    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("owner_id", sa.String(length=80), nullable=False),
        sa.Column("route", sa.String(length=120), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "route", "key", name="uq_idempotency_owner_route_key"),
    )


def downgrade() -> None:
    op.drop_table("idempotency_records")
    op.drop_index("ix_jobs_owner_seq", table_name="jobs")
    op.drop_index("ix_jobs_owner_id", "jobs")
    op.drop_table("jobs")
