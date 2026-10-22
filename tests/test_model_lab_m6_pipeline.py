"""M6: merge strengths contract, exact-bundle routing, Creation Cards."""

from __future__ import annotations

import pytest

_SEQ = iter(range(1, 10000))


@pytest.fixture(autouse=True)
def _admin_session(client):
    from app.models import User

    client.post("/api/v1/auth/logout")
    email = f"m6pipe{next(_SEQ)}@example.com"
    resp = client.post("/api/v1/auth/register",
                       json={"email": email, "username": f"m6p{next(_SEQ)}",
                             "password": "super-secret-1"})
    uid = resp.json()["user"]["id"]
    with client.app.state.db.session() as session:
        session.get(User, uid).role = "admin"
        session.commit()


def _adapter(client) -> str:
    from app.models import Lora, new_uuid

    with client.app.state.db.session() as session:
        a = Lora(id=f"m6p-a{next(_SEQ)}", name=f"m6p-{next(_SEQ)}", kind="genre",
                 state="active")
        session.add(a)
        session.commit()
        return a.id


def _bundle(client, *, state="released", sha256="cd" * 32, **over):
    from app.models import MlModelBundle, new_uuid

    with client.app.state.db.session() as session:
        b = MlModelBundle(id=new_uuid(), name=f"m6p-b{next(_SEQ)}", version="v1",
                          kind="merged", base_model="m", state=state,
                          sha256=sha256, **over)
        session.add(b)
        session.commit()
        return b.id


def test_strength_validation(client) -> None:
    a, b = _adapter(client), _adapter(client)
    bad_len = client.post("/api/v1/admin/model-lab/merge-recipes",
                          json={"name": "s-bad", "base_model": "m",
                                "adapter_ids": [a, b],
                                "params": {"strengths": [0.5]}})
    assert bad_len.status_code == 422
    bad_range = client.post("/api/v1/admin/model-lab/merge-recipes",
                            json={"name": "s-bad2", "base_model": "m",
                                  "adapter_ids": [a, b],
                                  "params": {"strengths": [0.5, 1.4]}})
    assert bad_range.status_code == 422
    ok = client.post("/api/v1/admin/model-lab/merge-recipes",
                     json={"name": "s-ok", "base_model": "m", "adapter_ids": [a, b],
                           "params": {"strengths": [0.8, 0.2]}})
    assert ok.status_code == 201


def test_exact_bundle_routing_on_jobs(client) -> None:
    from conftest import submit_body

    headers = {"Authorization": "Bearer user-a-secret-token"}
    missing = client.post("/api/v1/jobs",
                          json=submit_body(bundle_id="ghost-bundle"),
                          headers={**headers, "Idempotency-Key": "m6-miss"})
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "BUNDLE_NOT_FOUND"

    building = _bundle(client, state="building", sha256=None)
    blocked = client.post("/api/v1/jobs", json=submit_body(bundle_id=building),
                          headers={**headers, "Idempotency-Key": "m6-build"})
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "BUNDLE_NOT_AVAILABLE"

    good = _bundle(client)
    accepted = client.post("/api/v1/jobs", json=submit_body(bundle_id=good),
                           headers={**headers, "Idempotency-Key": "m6-good"})
    assert accepted.status_code == 202
    from app.models import Job
    from sqlalchemy import select

    with client.app.state.db.session() as session:
        job = session.execute(select(Job).where(Job.id == accepted.json()["job_id"])
                              ).scalar_one()
        assert job.request_json["bundle_id"] == good


def test_creation_card(client) -> None:
    bid = _bundle(client)
    client.post(f"/api/v1/admin/model-lab/bundles/{bid}/evaluations",
                json={"kind": "ab", "verdict": "win"})
    card = client.get(f"/api/v1/admin/model-lab/bundles/{bid}/card").json()
    assert card["bundle_id"] == bid and card["state"] == "released"
    assert card["evaluations"] == [{"kind": "ab", "verdict": "win"}]
    assert card["gate"]["ready"] is True
    assert card["strengths"] == [] and card["adapters"] == []
    missing = client.get("/api/v1/admin/model-lab/bundles/nope/card")
    assert missing.status_code == 404
