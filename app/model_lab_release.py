"""Model Lab M6: evaluations and explicit release channels.

Nothing promotes automatically: a channel may only point at a released
bundle, and the promotion gate reports machine-readable reasons instead of a
silent yes/no.
"""

from __future__ import annotations

from sqlalchemy import select

from .models import MlEvaluation, MlModelBundle, MlReleaseChannel, new_uuid

EVALUATION_KINDS = ("ab", "objective", "listener")
VERDICTS = ("win", "lose", "tie", "pass", "fail")


class ReleaseError(ValueError):
    pass


def record_evaluation(session, bundle_id: str, kind: str, scores: dict,
                      verdict: str | None = None, evaluator: str | None = None) -> MlEvaluation:
    if kind not in EVALUATION_KINDS:
        raise ReleaseError(f"unknown evaluation kind: {kind}")
    if verdict is not None and verdict not in VERDICTS:
        raise ReleaseError(f"unknown verdict: {verdict}")
    if session.get(MlModelBundle, bundle_id) is None:
        raise ReleaseError(f"unknown bundle: {bundle_id}")
    ev = MlEvaluation(id=new_uuid(), bundle_id=bundle_id, kind=kind,
                      scores_json=scores or {}, verdict=verdict, evaluator=evaluator)
    session.add(ev)
    session.commit()
    return ev


SATISFACTORY_VERDICTS = ("win", "pass")


def promotion_gate(session, bundle: MlModelBundle) -> dict:
    """Machine-readable readiness: released state + satisfactory verdict +
    artifact integrity. A `fail` verdict disqualifies regardless of others."""
    reasons: list[str] = []
    if bundle.state != "released":
        reasons.append(f"bundle is {bundle.state}, not released")
    evals = session.execute(
        select(MlEvaluation).where(MlEvaluation.bundle_id == bundle.id)).scalars().all()
    verdicts = [e.verdict for e in evals if e.verdict]
    if "fail" in verdicts:
        reasons.append("a failing evaluation verdict blocks promotion")
    elif not any(v in SATISFACTORY_VERDICTS for v in verdicts):
        reasons.append("no satisfactory evaluation verdict (win/pass) recorded")
    if not (bundle.sha256 or bundle.artifact_key):
        reasons.append("bundle has no artifact integrity (sha256 or artifact_key)")
    return {"ready": not reasons, "reasons": reasons, "evaluations": len(evals)}


def get_or_create_channel(session, name: str) -> MlReleaseChannel:
    channel = session.execute(
        select(MlReleaseChannel).where(MlReleaseChannel.name == name)).scalars().first()
    if channel is None:
        channel = MlReleaseChannel(id=new_uuid(), name=name)
        session.add(channel)
        session.commit()
    return channel


def promote_channel(session, name: str, bundle_id: str) -> MlReleaseChannel:
    """Explicit promotion: the target bundle must be released."""
    bundle = session.get(MlModelBundle, bundle_id)
    if bundle is None:
        raise ReleaseError(f"unknown bundle: {bundle_id}")
    if bundle.state != "released":
        raise ReleaseError(f"bundle {bundle.name} {bundle.version} is {bundle.state}; "
                           "only released bundles can be promoted")
    gate = promotion_gate(session, bundle)
    if not gate["ready"]:
        raise ReleaseError("promotion gate: " + "; ".join(gate["reasons"]))
    channel = get_or_create_channel(session, name)
    channel.bundle_id = bundle.id
    session.commit()
    return channel


def update_channel(session, name: str, *, enabled: bool | None = None,
                   min_credits: int | None = None) -> MlReleaseChannel:
    channel = get_or_create_channel(session, name)
    if enabled is not None:
        channel.enabled = enabled
    if min_credits is not None:
        if min_credits < 0:
            raise ReleaseError("min_credits must be >= 0")
        channel.min_credits = min_credits
    session.commit()
    return channel


def channel_view(session, channel: MlReleaseChannel) -> dict:
    bundle = session.get(MlModelBundle, channel.bundle_id) if channel.bundle_id else None
    return {"name": channel.name, "enabled": channel.enabled,
            "min_credits": channel.min_credits,
            "bundle": ({"id": bundle.id, "name": bundle.name, "version": bundle.version,
                        "state": bundle.state} if bundle else None)}
