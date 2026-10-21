"""Persona Compatibility Resolver (UAIS).

Given an Artist, a generation model selection and a fidelity requirement,
returns a validated execution plan derived from actual capability records and
adapter state -- never from model-name similarity. No acceptable method means
a structured compatibility error, not a song with the wrong voice.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import ApiError
from ..models import VoiceAdapter, VoiceDataset, VoiceProfile, VoiceRecording
from .capabilities import capability

NATIVE_ADAPTER_READY = "NATIVE_ADAPTER_READY"
ADAPTER_VALIDATION_REQUIRED = "ADAPTER_VALIDATION_REQUIRED"
REFERENCE_CONDITIONING_AVAILABLE = "REFERENCE_CONDITIONING_AVAILABLE"
ADAPTER_TRAINING_REQUIRED = "ADAPTER_TRAINING_REQUIRED"
PREPARING = "PREPARING"
UNSUPPORTED = "UNSUPPORTED"
FAILED = "FAILED"

FIDELITIES = ("native", "reference", "best")

_STATE_RANK = {"validated": 0, "ready": 1, "stale": 2, "training": 3, "failed": 4}


def _adapters_for(session: Session, artist_profile_id: str, model_selection: str) -> list[VoiceAdapter]:
    rows = list(session.execute(
        select(VoiceAdapter)
        .where(
            VoiceAdapter.artist_profile_id == artist_profile_id,
            VoiceAdapter.model_selection == model_selection,
            VoiceAdapter.state != "retired",
        )
        .order_by(VoiceAdapter.created_at.desc())
    ).scalars())
    return sorted(rows, key=lambda a: (_STATE_RANK.get(a.state, 9), a.created_at), reverse=False)


def _reference_asset(session: Session, artist_profile_id: str) -> str | None:
    rows = list(session.execute(
        select(VoiceRecording)
        .where(VoiceRecording.artist_profile_id == artist_profile_id, VoiceRecording.state == "active")
        .order_by(VoiceRecording.added_at.desc())
    ).scalars())
    usable = [r for r in rows if (r.qc_json or {}).get("verdict") == "usable"]
    pick = (usable or rows)
    return pick[0].asset_id if pick else None


def _profile_version(session: Session, artist_profile_id: str) -> int | None:
    profile = session.execute(
        select(VoiceProfile)
        .where(VoiceProfile.artist_profile_id == artist_profile_id)
        .order_by(VoiceProfile.version_number.desc())
    ).scalars().first()
    return profile.version_number if profile else None


def _dataset_version_count(session: Session, artist_profile_id: str) -> int:
    dataset = session.execute(
        select(VoiceDataset).where(VoiceDataset.artist_profile_id == artist_profile_id)
    ).scalars().first()
    return dataset.latest_version_number if dataset else 0


def compatibility(session: Session, owner_id: str, artist_profile_id: str, model_selection: str) -> dict:
    cap = capability(model_selection)
    base = {"model_selection": model_selection,
            "voice_profile_version": _profile_version(session, artist_profile_id)}
    if cap is None or cap.adapter_format is None or cap.training_recipe is None:
        return {**base, "state": UNSUPPORTED, "adapter_id": None,
                "detail": "Model has no verified voice-adapter path."}
    adapter = _adapters_for(session, artist_profile_id, model_selection)
    if adapter:
        best = adapter[0]
        if best.state == "validated":
            return {**base, "state": NATIVE_ADAPTER_READY, "adapter_id": best.id}
        if best.state == "training":
            return {**base, "state": PREPARING, "adapter_id": best.id}
        if best.state == "failed":
            return {**base, "state": FAILED, "adapter_id": best.id,
                    "detail": best.error_message or "Adapter training failed."}
        return {**base, "state": ADAPTER_VALIDATION_REQUIRED, "adapter_id": best.id}
    if _dataset_version_count(session, artist_profile_id) == 0:
        return {**base, "state": REFERENCE_CONDITIONING_AVAILABLE, "adapter_id": None,
                "detail": "No frozen training data; reference conditioning is the baseline."}
    return {**base, "state": ADAPTER_TRAINING_REQUIRED, "adapter_id": None}


def compatibility_matrix(session: Session, owner_id: str, artist_profile_id: str) -> list[dict]:
    from ..catalog import CATALOG

    return [compatibility(session, owner_id, artist_profile_id, selection)
            for selection in CATALOG]


def resolve_plan(session: Session, owner_id: str, artist_profile_id: str,
                 model_selection: str, fidelity: str = "best") -> dict:
    cap = capability(model_selection)
    if cap is None:
        raise ApiError(422, "MODEL_VOICE_UNSUPPORTED",
                       "This generation model has no registered voice capability manifest.",
                       {"model_selection": model_selection})
    compat = compatibility(session, owner_id, artist_profile_id, model_selection)
    version = compat["voice_profile_version"]

    if fidelity == "native":
        if compat["state"] == NATIVE_ADAPTER_READY:
            return _native_plan(session, compat["adapter_id"], model_selection, version, "VALIDATED")
        if compat["state"] == ADAPTER_VALIDATION_REQUIRED:
            raise ApiError(409, "VOICE_VALIDATION_REQUIRED",
                           "The adapter is trained but not identity-validated; run validation or choose best fidelity.",
                           compat)
        raise ApiError(409, "VOICE_NOT_READY", "No native adapter exists for this model.", compat)

    if fidelity == "reference":
        if cap.reference_conditioning is None:
            raise ApiError(422, "REFERENCE_CONDITIONING_UNSUPPORTED",
                           "This model has no reference-conditioning path.", compat)
        asset_id = _reference_asset(session, artist_profile_id)
        if asset_id is None:
            raise ApiError(409, "VOICE_NOT_READY", "The artist has no approved reference recordings.", compat)
        return {"artist_id": artist_profile_id, "voice_profile_version": version,
                "model": model_selection, "voice_method": "reference", "adapter_id": None,
                "dataset_version": None, "reference_asset_id": asset_id,
                "validation_status": "REFERENCE", "generation_ready": True,
                "note": "Reference conditioning does not guarantee stable singer identity."}

    # best: validated native > load-tested native > reference baseline
    if compat["state"] == NATIVE_ADAPTER_READY:
        return _native_plan(session, compat["adapter_id"], model_selection, version, "VALIDATED")
    if compat["state"] == ADAPTER_VALIDATION_REQUIRED:
        return _native_plan(session, compat["adapter_id"], model_selection, version, "LOAD_TESTED")
    if cap.reference_conditioning is not None:
        asset_id = _reference_asset(session, artist_profile_id)
        if asset_id is not None:
            return {"artist_id": artist_profile_id, "voice_profile_version": version,
                    "model": model_selection, "voice_method": "reference", "adapter_id": None,
                    "dataset_version": None, "reference_asset_id": asset_id,
                    "validation_status": "REFERENCE", "generation_ready": True,
                    "note": "No validated adapter; using reference conditioning."}
    raise ApiError(409, "VOICE_NOT_READY", "No acceptable voice method is available for this artist and model.",
                   compat)


def _native_plan(session: Session, adapter_id: str, model_selection: str,
                 version: int | None, validation_status: str) -> dict:
    adapter = session.get(VoiceAdapter, adapter_id)
    return {"artist_id": adapter.artist_profile_id if adapter else None,
            "voice_profile_version": version, "model": model_selection,
            "voice_method": "native", "adapter_id": adapter_id,
            "dataset_version": adapter.dataset_version_id if adapter else None,
            "reference_asset_id": None, "validation_status": validation_status,
            "generation_ready": True}
