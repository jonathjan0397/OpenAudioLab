"""Model Lab M6: evaluation records, promotion gate, release channels."""

from __future__ import annotations

import pytest

_SEQ = iter(range(1, 10000))


@pytest.fixture(autouse=True)
def _admin_session(client):
    from app.models import User

    client.post("/api/v1/auth/logout")
    email = f"ml6admin{next(_SEQ)}@example.com"
    resp = client.post("/api/v1/auth/register",
                       json={"email": email, "username": f"ml6a{next(_SEQ)}",
                             "password": "super-secret-1"})
    uid = resp.json()["user"]["id"]
    with client.app.state.db.session() as session:
        session.get(User, uid).role = "admin"
        session.commit()


def _bundle(client, state="candidate"):
    from app.models import MlModelBundle, new_uuid

    with client.app.state.db.session() as session:
        b = MlModelBundle(id=new_uuid(), name=f"b-{next(_SEQ)}", version="v1",
                          kind="merged", base_model="ace-step-1.5", state=state,
            sha256="ab" * 32, artifact_key="ml/test/model.pt")
        session.add(b)
        session.commit()
        return b.id


def test_evaluation_validation(client) -> None:
    bid = _bundle(client)
    bad_kind = client.post(f"/api/v1/admin/model-lab/bundles/{bid}/evaluations",
                           json={"kind": "vibes"})
    assert bad_kind.status_code == 422
    bad_verdict = client.post(f"/api/v1/admin/model-lab/bundles/{bid}/evaluations",
                              json={"kind": "ab", "verdict": "crush"})
    assert bad_verdict.status_code == 422
    missing = client.post("/api/v1/admin/model-lab/bundles/nope/evaluations",
                          json={"kind": "ab"})
    assert missing.status_code == 422
    ok = client.post(f"/api/v1/admin/model-lab/bundles/{bid}/evaluations",
                     json={"kind": "ab", "scores": {"a": 7, "b": 3}, "verdict": "win"})
    assert ok.status_code == 201
    listed = client.get(f"/api/v1/admin/model-lab/bundles/{bid}/evaluations").json()
    assert len(listed["evaluations"]) == 1


def test_promotion_gate_reasons(client) -> None:
    bid = _bundle(client)  # candidate, no evals
    gate = client.get(f"/api/v1/admin/model-lab/bundles/{bid}/promotion-gate").json()
    assert gate["ready"] is False and len(gate["reasons"]) == 2
    client.post(f"/api/v1/admin/model-lab/bundles/{bid}/evaluations",
                json={"kind": "objective", "verdict": "pass"})
    client.post(f"/api/v1/admin/model-lab/bundles/{bid}/release")
    gate = client.get(f"/api/v1/admin/model-lab/bundles/{bid}/promotion-gate").json()
    assert gate["ready"] is True and gate["evaluations"] == 1


def test_channel_promotion_requires_released_bundle(client) -> None:
    bid = _bundle(client)
    blocked = client.post("/api/v1/admin/model-lab/release-channels/stable/promote",
                          json={"bundle_id": bid})
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "PROMOTION_BLOCKED"
    client.post(f"/api/v1/admin/model-lab/bundles/{bid}/release")
    client.post(f"/api/v1/admin/model-lab/bundles/{bid}/evaluations",
                json={"kind": "objective", "verdict": "pass"})
    ok = client.post("/api/v1/admin/model-lab/release-channels/stable/promote",
                     json={"bundle_id": bid})
    assert ok.status_code == 200 and ok.json()["bundle"]["state"] == "released"
    patch = client.patch("/api/v1/admin/model-lab/release-channels/stable",
                         json={"enabled": True, "min_credits": 10})
    assert patch.json()["enabled"] is True and patch.json()["min_credits"] == 10
    channels = client.get("/api/v1/admin/model-lab/release-channels").json()["channels"]
    assert any(c["name"] == "stable" and c["enabled"] for c in channels)


def test_channel_promote_unknown_bundle(client) -> None:
    r = client.post("/api/v1/admin/model-lab/release-channels/canary/promote",
                    json={"bundle_id": "missing"})
    assert r.status_code == 409
