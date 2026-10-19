"""Policy version helpers."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings
from .models import PolicyAcceptance, PolicyDocument, utcnow


def current_policy_payload(session: Session, settings: Settings) -> dict:
    docs = list(session.execute(select(PolicyDocument).order_by(PolicyDocument.id)).scalars())
    if not docs:
        docs = [
            PolicyDocument(id="terms", name="Terms of Service", version=settings.policy_version),
            PolicyDocument(id="abuse", name="Abuse Policy", version=settings.policy_version),
            PolicyDocument(id="privacy", name="Privacy Notice", version=settings.policy_version),
        ]
        session.add_all(docs)
        session.commit()
    version = docs[0].version if docs else settings.policy_version
    return {
        "version": version,
        "documents": [{"id": d.id, "name": d.name, "version": d.version} for d in docs],
        "operator": settings.operator_name,
        "support_url": settings.support_url or settings.site_url,
    }


def record_policy_acceptance(
    session: Session,
    subject_type: str,
    subject_id: str,
    policy_version: str,
    marketing_consent: bool = False,
    ip_hash: str | None = None,
    user_agent: str | None = None,
) -> PolicyAcceptance:
    existing = session.execute(
        select(PolicyAcceptance).where(
            PolicyAcceptance.subject_type == subject_type,
            PolicyAcceptance.subject_id == subject_id,
            PolicyAcceptance.policy_version == policy_version,
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.marketing_consent = marketing_consent
        existing.accepted_at = utcnow()
        return existing
    acceptance = PolicyAcceptance(
        subject_type=subject_type,
        subject_id=subject_id,
        policy_version=policy_version,
        marketing_consent=marketing_consent,
        ip_hash=ip_hash,
        user_agent=user_agent,
    )
    session.add(acceptance)
    return acceptance


def has_policy_acceptance(session: Session, subject_type: str, subject_id: str, policy_version: str) -> bool:
    return (
        session.execute(
            select(PolicyAcceptance).where(
                PolicyAcceptance.subject_type == subject_type,
                PolicyAcceptance.subject_id == subject_id,
                PolicyAcceptance.policy_version == policy_version,
            )
        ).scalar_one_or_none()
        is not None
    )
