"""artist profile slugs

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _slugify(name: str) -> str:
    import re

    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:200] or "artist"


def upgrade() -> None:
    op.add_column("artist_profiles", sa.Column("slug", sa.String(length=220), nullable=True))
    op.create_index("ix_artist_profiles_slug", "artist_profiles", ["slug"], unique=True)
    conn = op.get_bind()
    rows = conn.execute(sa.text("select id, name from artist_profiles where slug is null")).fetchall()
    seen: set[str] = set()
    for row in rows:
        base = _slugify(row[1])
        slug = base
        counter = 2
        while slug in seen:
            slug = f"{base}-{counter}"
            counter += 1
        seen.add(slug)
        conn.execute(sa.text("update artist_profiles set slug=:s where id=:i"), {"s": slug, "i": row[0]})


def downgrade() -> None:
    op.drop_index("ix_artist_profiles_slug", table_name="artist_profiles")
    op.drop_column("artist_profiles", "slug")
