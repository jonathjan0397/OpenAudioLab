"""ml_recordings.format widened (ffprobe multi-container names exceed 20).

Revision ID: 0053
Revises: 0052
Create Date: 2026-10-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0053"
down_revision: Union[str, None] = "0052"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("ml_recordings") as batch:
        batch.alter_column("format", existing_type=sa.String(length=20),
                           type_=sa.String(length=120), existing_nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("ml_recordings") as batch:
        batch.alter_column("format", existing_type=sa.String(length=120),
                           type_=sa.String(length=20), existing_nullable=True)
