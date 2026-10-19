"""stripe billing columns

Revision ID: 0016
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("stripe_customer_id", sa.String(120), nullable=True))
    op.add_column("users", sa.Column("stripe_subscription_id", sa.String(120), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "stripe_subscription_id")
    op.drop_column("users", "stripe_customer_id")
