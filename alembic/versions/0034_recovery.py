"""Recovery: jobs.next_retry_at (bounded retry) + job_attempts.upstream_task_id (duplicate-inference guard)

Revision ID: 0034
Revises: 0033
Create Date: 2026-10-21

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0034"
down_revision: Union[str, None] = "0033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("job_attempts", sa.Column("upstream_task_id", sa.String(120), nullable=True))


def downgrade() -> None:
    op.drop_column("job_attempts", "upstream_task_id")
    op.drop_column("jobs", "next_retry_at")
