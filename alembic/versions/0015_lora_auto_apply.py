"""lora auto-apply + priority

Revision ID: 0015
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("loras", sa.Column("auto_apply", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("loras", sa.Column("priority", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("loras", "priority")
    op.drop_column("loras", "auto_apply")
