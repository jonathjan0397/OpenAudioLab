"""M17: workspaces, seed assignment, DB pricing, error logs, artist extras."""

from __future__ import annotations

from conftest import TOKEN_A, auth, submit


def _seed_admin(client, email: str) -> None:
    from app.models import User

    client.post("/api/v1/auth/logout")
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "username": email.split("@")[0].replace(".", "-"), "password": "super-secret-1"},
    )
    uid = response.json()["user"]["id"]
    with client.app.state.db.session() as session:
        user = session.get(User, uid)
        user.role = "admin"
        session.commit()


def test_generate_job_gets_seed(client) -> None:
    response = submit(client, key="seed-1")
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    detail = client.get(f"/api/v1/jobs/{job_id}", headers=auth(TOKEN_A)).json()
    assert isinstance(detail["seed"], int) and detail["seed"] >= 1


def test_explicit_seed_is_preserved(client) -> None:
    response = submit(client, key="seed-2", seed=777)
    job_id = response.json()["job_id"]
    detail = client.get(f"/api/v1/jobs/{job_id}", headers=auth(TOKEN_A)).json()
    assert detail["seed"] == 777


def test_workspace_crud(client) -> None:
    created = client.post("/api/v1/workspaces", json={"name": "Album drafts"}, headers=auth(TOKEN_A))
    assert created.status_code == 201
    ws_id = created.json()["workspace_id"]

    listed = client.get("/api/v1/workspaces", headers=auth(TOKEN_A)).json()["workspaces"]
    assert [w["workspace_id"] for w in listed] == [ws_id]

    renamed = client.patch(f"/api/v1/workspaces/{ws_id}", json={"name": "EP drafts"}, headers=auth(TOKEN_A))
    assert renamed.json()["name"] == "EP drafts"

    deleted = client.delete(f"/api/v1/workspaces/{ws_id}", headers=auth(TOKEN_A))
    assert deleted.status_code == 204
    assert client.get("/api/v1/workspaces", headers=auth(TOKEN_A)).json()["workspaces"] == []


def test_workspace_save_from_job(client) -> None:
    client.post("/api/v1/workspaces", json={"name": "Saves"}, headers=auth(TOKEN_A))
    ws_id = client.get("/api/v1/workspaces", headers=auth(TOKEN_A)).json()["workspaces"][0]["workspace_id"]
    job_id = submit(client, key="ws-job-1", seed=5).json()["job_id"]

    added = client.post(
        f"/api/v1/workspaces/{ws_id}/songs",
        json={"job_id": job_id, "title": "Draft one"},
        headers=auth(TOKEN_A),
    )
    assert added.status_code == 201
    song = added.json()
    assert song["seed"] == 5
    assert song["title"] == "Draft one"

    songs = client.get(f"/api/v1/workspaces/{ws_id}/songs", headers=auth(TOKEN_A)).json()["songs"]
    assert len(songs) == 1

    removed = client.delete(f"/api/v1/workspaces/{ws_id}/songs/{song['song_id']}", headers=auth(TOKEN_A))
    assert removed.status_code == 204


def test_workspace_isolation(client) -> None:
    ws_id = client.post("/api/v1/workspaces", json={"name": "Mine"}, headers=auth(TOKEN_A)).json()["workspace_id"]
    other = client.get(f"/api/v1/workspaces/{ws_id}", headers=auth("Bearer user-b-secret-token"))
    assert other.status_code == 404


def test_admin_pricing_seed_and_update(client) -> None:
    _seed_admin(client, "price-admin@example.com")

    pricing = client.get("/api/v1/admin/pricing").json()
    assert {p["id"] for p in pricing["plan"]} == {"free", "beginner", "pro", "premier"}
    assert {p["id"] for p in pricing["pack"]} == {"small", "medium", "large"}

    items = pricing["plan"] + pricing["pack"]
    for item in items:
        if item["id"] == "pro":
            item["price_usd"] = 9
    updated = client.put("/api/v1/admin/pricing", json={"items": items}).json()
    pro = next(p for p in updated["plan"] if p["id"] == "pro")
    assert pro["price_usd"] == 9

    plans = client.get("/api/v1/billing/plans", headers=auth(TOKEN_A)).json()["plans"]
    assert next(p for p in plans if p["id"] == "pro")["price_usd"] == 9


