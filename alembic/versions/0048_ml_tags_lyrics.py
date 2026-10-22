"""Recording-level style tags state + verbatim lyrics with provenance.

Revision ID: 0048
Revises: 0047
Create Date: 2026-10-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0048"
down_revision: Union[str, None] = "0047"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ml_recordings", sa.Column("tags_state", sa.String(length=16),
                                             nullable=False, server_default="unparsed"))
    op.add_column("ml_recordings", sa.Column("tags_provenance_json", sa.JSON(),
                                             nullable=False, server_default=sa.text("'{}'")))
    op.add_column("ml_recordings", sa.Column("lyrics_text", sa.Text(), nullable=True))
    op.add_column("ml_recordings", sa.Column("lyrics_sha256", sa.String(length=64),
                                             nullable=True))
    op.add_column("ml_recordings", sa.Column("lyrics_origin", sa.String(length=20),
                                             nullable=True))
    op.add_column("ml_recordings", sa.Column("lyrics_provenance_json", sa.JSON(),
                                             nullable=False, server_default=sa.text("'{}'")))


def downgrade() -> None:
    for column in ("lyrics_provenance_json", "lyrics_origin", "lyrics_sha256",
                   "lyrics_text", "tags_provenance_json", "tags_state"):
        op.drop_column("ml_recordings", column)
