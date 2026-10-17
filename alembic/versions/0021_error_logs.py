"""error_logs (M17 advanced error logging)

Revision ID: 0021
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "error_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("component", sa.String(40)),
        sa.Column("route", sa.String(120), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(60)),
        sa.Column("message", sa.Text()),
        sa.Column("traceback", sa.Text(), nullable=True),
        sa.Column("context_json", sa.JSON()),
        sa.Column("job_id", sa.String(36), nullable=True),
        sa.Column("worker_id", sa.String(120), nullable=True),
        sa.Column("user_id", sa.String(80), nullable=True),
        sa.Column("fingerprint", sa.String(160), nullable=True),
        sa.Column("resolved", sa.Boolean(), default=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_error_logs_component", "error_logs", ["component"])
    op.create_index("ix_error_logs_error_code", "error_logs", ["error_code"])
    op.create_index("ix_error_logs_created_at", "error_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_error_logs_created_at", table_name="error_logs")
    op.drop_index("ix_error_logs_error_code", table_name="error_logs")
    op.drop_index("ix_error_logs_component", table_name="error_logs")
    op.drop_table("error_logs")
