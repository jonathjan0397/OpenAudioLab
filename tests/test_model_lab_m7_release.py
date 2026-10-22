"""M7: release eligibility, canary routing, rollback, archive."""

from __future__ import annotations

import pytest

_SEQ = iter(range(1, 10000))


@pytest.fixture(autouse=True)
def _admin_session(client):
    from app.models import User

    client.post("/api/v1/auth/logout")
    email = f"m7admin{next(_SEQ)}@example.com"
    resp = client.post("/api/v1/auth/register",
                       json={"email": email, "username": f"m7a{next(_SEQ)}",
                             "password": "super-secret-1"})
    uid = resp.json()["user"]["id"]
    with client.app.state.db.session() as session:
        session.get(User, uid).role = "admin"
        session.commit()


def _released_bundle(client, name=None):
    from app.models import MlModelBundle, new_uuid

    with client.app.state.db.session() as session:
        b = MlModelBundle(id=new_uuid(), name=name or f"m7-b{next(_SEQ)}",
                          version="v1", kind="merged", base_model="m",
                          state="released", sha256="ef" * 32)
        session.add(b)
        session.commit()
        bid = b.id
    client.post(f"/api/v1/admin/model-lab/bundles/{bid}/evaluations",
                json={"kind": "objective", "verdict": "pass"})
    return bid


def test_promote_records_history_and_rollback(client) -> None:
    first = _released_bundle(client)
    second = _released_bundle(client)
    ch = client.post("/api/v1/admin/model-lab/release-channels/m7/promote",
                     json={"bundle_id": first})
    assert ch.status_code == 200 and ch.json()["previous_bundle_id"] is None
    ch2 = client.post("/api/v1/admin/model-lab/release-channels/m7/promote",
                      json={"bundle_id": second})
    assert ch2.json()["bundle"]["id"] == second
    assert ch2.json()["previous_bundle_id"] == first
    rb = client.post("/api/v1/admin/model-lab/release-channels/m7/rollback")
    assert rb.status_code == 200 and rb.json()["bundle"]["id"] == first
    # rollback swaps again (roll-forward)
    rb2 = client.post("/api/v1/admin/model-lab/release-channels/m7/rollback")
    assert rb2.json()["bundle"]["id"] == second


def test_resolve_eligibility_and_canary(client) -> None:
    bid = _released_bundle(client)
    client.post("/api/v1/admin/model-lab/release-channels/m7r/promote",
                json={"bundle_id": bid})
    off = client.get("/api/v1/admin/model-lab/release-channels/m7r/resolve").json()
    assert off == {"bundle_id": None, "reason": "channel_disabled"}
    client.patch("/api/v1/admin/model-lab/release-channels/m7r",
                 json={"enabled": True, "min_credits": 10})
    poor = client.get("/api/v1/admin/model-lab/release-channels/m7r/resolve"
                      "?owner_id=o1&credits=5").json()
    assert poor["reason"] == "credits_below_minimum"
    routed = client.get("/api/v1/admin/model-lab/release-channels/m7r/resolve"
                        "?owner_id=o1&credits=50").json()
    assert routed == {"bundle_id": bid, "reason": "routed"}
    # canary: 0% routes nobody, 100% routes everyone; deterministic per owner
    client.patch("/api/v1/admin/model-lab/release-channels/m7r",
                 json={"canary_percent": 0})
    out = client.get("/api/v1/admin/model-lab/release-channels/m7r/resolve"
                     "?owner_id=o1&credits=50").json()
    assert out["reason"] == "outside_canary"
    client.patch("/api/v1/admin/model-lab/release-channels/m7r",
                 json={"canary_percent": 100})
    again = client.get("/api/v1/admin/model-lab/release-channels/m7r/resolve"
                       "?owner_id=o1&credits=50").json()
    assert again["reason"] == "routed"
    bad = client.patch("/api/v1/admin/model-lab/release-channels/m7r",
                       json={"canary_percent": 140})
    assert bad.status_code == 422


def test_resolve_blocks_unready_bundle(client) -> None:
    from app.models import MlModelBundle

    bid = _released_bundle(client)
    promoted = client.post("/api/v1/admin/model-lab/release-channels/m7g/promote",
                           json={"bundle_id": bid})
    assert promoted.status_code == 200, promoted.text
    client.patch("/api/v1/admin/model-lab/release-channels/m7g",
                 json={"enabled": True})
    # a later failing verdict disqualifies the routed bundle
    with client.app.state.db.session() as session:
        session.get(MlModelBundle, bid).state = "released"
        session.commit()
    client.post(f"/api/v1/admin/model-lab/bundles/{bid}/evaluations",
                json={"kind": "ab", "verdict": "fail"})
    res = client.get("/api/v1/admin/model-lab/release-channels/m7g/resolve").json()
    assert res["reason"] == "gate_not_ready", res


def test_archive_transition(client) -> None:
    bid = _released_bundle(client)
    client.post(f"/api/v1/admin/model-lab/bundles/{bid}/retire")
    arch = client.post(f"/api/v1/admin/model-lab/bundles/{bid}/archive")
    assert arch.status_code == 200 and arch.json()["state"] == "archived"
    again = client.post(f"/api/v1/admin/model-lab/bundles/{bid}/archive")
    assert again.status_code == 409
