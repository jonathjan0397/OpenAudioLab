"""Model Lab M4: frozen datasets, pilot budgets, budgeted training attempts.

Durable records are authoritative: an attempt only exists after its budget
headroom is verified, and spend/hours are booked back on completion. No GPU
work happens in the API process; the attempt carries the job that a GPU
worker claims.
"""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import select

from .models import (
    Job,
    MlBudget,
    MlDataset,
    MlRecording,
    MlTrainingAttempt,
    new_uuid,
    utcnow,
)

PILOT_BUDGET = "pilot"


class BudgetError(ValueError):
    pass


def get_budget(session, settings=None) -> MlBudget:
    budget = session.execute(
        select(MlBudget).where(MlBudget.name == PILOT_BUDGET)).scalars().first()
    if budget is None:
        budget = MlBudget(id=new_uuid(), name=PILOT_BUDGET,
                          max_hours=getattr(settings, "model_lab_pilot_max_hours", 6.0)
                          if settings else 6.0,
                          max_spend_usd=getattr(settings, "model_lab_pilot_max_spend_usd", 3.0)
                          if settings else 3.0)
        session.add(budget)
        session.commit()
    return budget


def update_budget(session, payload: dict) -> dict:
    budget = get_budget(session)
    for field in ("max_hours", "max_spend_usd"):
        if field in payload:
            try:
                value = float(payload[field])
            except (TypeError, ValueError):
                raise BudgetError(f"{field} must be numeric") from None
            if value < 0:
                raise BudgetError(f"{field} must be >= 0")
            setattr(budget, field, value)
    if "state" in payload:
        if payload["state"] not in ("open", "exhausted", "closed"):
            raise BudgetError(f"unknown budget state: {payload['state']}")
        budget.state = payload["state"]
    _refresh_state(budget)
    session.commit()
    return budget_view(budget)


def _refresh_state(budget: MlBudget) -> None:
    if budget.state == "closed":
        return
    exhausted = (budget.used_hours >= budget.max_hours
                 or budget.spent_usd >= budget.max_spend_usd)
    budget.state = "exhausted" if exhausted else "open"


def budget_view(budget: MlBudget) -> dict:
    return {"name": budget.name, "max_hours": budget.max_hours,
            "max_spend_usd": budget.max_spend_usd, "used_hours": budget.used_hours,
            "spent_usd": budget.spent_usd, "reserved_usd": budget.reserved_usd,
            "state": budget.state}


def freeze_dataset(session, name: str, recording_ids: list[str]) -> MlDataset:
    """Freeze an explicit selection of reviewed recordings into an immutable manifest."""
    if not recording_ids:
        raise ValueError("dataset needs at least one recording")
    recs = session.execute(
        select(MlRecording).where(MlRecording.id.in_(recording_ids))).scalars().all()
    found = {r.id for r in recs}
    missing = [r for r in recording_ids if r not in found]
    if missing:
        raise ValueError(f"unknown recordings: {', '.join(missing[:3])}")
    blocked = [r.id for r in recs if r.review_status != "approved"]
    if blocked:
        raise ValueError(f"recordings not approved for training: {len(blocked)}")
    from .model_lab import deterministic_caption
    entries = sorted(({"sha256": r.sha256, "path": r.path,
                       "seconds": r.duration_seconds or 0.0,
                       "caption": deterministic_caption(r, r.path)} for r in recs),
                     key=lambda e: e["sha256"])
    digest = hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()
    total = sum(e["seconds"] for e in entries)
    ds = MlDataset(id=new_uuid(), name=name, frozen_sha256=digest,
                   manifest_json={"entries": entries},
                   report_json={"total_seconds": round(total, 1),
                                "performers": len({r.artist for r in recs if r.artist})},
                   recording_count=len(recs), total_seconds=round(total, 1))
    session.add(ds)
    session.commit()
    return ds


