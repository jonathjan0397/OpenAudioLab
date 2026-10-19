"""credit entry notes

Revision ID: 0017
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("credit_entries", sa.Column("note", sa.String(200), nullable=True))


def downgrade() -> None:
    op.drop_column("credit_entries", "note")