def test_admin_errors_list_and_resolve(client) -> None:
    _seed_admin(client, "err-admin@example.com")

    listed = client.get("/api/v1/admin/errors").json()
    baseline = listed["total"]

    from app.errorlog import record_error

    record_error(
        client.app.state.db,
        component="test",
        error_code="BOOM",
        message="something broke",
        route="GET /x",
        http_status=500,
    )
    listed = client.get("/api/v1/admin/errors").json()
    assert listed["total"] == baseline + 1
    eid = listed["items"][0]["id"]

    detail = client.get(f"/api/v1/admin/errors/{eid}").json()
    assert detail["error_code"] == "BOOM"
    assert "BOOM — test" in detail["agent_brief"]

    patched = client.patch(f"/api/v1/admin/errors/{eid}", json={"resolved": True})
    assert patched.json()["resolved"] is True


def test_admin_user_soft_delete(client) -> None:
    _seed_admin(client, "del-admin@example.com")

    created = client.post(
        "/api/v1/admin/users",
        json={"email": "victim@example.com", "username": "victim", "password": "super-secret-1"},
    )
    victim_id = created.json()["user"]["id"]
    deleted = client.delete(f"/api/v1/admin/users/{victim_id}")
    assert deleted.status_code == 204
    users = client.get("/api/v1/admin/users").json()["users"]
    assert victim_id not in [u["id"] for u in users]


def test_public_artist_only_shows_shared_curated_songs(client) -> None:
    import hashlib
    import uuid

    from app.models import Asset, utcnow
    from conftest import TOKEN_A, auth

    owner = "tok_" + hashlib.sha256(TOKEN_A[7:].encode("utf-8")).hexdigest()[:32]

    def seed_asset(title: str, shared: bool) -> str:
        asset_id = str(uuid.uuid4())
        key = f"owners/{owner}/jobs/j1/{asset_id}/mix_wav.wav"
        client.app.state.storage.put(key, b"RIFFfake")
        with client.app.state.db.session() as session:
            session.add(
                Asset(
                    id=asset_id,
                    owner_id=owner,
                    job_id="j1",
                    storage_key=key,
                    role="mix_wav",
                    mime="audio/wav",
                    bytes=8,
                    sha256="x",
                    synthetic=False,
                    title=title,
                    shared=shared,
                    tags_json=[],
                    finalized_at=utcnow(),
                    expires_at=utcnow() + __import__("datetime").timedelta(days=7),
                )
            )
            session.commit()
        return asset_id

    created = client.post("/api/v1/artist-profiles", json={"name": "Privacy Artist"}, headers=auth(TOKEN_A))
    assert created.status_code == 201
    pid = created.json()["profile_id"]
    patched = client.patch(
        f"/api/v1/artist-profiles/{pid}",
        json={"sharing": "public"},
        headers=auth(TOKEN_A, **{"If-Match": created.json()["etag"]}),
    )
    assert patched.status_code == 200

    shared = seed_asset("Public Curated", True)
    private = seed_asset("Private Curated", False)
    seed_asset("Unshared Uncurated", False)

    for asset_id in (shared, private):
        added = client.post(
            f"/api/v1/artist-profiles/{pid}/songs",
            json={"asset_id": asset_id},
            headers=auth(TOKEN_A),
        )
        assert added.status_code == 201

    body = client.get("/api/v1/public/artists/privacy-artist").json()
    assert [t["asset_id"] for t in body["tracks"]] == [shared]


def test_artist_bio_and_songs(client) -> None:
    created = client.post("/api/v1/artist-profiles", json={"name": "Curator", "bio": "Hello world"}, headers=auth(TOKEN_A))
    assert created.status_code == 201
    body = created.json()
    assert body["bio"] == "Hello world"
    pid = body["profile_id"]

    patched = client.patch(
        f"/api/v1/artist-profiles/{pid}",
        json={"bio": "Updated bio"},
        headers=auth(TOKEN_A, **{"If-Match": body["etag"]}),
    )
    assert patched.json()["bio"] == "Updated bio"

    songs = client.get(f"/api/v1/artist-profiles/{pid}/songs", headers=auth(TOKEN_A)).json()
    assert songs == []
