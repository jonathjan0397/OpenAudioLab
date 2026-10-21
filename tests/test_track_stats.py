"""P2 remediation: aggregate library stats endpoint and plan allowance in /auth/me."""

from __future__ import annotations

from conftest import TOKEN_A, auth, submit_body


def _complete(client, orch, title: str, key: str) -> str:
    r = client.post(
        "/api/v1/jobs", json=submit_body(title=title), headers=auth(TOKEN_A, **{"Idempotency-Key": key})
    )
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    orch.dispatcher.publish_once()
    orch.worker.run_once()
    return job_id


def test_tracks_stats_counts(client, orch) -> None:
    before = client.get("/api/v1/tracks/stats", headers=auth(TOKEN_A)).json()
    assert before == {"total": 0, "shared": 0, "favorites": 0}

    job_a = _complete(client, orch, "Stat One", "st-1")
    _complete(client, orch, "Stat Two", "st-2")
    mid = client.get("/api/v1/tracks/stats", headers=auth(TOKEN_A)).json()
    assert mid["total"] > before["total"]

    tracks = client.get("/api/v1/tracks", headers=auth(TOKEN_A)).json()["tracks"]
    mix_a = next(t for t in tracks if t["job_id"] == job_a and t["role"] == "mix_wav")
    assert client.patch(f"/api/v1/artifacts/{mix_a['asset_id']}", json={"shared": True}, headers=auth(TOKEN_A)).status_code == 200
    assert client.post(f"/api/v1/artifacts/{mix_a['asset_id']}/favorite", headers=auth(TOKEN_A)).status_code in (200, 201)

    after = client.get("/api/v1/tracks/stats", headers=auth(TOKEN_A)).json()
    assert after["total"] == mid["total"]
    assert after["shared"] == 1
    assert after["favorites"] == 1


def test_me_includes_plan_allowance(client) -> None:
    client.post(
        "/api/v1/auth/register",
        json={"email": "allow@example.com", "password": "super-secret-1", "username": "allow"},
    )
    body = client.get("/api/v1/auth/me").json()
    assert body["allowance"]["plan"] == "free"
    assert body["allowance"]["monthly_credits"] == 0
