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


def resolve_exact_bundle(session, bundle_id: str) -> MlModelBundle:
    """Exact-bundle routing: a named bundle is honored or the request fails.

    No silent substitution to another engine, tone or cloud provider.
    """
    bundle = session.get(MlModelBundle, bundle_id)
    if bundle is None:
        raise ReleaseError("BUNDLE_NOT_FOUND: no such model bundle")
    if bundle.state not in ("candidate", "released"):
        raise ReleaseError(f"BUNDLE_NOT_AVAILABLE: bundle is {bundle.state}")
    if not (bundle.sha256 or bundle.artifact_key):
        raise ReleaseError("BUNDLE_NOT_AVAILABLE: bundle has no artifact integrity")
    return bundle


def creation_card(session, bundle: MlModelBundle) -> dict:
    """Deterministic Creation Card: provenance, contract and evidence."""
    from .model_lab_merge import MlMergeRecipe

    bundle_json = bundle.bundle_json or {}
    recipe = (session.get(MlMergeRecipe, bundle_json.get("recipe_id"))
              if bundle_json.get("recipe_id") else None)
    evals = session.execute(
        select(MlEvaluation).where(MlEvaluation.bundle_id == bundle.id)).scalars().all()
    return {"bundle_id": bundle.id, "name": bundle.name, "version": bundle.version,
            "kind": bundle.kind, "base_model": bundle.base_model,
            "state": bundle.state,
            "method": recipe.method if recipe else bundle_json.get("method"),
            "adapters": (list(recipe.adapter_ids_json) if recipe
                         else bundle_json.get("adapter_ids", [])),
            "strengths": (recipe.params_json or {}).get("strengths", []) if recipe else [],
            "sha256": bundle.sha256, "artifact_key": bundle.artifact_key,
            "reload": bundle_json.get("reload"),
            "error": bundle_json.get("error"),
            "evaluations": [{"kind": e.kind, "verdict": e.verdict} for e in evals],
            "gate": promotion_gate(session, bundle)}


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
    channel.previous_bundle_id = channel.bundle_id
    channel.bundle_id = bundle.id
    session.commit()
    return channel


def rollback_channel(session, name: str) -> MlReleaseChannel:
    """One-step rollback to the previously promoted bundle."""
    channel = get_or_create_channel(session, name)
    if channel.previous_bundle_id is None:
        raise ReleaseError(f"channel {name} has no previous bundle to roll back to")
    channel.bundle_id, channel.previous_bundle_id = channel.previous_bundle_id, channel.bundle_id
    session.commit()
    return channel


def resolve_channel_bundle(session, name: str, *, owner_id: str, credits: int) -> dict:
    """Release eligibility + deterministic canary routing for one request."""
    import hashlib

    channel = get_or_create_channel(session, name)
    if not channel.enabled or channel.bundle_id is None:
        return {"bundle_id": None, "reason": "channel_disabled"}
    if credits < channel.min_credits:
        return {"bundle_id": None, "reason": "credits_below_minimum"}
    bundle = session.get(MlModelBundle, channel.bundle_id)
    if bundle is None or bundle.state != "released":
        return {"bundle_id": None, "reason": "bundle_not_released"}
    if not promotion_gate(session, bundle)["ready"]:
        return {"bundle_id": None, "reason": "gate_not_ready"}
    if channel.canary_percent < 100:
        bucket = int(hashlib.sha256(owner_id.encode()).hexdigest()[:8], 16) % 100
        if bucket >= channel.canary_percent:
            return {"bundle_id": None, "reason": "outside_canary"}
    return {"bundle_id": bundle.id, "reason": "routed"}


def update_channel(session, name: str, *, enabled: bool | None = None,
                   min_credits: int | None = None,
                   canary_percent: int | None = None) -> MlReleaseChannel:
    channel = get_or_create_channel(session, name)
    if enabled is not None:
        channel.enabled = enabled
    if min_credits is not None:
        if min_credits < 0:
            raise ReleaseError("min_credits must be >= 0")
        channel.min_credits = min_credits
    if canary_percent is not None:
        if not 0 <= canary_percent <= 100:
            raise ReleaseError("canary_percent must be within 0..100")
        channel.canary_percent = canary_percent
    session.commit()
    return channel


def channel_view(session, channel: MlReleaseChannel) -> dict:
    bundle = session.get(MlModelBundle, channel.bundle_id) if channel.bundle_id else None
    return {"name": channel.name, "enabled": channel.enabled,
            "min_credits": channel.min_credits,
            "canary_percent": channel.canary_percent,
            "previous_bundle_id": channel.previous_bundle_id,
            "bundle": ({"id": bundle.id, "name": bundle.name, "version": bundle.version,
                        "state": bundle.state} if bundle else None)}


def bundle_base_compatible(base_model: str | None, engine_model: str | None) -> bool:
    """LoRA families are checkpoint-incompatible across the xl boundary
    (hidden 2048 vs 2560). Same-family or unknown strings pass through,
    mirroring engine_worker._lora_compatible."""
    def is_xl(t: str | None) -> bool:
        return "xl" in (t or "").lower()
    base, engine = (base_model or "").strip(), (engine_model or "").strip()
    if not base or not engine:
        return True
    return is_xl(base) == is_xl(engine)
