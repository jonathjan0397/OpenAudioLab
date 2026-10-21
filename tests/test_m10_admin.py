"""M10: admin console endpoints (services, storage, billing, audit, workers, extended stats)."""

from __future__ import annotations


def _seed_admin(client, email: str) -> None:
    from app.models import User

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


def test_admin_services(client) -> None:
    _seed_admin(client, "m10-svc@example.com")
    response = client.get("/api/v1/admin/services")
    assert response.status_code == 200
    services = response.json()["services"]
    assert [s["operation"] for s in services] == ["music.generate", "audio.export", "voice.train"]
    assert all(s["status"] in ("healthy", "busy") for s in services)


def test_admin_storage(client) -> None:
    _seed_admin(client, "m10-sto@example.com")
    response = client.get("/api/v1/admin/storage")
    assert response.status_code == 200
    body = response.json()
    assert body["quota_bytes"] == 5 * 1024**4
    assert set(body["categories"]) == {"generated_audio", "training_data", "model_checkpoints", "other"}


def test_admin_billing(client) -> None:
    _seed_admin(client, "m10-bil@example.com")
    response = client.get("/api/v1/admin/billing")
    assert response.status_code == 200
    body = response.json()
    assert body["credits_quota"] == 1_000_000
    assert body["credits_granted"] >= 1000  # signup grant recorded


def test_admin_audit(client) -> None:
    _seed_admin(client, "m10-aud@example.com")
    response = client.get("/api/v1/admin/audit")
    assert response.status_code == 200
    assert isinstance(response.json()["items"], list)
    assert "total" in response.json()


def test_admin_workers(client) -> None:
    _seed_admin(client, "m10-wor@example.com")
    response = client.get("/api/v1/admin/workers")
    assert response.status_code == 200
    assert response.json()["workers"] == []


def test_admin_stats_extended_fields(client) -> None:
    _seed_admin(client, "m10-sta@example.com")
    response = client.get("/api/v1/admin/stats")
    body = response.json()
    for key in ("active_users_30d", "jobs_yesterday", "gpu_util_avg", "revenue", "credits_used", "credits_quota"):
        assert key in body


def test_admin_timeseries_granularity_and_task(client) -> None:
    _seed_admin(client, "m10-tim@example.com")
    response = client.get("/api/v1/admin/stats/timeseries?granularity=hour")
    assert response.status_code == 200
    body = response.json()
    assert body["granularity"] == "hour"
    assert len(body["series"]) == 24

    response = client.get("/api/v1/admin/stats/timeseries?days=3&task=generate")
    assert response.status_code == 200
    assert len(response.json()["series"]) == 3


def test_admin_jobs_labels_and_filters(client) -> None:
    _seed_admin(client, "m10-job@example.com")
    response = client.get("/api/v1/admin/jobs?limit=5")
    assert response.status_code == 200
    assert isinstance(response.json()["items"], list)
    assert "total" in response.json()


def test_admin_trainings_join(client) -> None:
    _seed_admin(client, "m10-trn@example.com")
    response = client.get("/api/v1/admin/trainings?limit=8")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
