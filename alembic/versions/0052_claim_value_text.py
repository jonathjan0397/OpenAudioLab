"""Claim values widened to Text (LM captions/transcripts exceed 500 chars).

Revision ID: 0052
Revises: 0051
Create Date: 2026-10-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0052"
down_revision: Union[str, None] = "0051"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("ml_metadata_claims") as batch:
        batch.alter_column("value", existing_type=sa.String(length=500),
                           type_=sa.Text(), existing_nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("ml_metadata_claims") as batch:
        batch.alter_column("value", existing_type=sa.Text(),
                           type_=sa.String(length=500), existing_nullable=False)
