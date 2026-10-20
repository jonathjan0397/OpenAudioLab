"""worker health: last error + unhealthy cooldown

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("workers") as batch:
        batch.add_column(sa.Column("last_error", sa.String(300), nullable=True))
        batch.add_column(sa.Column("unhealthy_until", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("workers") as batch:
        batch.drop_column("unhealthy_until")
        batch.drop_column("last_error")
