"""workspaces: asset membership (assets.workspace_id) + per-owner default space

Revision ID: 0029
Revises: 0028
Create Date: 2026-10-21

"""
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa

revision: str = "0029"
down_revision: Union[str, None] = "0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("assets", sa.Column("workspace_id", sa.String(36), nullable=True))
    op.create_index("ix_assets_workspace_id", "assets", ["workspace_id"])
    op.add_column(
        "workspaces",
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    bind = op.get_bind()
    owners = [
        r[0]
        for r in bind.execute(
            sa.text("SELECT DISTINCT owner_id FROM assets WHERE deleted_at IS NULL")
        )
    ]
    for owner in owners:
        existing = bind.execute(
            sa.text("SELECT id FROM workspaces WHERE owner_id = :o AND is_default AND deleted_at IS NULL LIMIT 1"),
            {"o": owner},
        ).first()
        if existing:
            wid = existing[0]
        else:
            wid = str(uuid.uuid4())
            bind.execute(
                sa.text(
                    "INSERT INTO workspaces (id, owner_id, name, is_default, created_at, updated_at)"
                    " VALUES (:i, :o, 'My Default Space', :d, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"i": wid, "o": owner, "d": True},
            )
        bind.execute(
            sa.text("UPDATE assets SET workspace_id = :w WHERE owner_id = :o AND workspace_id IS NULL"),
            {"w": wid, "o": owner},
        )


def downgrade() -> None:
    op.drop_index("ix_assets_workspace_id", table_name="assets")
    op.drop_column("assets", "workspace_id")
    op.drop_column("workspaces", "is_default")
