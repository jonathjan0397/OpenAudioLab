"""Voice recordings accept submitted lyrics (verbatim + SHA-256, invariant 1).

Revision ID: 0051
Revises: 0050
Create Date: 2026-10-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0051"
down_revision: Union[str, None] = "0050"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("voice_recordings", sa.Column("lyrics_text", sa.Text(), nullable=True))
    op.add_column("voice_recordings", sa.Column("lyrics_sha256", sa.String(length=64),
                                                nullable=True))


def downgrade() -> None:
    op.drop_column("voice_recordings", "lyrics_sha256")
    op.drop_column("voice_recordings", "lyrics_text")
