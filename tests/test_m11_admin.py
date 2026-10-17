"""M11: API keys, environment setting, credit ledger, worker drain, job detail, training cancel."""

from __future__ import annotations

from datetime import timedelta

from app.models import User, Worker, utcnow


def _seed_admin(client, email: str) -> None:
    client.post("/api/v1/auth/logout")
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "username": email.split("@")[0].replace(".", ""), "password": "super-secret-1"},
    )
    uid = response.json()["user"]["id"]
    with client.app.state.db.session() as session:
        user = session.get(User, uid)
        user.role = "admin"
        session.commit()


def test_api_key_lifecycle(client) -> None:
    _seed_admin(client, "m11-key@example.com")
    created = client.post("/api/v1/api-keys", json={"name": "laptop"})
    assert created.status_code == 201
    secret = created.json()["secret"]
    assert secret.startswith("oal_")
    key_id = created.json()["id"]

    listed = client.get("/api/v1/api-keys")
    assert listed.status_code == 200
    assert [k["id"] for k in listed.json()["items"]] == [key_id]

    # The key authenticates as the same owner as the cookie session.
    me = client.get("/api/v1/artist-profiles", headers={"Authorization": f"Bearer {secret}"})
    assert me.status_code == 200
    after_use = client.get("/api/v1/api-keys").json()["items"][0]
    assert after_use["last_used_at"] is not None

    revoked = client.delete(f"/api/v1/api-keys/{key_id}")
    assert revoked.status_code == 200
    assert revoked.json()["revoked_at"] is not None

    other = client.delete("/api/v1/api-keys/nope")
    assert other.status_code == 404


def test_api_key_unknown_token_falls_back(client) -> None:
    _seed_admin(client, "m11-fb@example.com")
    response = client.get("/api/v1/artist-profiles", headers={"Authorization": "Bearer not-a-real-key"})
    assert response.status_code == 200


def test_environment_setting(client) -> None:
    _seed_admin(client, "m11-env@example.com")
    bad = client.put("/api/v1/admin/settings/environment", json={"value": "qa"})
    assert bad.status_code == 422
    ok = client.put("/api/v1/admin/settings/environment", json={"value": "staging"})
    assert ok.status_code == 200
    settings = client.get("/api/v1/admin/settings").json()["settings"]
    assert settings["environment"] == "staging"


def test_credits_ledger(client) -> None:
    _seed_admin(client, "m11-cre@example.com")
    response = client.get("/api/v1/admin/credits")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["items"], list)
    assert body["total"] >= 0


def test_worker_drain_toggle(client) -> None:
    _seed_admin(client, "m11-dra@example.com")
    with client.app.state.db.session() as session:
        session.add(Worker(id="w-m11", kind="acestep", last_heartbeat=utcnow()))
        session.commit()
    first = client.post("/api/v1/admin/workers/w-m11/drain")
    assert first.status_code == 200
    assert first.json()["drain"] is True
    second = client.post("/api/v1/admin/workers/w-m11/drain")
    assert second.json()["drain"] is False
    missing = client.post("/api/v1/admin/workers/w-none/drain")
    assert missing.status_code == 404


def test_worker_purge_stale(client) -> None:
    _seed_admin(client, "m11-pur@example.com")
    now = utcnow()
    with client.app.state.db.session() as session:
        session.add(Worker(id="w-old", kind="acestep", last_heartbeat=now - timedelta(hours=30)))
        session.add(Worker(id="w-new", kind="audio", last_heartbeat=now))
        session.commit()
    purged = client.delete("/api/v1/admin/workers/stale")
    assert purged.status_code == 200
    assert purged.json()["purged"] == 1
    remaining = {w["id"] for w in client.get("/api/v1/admin/workers").json()["workers"]}
    assert remaining == {"w-new"}


def test_job_detail_with_events(client) -> None:
    from conftest import submit

    _seed_admin(client, "m11-det@example.com")
    missing = client.get("/api/v1/admin/jobs/does-not-exist")
    assert missing.status_code == 404
    created = submit(client, key="m11-detail")
    assert created.status_code == 202
    job_id = created.json()["job_id"]
    detail = client.get(f"/api/v1/admin/jobs/{job_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["job_id"] == job_id
    assert isinstance(body["events"], list) and body["events"]
    assert body["task"] == "Text to Music"


def test_training_cancel_missing(client) -> None:
    _seed_admin(client, "m11-can@example.com")
    response = client.post("/api/v1/admin/trainings/nope/cancel")
    assert response.status_code == 404
