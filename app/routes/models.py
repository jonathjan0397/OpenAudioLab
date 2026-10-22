"""Model discovery from the static registry stub + multi-model catalog."""

from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import select, func

from .. import catalog as _catalog
from ..errors import ApiError
from ..models import WorkerCapability
from ..registry import MODEL_RELEASES, control_capabilities
from ..schemas import ModelDetail, ModelSummary

router = APIRouter(tags=["models"])


def _summary(release) -> ModelSummary:
    return ModelSummary(
        model_id=release.model_id,
        display_name=release.display_name,
        enabled=release.enabled,
        availability="available" if release.enabled else "disabled",
        commercial_policy=release.commercial_policy,
        required_notices=list(release.required_notices),
        capabilities=release.capabilities,
    )


@router.get("/models", response_model=list[ModelSummary])
def list_models() -> list[ModelSummary]:
    return [_summary(release) for release in MODEL_RELEASES.values()]


@router.get("/models/{model_id}", response_model=ModelDetail)
def get_model(model_id: str) -> ModelDetail:
    release = MODEL_RELEASES.get(model_id)
    if release is None:
        raise ApiError(404, "MODEL_NOT_FOUND", "Unknown model id.")
    return ModelDetail(
        **_summary(release).model_dump(),
        revision=release.revision,
        license_status=release.license_status,
        supported_controls=list(release.supported_controls),
        supported_task_types=list(release.supported_task_types),
        model_family=release.model_family,
        controls=control_capabilities(model_id),
        supports_seed=release.supports_seed,
        supports_duration=release.supports_duration,
        min_duration_seconds=release.min_duration_seconds,
        max_duration_seconds=release.max_duration_seconds,
        output_options=list(release.output_options),
    )


@router.get("/model-selections")
def list_model_selections(request: Request) -> list[dict]:
    """Public product catalog: selections, profiles, availability, runnability,
    control ranges and pricing metadata. Server admission still enforces
    entitlement/availability; hiding is not access control. No private paths."""
    with request.app.state.db.session() as session:
        runnable = set(
            session.execute(
                select(WorkerCapability.model_selection, WorkerCapability.execution_profile_id).where(
                    WorkerCapability.enabled.is_(True)
                )
            ).all()
        )
        from .. import model_pricing as _mp

        mp = _mp.load(session)
    out = []
    for release in _catalog.CATALOG.values():
        profiles = []
        for p in release.profiles:
            profiles.append({
                "execution_profile_id": p.profile_id,
                "label": p.label,
                "quality_note": p.quality_note,
                "availability": _mp.effective_availability(p, mp),
                "display_name": _mp.effective_display_name(p, mp, p.label),
                "runnable": (p.model_selection, p.profile_id) in runnable,
                "requires_paid": release.family != "turbo",
                "experimental": release.experimental,
                "tasks": list(p.tasks),
                "control_ranges": {
                    "inference_steps": {"min": p.steps_min, "max": p.steps_max, "default": p.steps_default, "locked": p.cfg_locked or p.steps_min == p.steps_max},
                    "guidance_scale": {"min": p.cfg_min, "max": p.cfg_max, "default": p.cfg_default, "locked": p.cfg_locked},
                    "shift": {"min": p.shift_min, "max": p.shift_max, "default": p.shift_default},
                    "dcw_forced_off": p.dcw_forced_off,
                },
                "max_duration_seconds": p.max_duration_seconds,
                "max_batch": p.max_batch,
                "planner_model": p.planner_model,
                "pricing": {"multiplier": _mp.effective_multiplier(p, mp), "policy_version": _catalog.PRICE_POLICY_VERSION, "provisional": True},
            })
        out.append({
            "model_selection": release.selection,
            "display_name": (_mp.effective_display_name(release.profiles[0], mp, release.display_name)
                             if release.profiles else release.display_name),
            "family": release.family,
            "license_status": release.license_status,
            "experimental": release.experimental,
            "availability": release.availability,
            "runnable": any(pr["runnable"] for pr in profiles),
            "profiles": profiles,
        })
    return out