def open_attempt(session, dataset: MlDataset, budget: MlBudget, *,
                 recipe: dict | None = None, est_hours: float = 1.0,
                 est_spend_usd: float = 0.25) -> MlTrainingAttempt:
    """Budget-gated dispatch with an atomic reservation.

    Headroom = max - (spent + reserved + estimate). Zero remaining budget
    allows no new spend; retries reserve again and cannot reset the budget.
    """
    _refresh_state(budget)
    if budget.state != "open":
        raise BudgetError(f"budget {budget.name} is {budget.state}")
    if budget.used_hours + est_hours > budget.max_hours:
        raise BudgetError(f"budget {budget.name}: no hour headroom for estimate {est_hours}h")
    if budget.spent_usd + budget.reserved_usd + est_spend_usd > budget.max_spend_usd:
        raise BudgetError(f"budget {budget.name}: no spend headroom for estimate ${est_spend_usd}")
    attempt = MlTrainingAttempt(id=new_uuid(), dataset_id=dataset.id, budget_id=budget.id,
                                state="queued", recipe_json=recipe or {},
                                reserved_usd=est_spend_usd)
    budget.reserved_usd = round(budget.reserved_usd + est_spend_usd, 4)
    session.add(attempt)
    session.commit()
    return attempt


def attach_job(session, attempt: MlTrainingAttempt, owner_id: str, settings) -> Job:
    """Create the durable model_lab.train job for a GPU worker to claim."""
    import hashlib as _hl

    request_json = {"attempt_id": attempt.id, "dataset_id": attempt.dataset_id,
                    "frozen_sha256": session.get(MlDataset, attempt.dataset_id).frozen_sha256}
    queue_model = getattr(settings, "train_queue_model_id", "training")
    job = Job(id=new_uuid(), owner_id=owner_id, operation="model_lab.train",
              model_id=queue_model, model_revision="model-lab",
              status="queued", request_json=request_json,
              request_hash=_hl.sha256(json.dumps(request_json, sort_keys=True).encode()).hexdigest(),
              idempotency_key=f"ml-attempt-{attempt.id}")
    session.add(job)
    attempt.job_id = job.id
    session.commit()
    return job


def settle_attempt(session, attempt: MlTrainingAttempt, *, state: str,
                   hours: float | None = None, spend_usd: float | None = None,
                   error: str | None = None, budget: MlBudget | None = None) -> dict:
    """Terminal outcome with idempotent budget settlement (replays re-book once)."""
    if state not in ("done", "failed", "cancelled"):
        raise BudgetError(f"unknown terminal state: {state}")
    attempt.state = state
    attempt.hours = hours
    attempt.spend_usd = spend_usd
    attempt.error = error
    attempt.finished_at = utcnow()
    if budget is not None and not attempt.settled:
        budget.reserved_usd = round(max(0.0, budget.reserved_usd - attempt.reserved_usd), 4)
        budget.used_hours = round(budget.used_hours + (hours or 0.0), 4)
        budget.spent_usd = round(budget.spent_usd + (spend_usd or 0.0), 4)
        attempt.settled = True
        _refresh_state(budget)
    session.commit()
    return {"id": attempt.id, "state": attempt.state, "hours": attempt.hours,
            "spend_usd": attempt.spend_usd}


# backwards-compatible alias used by earlier milestones/tests
complete_attempt = settle_attempt


def register_trained_bundle(session, attempt: MlTrainingAttempt, dataset: MlDataset,
                            result: dict, *, base_model: str = "ace-step-1.5"):
    """Register a trained adapter as an immutable candidate bundle (slice tail)."""
    from .models import MlModelBundle

    bundle = MlModelBundle(id=new_uuid(),
                           name=result.get("name") or f"{dataset.name}-adapter",
                           version="v1", kind="adapter", base_model=base_model,
                           state="candidate",
                           artifact_key=result.get("artifact_key"),
                           sha256=result.get("sha256"),
                           bundle_json={"attempt_id": attempt.id, "dataset_id": dataset.id,
                                        "frozen_sha256": dataset.frozen_sha256,
                                        "reload": result.get("reload"),
                                        "trainer_result": result})
    session.add(bundle)
    session.commit()
    return bundle


def attempt_view(attempt: MlTrainingAttempt) -> dict:
    return {"id": attempt.id, "dataset_id": attempt.dataset_id, "job_id": attempt.job_id,
            "state": attempt.state, "instance_id": attempt.instance_id,
            "worker_id": attempt.worker_id, "hours": attempt.hours,
            "spend_usd": attempt.spend_usd, "reserved_usd": attempt.reserved_usd,
            "settled": attempt.settled, "error": attempt.error}
