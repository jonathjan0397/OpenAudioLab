"""billing events for payment/invoice/refund audit trail (Milestone 2)

Revision ID: 0023
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "billing_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(80), nullable=True),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("stripe_event_id", sa.String(120), nullable=True),
        sa.Column("checkout_session_id", sa.String(120), nullable=True),
        sa.Column("payment_intent_id", sa.String(120), nullable=True),
        sa.Column("invoice_id", sa.String(120), nullable=True),
        sa.Column("subscription_id", sa.String(120), nullable=True),
        sa.Column("kind", sa.String(20), nullable=True),
        sa.Column("item_id", sa.String(40), nullable=True),
        sa.Column("amount_usd", sa.Integer(), nullable=False, default=0),
        sa.Column("credits", sa.Integer(), nullable=False, default=0),
        sa.Column("status", sa.String(40), nullable=False, default="recorded"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_billing_events_owner_id", "billing_events", ["owner_id"])
    op.create_index("ix_billing_events_event_type", "billing_events", ["event_type"])
    op.create_index("ix_billing_events_stripe_event_id", "billing_events", ["stripe_event_id"], unique=True)
    op.create_index("ix_billing_events_checkout_session_id", "billing_events", ["checkout_session_id"])
    op.create_index("ix_billing_events_payment_intent_id", "billing_events", ["payment_intent_id"])
    op.create_index("ix_billing_events_invoice_id", "billing_events", ["invoice_id"])
    op.create_index("ix_billing_events_subscription_id", "billing_events", ["subscription_id"])
    op.create_index("ix_billing_events_created_at", "billing_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_billing_events_created_at", table_name="billing_events")
    op.drop_index("ix_billing_events_subscription_id", table_name="billing_events")
    op.drop_index("ix_billing_events_invoice_id", table_name="billing_events")
    op.drop_index("ix_billing_events_payment_intent_id", table_name="billing_events")
    op.drop_index("ix_billing_events_checkout_session_id", table_name="billing_events")
    op.drop_index("ix_billing_events_stripe_event_id", table_name="billing_events")
    op.drop_index("ix_billing_events_event_type", table_name="billing_events")
    op.drop_index("ix_billing_events_owner_id", table_name="billing_events")
    op.drop_table("billing_events")
