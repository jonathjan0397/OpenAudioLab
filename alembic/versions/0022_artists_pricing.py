"""artist bio/avatar + artist_songs + pricing + users.deleted_at (M17)

Revision ID: 0022
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("artist_profiles", sa.Column("bio", sa.String(1000), nullable=True))
    op.add_column("artist_profiles", sa.Column("avatar_key", sa.String(200), nullable=True))
    op.add_column("users", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "artist_songs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("profile_id", sa.String(36)),
        sa.Column("owner_id", sa.String(80)),
        sa.Column("asset_id", sa.String(36)),
        sa.Column("position", sa.Integer(), default=0),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_artist_songs_profile_id", "artist_songs", ["profile_id"])
    op.create_index("ix_artist_songs_owner_id", "artist_songs", ["owner_id"])
    op.create_index("ix_artist_songs_asset_id", "artist_songs", ["asset_id"])
    op.create_table(
        "pricing",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("kind", sa.String(10)),
        sa.Column("name", sa.String(120)),
        sa.Column("price_usd", sa.Integer(), default=0),
        sa.Column("credits", sa.Integer(), default=0),
        sa.Column("position", sa.Integer(), default=0),
    )
    op.create_index("ix_pricing_kind", "pricing", ["kind"])


def downgrade() -> None:
    op.drop_index("ix_pricing_kind", table_name="pricing")
    op.drop_table("pricing")
    op.drop_index("ix_artist_songs_asset_id", table_name="artist_songs")
    op.drop_index("ix_artist_songs_owner_id", table_name="artist_songs")
    op.drop_index("ix_artist_songs_profile_id", table_name="artist_songs")
    op.drop_table("artist_songs")
    op.drop_column("users", "deleted_at")
    op.drop_column("artist_profiles", "avatar_key")
    op.drop_column("artist_profiles", "bio")
