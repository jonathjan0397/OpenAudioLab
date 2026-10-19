"""vast instance registry (recently used nodes for fast reuse)

Revision ID: 0019
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vast_instances",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("vast_instance_id", sa.String(60), unique=True),
        sa.Column("hostname", sa.String(120), nullable=True),
        sa.Column("role", sa.String(40), default="engine"),
        sa.Column("gpu_model", sa.String(120), nullable=True),
        sa.Column("state", sa.String(20), default="running"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_vast_instances_state", "vast_instances", ["state"])


def downgrade() -> None:
    op.drop_index("ix_vast_instances_state", table_name="vast_instances")
    op.drop_table("vast_instances")
