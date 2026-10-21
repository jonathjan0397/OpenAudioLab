"""admin catalog + unified Trash/purge + friendly slugs

Revision ID: 0030
Revises: 0029
Create Date: 2026-10-21

"""
from typing import Sequence, Union
from datetime import datetime, timedelta, timezone

from alembic import op
import sqlalchemy as sa

revision: str = "0030"
down_revision: Union[str, None] = "0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TRASH_PURGE_HOURS = 48


def upgrade() -> None:
    op.add_column(
        "assets",
        sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "assets",
        sa.Column("purge_after", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "assets",
        sa.Column("slug", sa.String(80), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("active_workspace_id", sa.String(36), nullable=True),
    )

    bind = op.get_bind()
    cutoff = datetime.now(timezone.utc) - timedelta(days=TRASH_PURGE_HOURS)
    rows = bind.execute(
        sa.text(
            "SELECT id, deleted_at FROM assets"
            " WHERE deleted_at IS NOT NULL AND purge_after IS NULL"
        )
    ).all()
    for asset_id, deleted_at in rows:
        if isinstance(deleted_at, str):
            deleted_at = datetime.fromisoformat(deleted_at.replace("Z", "+00:00"))
        if deleted_at is None:
            continue
        if deleted_at.tzinfo is None:
            deleted_at = deleted_at.replace(tzinfo=timezone.utc)
        purge_after = (deleted_at + timedelta(hours=TRASH_PURGE_HOURS)).isoformat()
        bind.execute(
            sa.text("UPDATE assets SET purge_after = :p WHERE id = :i"),
            {"p": purge_after, "i": asset_id},
        )


def downgrade() -> None:
    op.drop_column("users", "active_workspace_id")
    op.drop_column("assets", "slug")
    op.drop_column("assets", "purge_after")
    op.drop_column("assets", "purged_at")
