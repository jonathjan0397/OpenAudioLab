"""play events

Revision ID: 0013
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "play_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("asset_id", sa.String(36), nullable=False),
        sa.Column("viewer_id", sa.String(80), nullable=False, server_default="anon"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_play_events_asset_id", "play_events", ["asset_id"])


def downgrade() -> None:
    op.drop_index("ix_play_events_asset_id", table_name="play_events")
    op.drop_table("play_events")
