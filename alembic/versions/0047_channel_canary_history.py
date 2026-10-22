"""Release-channel canary percentage and rollback history.

Revision ID: 0047
Revises: 0046
Create Date: 2026-10-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0047"
down_revision: Union[str, None] = "0046"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ml_release_channels", sa.Column("previous_bundle_id",
                                                   sa.String(length=36), nullable=True))
    op.add_column("ml_release_channels", sa.Column("canary_percent", sa.Integer(),
                                                   nullable=False, server_default="100"))


def downgrade() -> None:
    op.drop_column("ml_release_channels", "canary_percent")
    op.drop_column("ml_release_channels", "previous_bundle_id")
