"""friendly track slugs: unique index on assets.slug + backfill

Revision ID: 0032
Revises: 0031
Create Date: 2026-10-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0032"
down_revision: Union[str, None] = "0031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from app.naming import slugify

    bind = op.get_bind()
    used = {r[0] for r in bind.execute(sa.text("SELECT slug FROM assets WHERE slug IS NOT NULL"))}
    rows = bind.execute(
        sa.text("SELECT id, title FROM assets WHERE slug IS NULL ORDER BY created_at ASC")
    ).all()
    for asset_id, title in rows:
        base = slugify(title) or f"track-{str(asset_id)[:6]}"
        candidate = base
        n = 2
        while candidate in used:
            candidate = f"{base[:74]}-{n}"
            n += 1
        candidate = candidate[:80]
        used.add(candidate)
        bind.execute(sa.text("UPDATE assets SET slug = :s WHERE id = :i"), {"s": candidate, "i": asset_id})

    op.create_index("uq_assets_slug", "assets", ["slug"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_assets_slug", table_name="assets")
