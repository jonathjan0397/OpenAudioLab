"""Widen site_settings.value for the model_pricing blob

Revision ID: 0043
Revises: 0042
Create Date: 2026-10-22

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0043"
down_revision: Union[str, None] = "0042"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("site_settings") as batch:
        batch.alter_column("value", existing_type=sa.String(500), type_=sa.String(2000),
                           existing_nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("site_settings") as batch:
        batch.alter_column("value", existing_type=sa.String(2000), type_=sa.String(500),
                           existing_nullable=False)
