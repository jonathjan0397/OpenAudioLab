"""artist follows

Revision ID: 0011
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "artist_follows",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(80), nullable=False),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "profile_id"),
    )
    op.create_index("ix_artist_follows_owner_id", "artist_follows", ["owner_id"])
    op.create_index("ix_artist_follows_profile_id", "artist_follows", ["profile_id"])


def downgrade() -> None:
    op.drop_index("ix_artist_follows_profile_id", table_name="artist_follows")
    op.drop_index("ix_artist_follows_owner_id", table_name="artist_follows")
    op.drop_table("artist_follows")
