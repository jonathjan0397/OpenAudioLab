"""M19: active workspace routing (server-side selection + generation stamping)."""

from __future__ import annotations

from sqlalchemy import select

from conftest import TOKEN_A, auth, submit_body

WS = "/api/v1/workspaces"


def _login(client, email: str) -> str:
    client.post("/api/v1/auth/logout")
    r = client.post(
        "/api/v1/auth/register",
        json={"email": email, "username": email.split("@")[0].replace(".", ""), "password": "super-secret-1"},
    )
    return r.json()["user"]["id"]


def _workspace_id(client, name: str) -> str:
    resp = client.post(WS, json={"name": name})
    assert resp.status_code == 201
    return resp.json()["workspace_id"]


def test_default_active_is_default_space(client) -> None:
    _login(client, "m19-a@example.com")
    active = client.get(f"{WS}/active").json()
    assert active["is_default"] is True
    listed = client.get(WS).json()["workspaces"]
    default = next(ws for ws in listed if ws["is_default"])
    assert active["workspace_id"] == default["workspace_id"]


def test_active_workspace_roundtrip(client) -> None:
    _login(client, "m19-b@example.com")
    wid = _workspace_id(client, "Album")
    assert client.post(f"{WS}/active", json={"workspace_id": wid}).json()["workspace_id"] == wid
    active = client.get(f"{WS}/active").json()
    assert active["workspace_id"] == wid and active["is_default"] is False
    # clear selection -> back to default
    default = client.get(f"{WS}/active").json()["workspace_id"]
    client.post(f"{WS}/active", json={"workspace_id": None})
    assert client.get(f"{WS}/active").json()["is_default"] is True
    assert client.post(f"{WS}/active", json={"workspace_id": "does-not-exist"}).status_code == 404


def test_create_job_rejects_foreign_workspace(client) -> None:
    _login(client, "m19-owner@example.com")
    wid = _workspace_id(client, "Owned")
    client.post("/api/v1/auth/logout")
    # bearer TOKEN_A maps to a different owner (tok_*), so the cookie user's workspace is foreign
    body = submit_body(workspace_id=wid)
    resp = client.post("/api/v1/jobs", json=body, headers=auth(TOKEN_A, **{"Idempotency-Key": "k-foreign"}))
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "WORKSPACE_NOT_FOUND"


def test_generation_stamps_workspace(client, orch) -> None:
    from app.models import Asset, Job

    _login(client, "m19-gen@example.com")
    wid = _workspace_id(client, "Sound")
    client.post(f"{WS}/active", json={"workspace_id": wid})

    resp = client.post("/api/v1/jobs", json=submit_body(workspace_id=wid), headers={"Idempotency-Key": "k-gen"})
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    with orch.db.session() as session:
        job = session.execute(select(Job).where(Job.id == job_id)).scalar_one()
        assert job.request_json["workspace_id"] == wid

    orch.dispatcher.publish_once()
    orch.worker.run_once()

    with orch.db.session() as session:
        assets = list(
            session.execute(select(Asset).where(Asset.job_id == job_id, Asset.deleted_at.is_(None))).scalars()
        )
    assert assets, "fixture worker produced no assets"
    assert all(a.workspace_id == wid for a in assets)

    # the track appears under that workspace via the existing filter
    ids = {t["asset_id"] for t in client.get(f"/api/v1/tracks?workspace_id={wid}").json()["tracks"]}
    assert ids == {a.id for a in assets}
