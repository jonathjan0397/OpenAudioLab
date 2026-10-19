"""worker telemetry: gpu util + vram

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("workers", sa.Column("gpu_util", sa.Integer(), nullable=True))
    op.add_column("workers", sa.Column("vram_used_mb", sa.Integer(), nullable=True))
    op.add_column("workers", sa.Column("vram_total_mb", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("workers", "vram_total_mb")
    op.drop_column("workers", "vram_used_mb")
    op.drop_column("workers", "gpu_util")
