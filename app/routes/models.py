"""Model discovery from the static registry stub."""

from __future__ import annotations

from fastapi import APIRouter

from ..errors import ApiError
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
