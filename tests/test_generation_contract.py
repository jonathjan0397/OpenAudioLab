"""Generation contract: strict control validation + independent idea/style/caption metadata.

Covers the CONTROL_UNSUPPORTED blocker repair and the first-class metadata fields.
"""

from __future__ import annotations

from conftest import submit_body  # noqa: F401

from app.db import Db
from app.models import IdempotencyRecord, Job
from sqlalchemy import func, select


def _job_count(client) -> int:
    db = Db(client.app.state.settings.database_url)
    with db.session() as session:
        return int(session.execute(select(func.count()).select_from(Job)).scalar_one())


def _post(client, body, key):
    return client.post("/api/v1/jobs", json=body, headers={"Authorization": "Bearer user-a-secret-token", "Idempotency-Key": key})


def test_free_text_controls_rejected_with_safe_field_details(client) -> None:
    """The original blocker: idea/style in the control bag are unsupported."""
    before = _job_count(client)
    response = _post(client, submit_body(controls={"description": "a story", "styles": "chill"}), key="gc-bad")
    assert response.status_code == 422
    err = response.json()["error"]
    assert err["code"] == "CONTROL_UNSUPPORTED"
    details = err["details"]
    assert details["unknown_controls"] == ["description", "styles"]
    assert "bpm" in details["supported_controls"]
    # Rejected requests must not create work, reserve, or bill.
    assert _job_count(client) == before
    db = Db(client.app.state.settings.database_url)
    with db.session() as session:
        rec = session.execute(
            select(IdempotencyRecord).where(IdempotencyRecord.key == "gc-bad")
        ).scalar_one_or_none()
    assert rec is None


def test_independent_metadata_accepted_and_persisted(client) -> None:
    """Fixed shape: free text lives as top-level metadata + caption, controls stay supported-only."""
    body = submit_body(
        music_description="a story about home, warm indie folk, female vocals",
        song_idea="a story about home",
        style_prompt="warm indie folk",
        controls={"mood": "warm", "gender": "female", "bpm": 92},
    )
    response = _post(client, body, key="gc-ok")
    assert response.status_code == 202, response.json()
    job_id = response.json()["job_id"]

    db = Db(client.app.state.settings.database_url)
    with db.session() as session:
        job = session.execute(select(Job).where(Job.id == job_id)).scalar_one()
    stored = job.request_json
    assert stored["song_idea"] == "a story about home"
    assert stored["style_prompt"] == "warm indie folk"
    # The engine caption is independent of the raw idea/style fields.
    assert stored["music_description"].startswith("a story about home")
    # Free text must not be in the control bag.
    assert "description" not in stored["controls"] and "styles" not in stored["controls"]
    assert stored["controls"]["bpm"] == 92


def test_legacy_recreation_hydration_fields_present(client) -> None:
    """mood/gender remain accepted controls so Studio recreation keeps round-tripping them."""
    response = _post(client, submit_body(controls={"mood": "chill", "gender": "male"}), key="gc-hydrate")
    assert response.status_code == 202
    db = Db(client.app.state.settings.database_url)
    with db.session() as session:
        job = session.execute(select(Job).where(Job.id == response.json()["job_id"])).scalar_one()
    assert job.request_json["controls"] == {"mood": "chill", "gender": "male"}


def test_control_out_of_range_rejected(client) -> None:
    before = _job_count(client)
    response = _post(client, submit_body(controls={"bpm": 999}), key="gc-range")
    assert response.status_code == 422
    err = response.json()["error"]
    assert err["code"] == "CONTROL_INVALID"
    invalid = err["details"]["invalid_controls"]
    assert any(item["control"] == "bpm" and item["code"] == "CONTROL_RANGE" for item in invalid)
    assert _job_count(client) == before  # rejected, no reservation


def test_control_wrong_type_rejected(client) -> None:
    response = _post(client, submit_body(controls={"bpm": "fast"}), key="gc-type")
    assert response.status_code == 422
    err = response.json()["error"]
    assert err["code"] == "CONTROL_INVALID"
    assert any(item["code"] == "CONTROL_TYPE" for item in err["details"]["invalid_controls"])


def test_shift_rejected_on_turbo(client) -> None:
    """shift is base-model only; the deployed Turbo release must not accept it."""
    response = _post(client, submit_body(controls={"shift": 3.0}), key="gc-shift")
    assert response.status_code == 422
    err = response.json()["error"]
    assert err["code"] == "CONTROL_UNSUPPORTED"
    assert "shift" in err["details"]["unknown_controls"]


def test_time_signature_accepted_and_forwarded_to_card(client) -> None:
    response = _post(client, submit_body(controls={"bpm": 90, "time_signature": "4/4"}), key="gc-ts")
    assert response.status_code == 202
    db = Db(client.app.state.settings.database_url)
    with db.session() as session:
        job = session.execute(select(Job).where(Job.id == response.json()["job_id"])).scalar_one()
    assert job.request_json["controls"]["time_signature"] == "4/4"


def test_adapter_forwards_time_signature() -> None:
    from app.engine_acestep import AceStepAdapter

    class _T:
        def post_json(self, *a, **k):  # pragma: no cover - not called here
            raise AssertionError

    payload = AceStepAdapter(_T(), model="acestep-v15-turbo").build_payload(
        music_description="test", lyrics=None, instrumental=True,
        seed=None, duration_seconds=30,
        controls={"bpm": 120, "key_scale": "Amin", "time_signature": "6/8"},
    )
    assert payload["time_signature"] == "6/8"
    assert payload["bpm"] == 120
    assert payload["key_scale"] == "Amin"


def test_model_detail_exposes_capabilities(client) -> None:
    body = client.get("/api/v1/models/ace-step-1.5").json()
    assert "cover" in body["supported_task_types"] and "repaint" in body["supported_task_types"]
    controls = {c["key"]: c for c in body["controls"]}
    assert controls["time_signature"]["applicable"] is True
    assert controls["shift"]["applicable"] is False  # base-only, discoverable but not effective
    assert controls["bpm"]["min"] == 20 and controls["bpm"]["max"] == 300

