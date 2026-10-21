"""per-workspace artist binding + main artist profile

Revision ID: 0031
Revises: 0030
Create Date: 2026-10-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0031"
down_revision: Union[str, None] = "0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column("artist_profile_id", sa.String(36), nullable=True),
    )
    op.create_index("ix_workspaces_artist_profile_id", "workspaces", ["artist_profile_id"])
    op.add_column(
        "artist_profiles",
        sa.Column("is_main", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    # Give every owner who has at least one profile a Main (earliest created).
    bind = op.get_bind()
    owners = [
        r[0]
        for r in bind.execute(
            sa.text(
                "SELECT DISTINCT owner_id FROM artist_profiles WHERE deleted_at IS NULL"
            )
        )
    ]
    for owner in owners:
        first = bind.execute(
            sa.text(
                "SELECT id FROM artist_profiles"
                " WHERE owner_id = :o AND deleted_at IS NULL"
                " ORDER BY created_at ASC LIMIT 1"
            ),
            {"o": owner},
        ).first()
        if first:
            bind.execute(
                sa.text("UPDATE artist_profiles SET is_main = :m WHERE id = :i"),
                {"m": True, "i": first[0]},
            )


def downgrade() -> None:
    op.drop_column("artist_profiles", "is_main")
    op.drop_index("ix_workspaces_artist_profile_id", table_name="workspaces")
    op.drop_column("workspaces", "artist_profile_id")
