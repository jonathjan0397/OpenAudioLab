"""durable generation manifest per asset (Milestone 3)

Revision ID: 0024
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: Union[str, None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("assets", sa.Column("manifest_json", sa.JSON(), nullable=False, server_default="{}"))


def downgrade() -> None:
    op.drop_column("assets", "manifest_json")
