"""Per-recording rights declarations + dataset kind (style|voice).

Revision ID: 0050
Revises: 0049
Create Date: 2026-10-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0050"
down_revision: Union[str, None] = "0049"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ml_datasets", sa.Column("kind", sa.String(length=12),
                                           nullable=False, server_default="style"))
    op.create_table(
        "ml_rights_records",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("recording_id", sa.String(length=36), nullable=False),
        sa.Column("holder", sa.String(length=200), nullable=False),
        sa.Column("scope", sa.String(length=24), nullable=False),
        sa.Column("purpose", sa.String(length=40), nullable=False,
                  server_default="house-training"),
        sa.Column("state", sa.String(length=12), nullable=False, server_default="declared"),
        sa.Column("evidence", sa.String(length=300), nullable=True),
        sa.Column("declared_by", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_ml_rights_records_recording_id", "ml_rights_records", ["recording_id"])


def downgrade() -> None:
    op.drop_index("ix_ml_rights_records_recording_id", table_name="ml_rights_records")
    op.drop_table("ml_rights_records")
    op.drop_column("ml_datasets", "kind")
