"""workspaces + workspace_songs (M17)

Revision ID: 0020
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(80)),
        sa.Column("name", sa.String(200)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_workspaces_owner_id", "workspaces", ["owner_id"])
    op.create_table(
        "workspace_songs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36)),
        sa.Column("owner_id", sa.String(80)),
        sa.Column("title", sa.String(200)),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("lyrics", sa.Text(), nullable=True),
        sa.Column("style_tags", sa.JSON()),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("instrumental", sa.Boolean(), default=False),
        sa.Column("asset_id", sa.String(36), nullable=True),
        sa.Column("job_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_workspace_songs_workspace_id", "workspace_songs", ["workspace_id"])
    op.create_index("ix_workspace_songs_owner_id", "workspace_songs", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_workspace_songs_owner_id", table_name="workspace_songs")
    op.drop_index("ix_workspace_songs_workspace_id", table_name="workspace_songs")
    op.drop_table("workspace_songs")
    op.drop_index("ix_workspaces_owner_id", table_name="workspaces")
    op.drop_table("workspaces")
