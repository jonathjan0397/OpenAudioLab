"""guest identity, Beginner pricing, signup policies, billing periods, admin records

Revision ID: 0025
"""

from typing import Sequence, Union
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

POLICY_VERSION = "2026-10-19.1"


def _pricing_table() -> sa.Table:
    return sa.table(
        "pricing",
        sa.column("id", sa.String),
        sa.column("kind", sa.String),
        sa.column("name", sa.String),
        sa.column("price_usd", sa.Integer),
        sa.column("credits", sa.Integer),
        sa.column("position", sa.Integer),
        sa.column("visible", sa.Boolean),
    )


def _policy_table() -> sa.Table:
    return sa.table(
        "policy_documents",
        sa.column("id", sa.String),
        sa.column("name", sa.String),
        sa.column("version", sa.String),
        sa.column("effective_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("subscription_status", sa.String(40), nullable=True))
        batch.add_column(sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True))
        batch.alter_column("credits_balance", existing_type=sa.Integer(), server_default="0")

    with op.batch_alter_table("credit_entries") as batch:
        batch.add_column(sa.Column("external_id", sa.String(160), nullable=True))
    op.create_index("ix_credit_entries_external_id", "credit_entries", ["external_id"], unique=True)

    with op.batch_alter_table("billing_events") as batch:
        batch.add_column(sa.Column("period_start", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("period_end", sa.DateTime(timezone=True), nullable=True))

    with op.batch_alter_table("pricing") as batch:
        batch.add_column(sa.Column("visible", sa.Boolean(), nullable=False, server_default=sa.true()))

    bind = op.get_bind()
    pricing = _pricing_table()
    existing_ids = {row[0] for row in bind.execute(sa.select(pricing.c.id)).all()}
    now = datetime.now(timezone.utc)

    if not existing_ids:
        defaults = [
            ("free", "plan", "Free account", 0, 0, 90, False),
            ("beginner", "plan", "Beginner", 5, 1000, 1, True),
            ("pro", "plan", "Pro", 8, 2500, 2, True),
            ("premier", "plan", "Premier", 24, 10000, 3, True),
            ("small", "pack", "Starter pack", 5, 1000, 10, True),
            ("medium", "pack", "Creator pack", 20, 5000, 11, True),
            ("large", "pack", "Studio pack", 45, 12000, 12, True),
        ]
        for row in defaults:
            bind.execute(
                sa.insert(pricing).values(
                    id=row[0], kind=row[1], name=row[2], price_usd=row[3], credits=row[4], position=row[5], visible=row[6]
                )
            )
    else:
        bind.execute(sa.update(pricing).where(pricing.c.id == "free").values(name="Free account", visible=False))
        if "beginner" not in existing_ids:
            bind.execute(
                sa.insert(pricing).values(
                    id="beginner", kind="plan", name="Beginner", price_usd=5, credits=1000, position=1, visible=True
                )
            )

    op.create_table(
        "guest_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("token_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("policy_version", sa.String(80), nullable=True),
        sa.Column("policy_accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("marketing_consent", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("claimed_user_id", sa.String(36), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_hash", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(300), nullable=True),
    )
    op.create_index("ix_guest_sessions_token_sha256", "guest_sessions", ["token_sha256"], unique=True)
    op.create_index("ix_guest_sessions_claimed_user_id", "guest_sessions", ["claimed_user_id"])

    op.create_table(
        "guest_quota_counters",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("guest_id", sa.String(36), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("limit", sa.Integer(), nullable=False, server_default="4"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("guest_id", "day"),
    )
    op.create_index("ix_guest_quota_counters_guest_id", "guest_quota_counters", ["guest_id"])

    op.create_table(
        "guest_quota_reservations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("guest_id", sa.String(36), nullable=False),
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("takes", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(20), nullable=False, server_default="reserved"),
        sa.Column("reason", sa.String(120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("guest_id", "job_id"),
    )
    op.create_index("ix_guest_quota_reservations_guest_id", "guest_quota_reservations", ["guest_id"])
    op.create_index("ix_guest_quota_reservations_job_id", "guest_quota_reservations", ["job_id"])
    op.create_index("ix_guest_quota_reservations_status", "guest_quota_reservations", ["status"])

    op.create_table(
        "policy_documents",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("version", sa.String(80), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    policy = _policy_table()
    for doc_id, name in (("terms", "Terms of Service"), ("abuse", "Abuse Policy"), ("privacy", "Privacy Notice")):
        bind.execute(
            sa.insert(policy).values(id=doc_id, name=name, version=POLICY_VERSION, effective_at=now, updated_at=now)
        )

    op.create_table(
        "policy_acceptances",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("subject_type", sa.String(20), nullable=False),
        sa.Column("subject_id", sa.String(80), nullable=False),
        sa.Column("policy_version", sa.String(80), nullable=False),
        sa.Column("documents_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("marketing_consent", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_hash", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(300), nullable=True),
        sa.UniqueConstraint("subject_type", "subject_id", "policy_version"),
    )
    op.create_index("ix_policy_acceptances_subject", "policy_acceptances", ["subject_type", "subject_id"])
    op.create_index("ix_policy_acceptances_policy_version", "policy_acceptances", ["policy_version"])

    op.create_table(
        "auth_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("purpose", sa.String(40), nullable=False),
        sa.Column("token_sha256", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_auth_tokens_user_id", "auth_tokens", ["user_id"])
    op.create_index("ix_auth_tokens_purpose", "auth_tokens", ["purpose"])
    op.create_index("ix_auth_tokens_token_sha256", "auth_tokens", ["token_sha256"], unique=True)

    op.create_table(
        "subscription_periods",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("plan", sa.String(40), nullable=False),
        sa.Column("stripe_subscription_id", sa.String(120), nullable=True),
        sa.Column("stripe_invoice_id", sa.String(120), nullable=True),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(40), nullable=False, server_default="recorded"),
        sa.Column("credits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("amount_usd", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("stripe_subscription_id", "period_start"),
    )
    op.create_index("ix_subscription_periods_user_id", "subscription_periods", ["user_id"])
    op.create_index("ix_subscription_periods_subscription", "subscription_periods", ["stripe_subscription_id"])
    op.create_index("ix_subscription_periods_invoice", "subscription_periods", ["stripe_invoice_id"])
    op.create_index("ix_subscription_periods_status", "subscription_periods", ["status"])

    op.create_table(
        "abuse_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("reporter_owner_id", sa.String(80), nullable=True),
        sa.Column("subject_type", sa.String(40), nullable=False, server_default="asset"),
        sa.Column("subject_id", sa.String(80), nullable=False),
        sa.Column("reason", sa.String(120), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("status", sa.String(40), nullable=False, server_default="open"),
        sa.Column("decision", sa.String(200), nullable=True),
        sa.Column("appeal_status", sa.String(40), nullable=True),
        sa.Column("decided_by", sa.String(80), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_abuse_reports_reporter", "abuse_reports", ["reporter_owner_id"])
    op.create_index("ix_abuse_reports_subject", "abuse_reports", ["subject_id"])
    op.create_index("ix_abuse_reports_status", "abuse_reports", ["status"])
    op.create_index("ix_abuse_reports_created_at", "abuse_reports", ["created_at"])

    op.create_table(
        "admin_audits",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("admin_id", sa.String(80), nullable=False),
        sa.Column("action", sa.String(120), nullable=False),
        sa.Column("target_type", sa.String(80), nullable=True),
        sa.Column("target_id", sa.String(80), nullable=True),
        sa.Column("reason", sa.String(300), nullable=True),
        sa.Column("context_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_admin_audits_admin_id", "admin_audits", ["admin_id"])
    op.create_index("ix_admin_audits_action", "admin_audits", ["action"])
    op.create_index("ix_admin_audits_target", "admin_audits", ["target_id"])
    op.create_index("ix_admin_audits_created_at", "admin_audits", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_admin_audits_created_at", table_name="admin_audits")
    op.drop_index("ix_admin_audits_target", table_name="admin_audits")
    op.drop_index("ix_admin_audits_action", table_name="admin_audits")
    op.drop_index("ix_admin_audits_admin_id", table_name="admin_audits")
    op.drop_table("admin_audits")

    op.drop_index("ix_abuse_reports_created_at", table_name="abuse_reports")
    op.drop_index("ix_abuse_reports_status", table_name="abuse_reports")
    op.drop_index("ix_abuse_reports_subject", table_name="abuse_reports")
    op.drop_index("ix_abuse_reports_reporter", table_name="abuse_reports")
    op.drop_table("abuse_reports")

    op.drop_index("ix_subscription_periods_status", table_name="subscription_periods")
    op.drop_index("ix_subscription_periods_invoice", table_name="subscription_periods")
    op.drop_index("ix_subscription_periods_subscription", table_name="subscription_periods")
    op.drop_index("ix_subscription_periods_user_id", table_name="subscription_periods")
    op.drop_table("subscription_periods")

    op.drop_index("ix_auth_tokens_token_sha256", table_name="auth_tokens")
    op.drop_index("ix_auth_tokens_purpose", table_name="auth_tokens")
    op.drop_index("ix_auth_tokens_user_id", table_name="auth_tokens")
    op.drop_table("auth_tokens")

    op.drop_index("ix_policy_acceptances_policy_version", table_name="policy_acceptances")
    op.drop_index("ix_policy_acceptances_subject", table_name="policy_acceptances")
    op.drop_table("policy_acceptances")
    op.drop_table("policy_documents")

    op.drop_index("ix_guest_quota_reservations_status", table_name="guest_quota_reservations")
    op.drop_index("ix_guest_quota_reservations_job_id", table_name="guest_quota_reservations")
    op.drop_index("ix_guest_quota_reservations_guest_id", table_name="guest_quota_reservations")
    op.drop_table("guest_quota_reservations")
    op.drop_index("ix_guest_quota_counters_guest_id", table_name="guest_quota_counters")
    op.drop_table("guest_quota_counters")
    op.drop_index("ix_guest_sessions_claimed_user_id", table_name="guest_sessions")
    op.drop_index("ix_guest_sessions_token_sha256", table_name="guest_sessions")
    op.drop_table("guest_sessions")

    with op.batch_alter_table("pricing") as batch:
        batch.drop_column("visible")

    with op.batch_alter_table("billing_events") as batch:
        batch.drop_column("period_end")
        batch.drop_column("period_start")

    op.drop_index("ix_credit_entries_external_id", table_name="credit_entries")
    with op.batch_alter_table("credit_entries") as batch:
        batch.drop_column("external_id")

    with op.batch_alter_table("users") as batch:
        batch.drop_column("email_verified_at")
        batch.drop_column("current_period_end")
        batch.drop_column("cancel_at_period_end")
        batch.drop_column("subscription_status")
        batch.alter_column("credits_balance", existing_type=sa.Integer(), server_default=None)
