"""M13a: play events, social favorites, mood tags, spotlight + artist stats."""

from __future__ import annotations

import uuid

from app.models import ArtistFollow, ArtistProfile, Asset, utcnow


def _seed_owner(client, email: str, username: str) -> str:
    client.post("/api/v1/auth/logout")
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "username": username, "password": "super-secret-1"},
    )
    return "usr_" + response.json()["user"]["id"]


def _seed_asset(client, owner_id: str, title: str, shared: bool = True, tags: list[str] | None = None) -> str:
    asset_id = str(uuid.uuid4())
    key = f"owners/{owner_id}/jobs/j1/{asset_id}/mix_wav.wav"
    client.app.state.storage.put(key, b"RIFFfake")
    with client.app.state.db.session() as session:
        session.add(
            Asset(
                id=asset_id,
                owner_id=owner_id,
                job_id="j1",
                storage_key=key,
                role="mix_wav",
                mime="audio/wav",
                bytes=8,
                sha256="x",
                synthetic=False,
                title=title,
                shared=shared,
                tags_json=tags or [],
                finalized_at=utcnow(),
                expires_at=utcnow() + __import__("datetime").timedelta(days=7),
            )
        )
        session.commit()
    return asset_id


def test_play_event_and_count(client) -> None:
    from conftest import TOKEN_A, auth

    owner = _seed_owner(client, "m13-play@example.com", "m13play")
    asset_id = _seed_asset(client, owner, "Play Me")

    anon = client.post(f"/api/v1/artifacts/{asset_id}/play")
    assert anon.status_code == 202
    authed = client.post(f"/api/v1/artifacts/{asset_id}/play", headers=auth(TOKEN_A))
    assert authed.status_code == 202

    tracks = client.get("/api/v1/public/tracks").json()["tracks"]
    row = next(t for t in tracks if t["asset_id"] == asset_id)
    assert row["plays"] == 2

    missing = client.post("/api/v1/artifacts/nope/play")
    assert missing.status_code == 404


def test_favorite_shared_asset_of_other_user(client) -> None:
    from conftest import TOKEN_A, TOKEN_B, auth

    owner = _seed_owner(client, "m13-fav@example.com", "m13fav")
    shared = _seed_asset(client, owner, "Community Hit")
    private = _seed_asset(client, owner, "Locked", shared=False)

    fav = client.post(f"/api/v1/artifacts/{shared}/favorite", headers=auth(TOKEN_B))
    assert fav.status_code == 200 and fav.json()["favorite"] is True
    again = client.post(f"/api/v1/artifacts/{shared}/favorite", headers=auth(TOKEN_B))
    assert again.json()["favorite"] is False

    denied = client.post(f"/api/v1/artifacts/{private}/favorite", headers=auth(TOKEN_A))
    assert denied.status_code == 404

    tracks = client.get("/api/v1/public/tracks", headers=auth(TOKEN_B)).json()["tracks"]
    row = next(t for t in tracks if t["asset_id"] == shared)
    assert row["like_count"] == 0  # toggled off above
    client.post(f"/api/v1/artifacts/{shared}/favorite", headers=auth(TOKEN_B))
    row = next(t for t in client.get("/api/v1/public/tracks", headers=auth(TOKEN_B)).json()["tracks"] if t["asset_id"] == shared)
    assert row["favorite"] is True


def test_tag_filter(client) -> None:
    owner = _seed_owner(client, "m13-tag@example.com", "m13tag")
    hopeful = _seed_asset(client, owner, "Sunrise Run", tags=["hopeful"])
    dark = _seed_asset(client, owner, "Midnight Drive", tags=["dark"])

    rows = client.get("/api/v1/public/tracks?tag=hopeful").json()["tracks"]
    assert [t["asset_id"] for t in rows] == [hopeful]
    rows = client.get("/api/v1/public/tracks?tag=dark").json()["tracks"]
    assert [t["asset_id"] for t in rows] == [dark]
    rows = client.get("/api/v1/public/tracks?tag=jazz").json()["tracks"]
    assert rows == []


def test_spotlight_and_stats(client) -> None:
    owner = _seed_owner(client, "m13-spot@example.com", "m13spot")
    asset_id = _seed_asset(client, owner, "Spotlight Hit")
    client.post(f"/api/v1/artifacts/{asset_id}/play")
    with client.app.state.db.session() as session:
        profile = ArtistProfile(owner_id=owner, name="Nova Wells", slug="nova-wells", sharing_policy="public")
        session.add(profile)
        session.commit()
        profile_id = profile.id
        session.add(ArtistFollow(owner_id="tok_someone", profile_id=profile_id))
        session.commit()

    spot = client.get("/api/v1/public/spotlight").json()["artist"]
    assert spot["name"] == "Nova Wells"
    assert spot["followers"] == 1
    assert spot["tracks"] == 1
    assert spot["plays"] == 1

    stats = client.get("/api/v1/public/artists/nova-wells/stats").json()
    assert stats["tracks"] == 1 and stats["followers"] == 1 and stats["plays"] == 1


def test_billing_plans_flow(client) -> None:
    _seed_owner(client, "m13-bill@example.com", "m13bill")

    plans = client.get("/api/v1/billing/plans")
    assert plans.status_code == 200
    body = plans.json()
    assert [p["id"] for p in body["plans"]] == ["free", "pro", "premier"]
    assert body["current"] == "free"
    start = body["credits_balance"]

    sub = client.post("/api/v1/billing/subscribe", json={"plan": "pro"})
    assert sub.status_code == 200
    assert sub.json()["plan"] == "pro"
    assert sub.json()["credits_balance"] == start + 2500

    top = client.post("/api/v1/billing/topup")
    assert top.json()["credits_balance"] == start + 2500 + 500

    unsub = client.post("/api/v1/billing/unsubscribe")
    assert unsub.json()["plan"] == "free"

    bad = client.post("/api/v1/billing/subscribe", json={"plan": "gold"})
    assert bad.status_code == 422


def test_billing_mock_endpoints_disabled_in_production(client) -> None:
    _seed_owner(client, "m13-bill-prod@example.com", "m13billprod")
    settings = client.app.state.settings
    old_mode = settings.billing_mode
    settings.billing_mode = "production"
    try:
        assert client.post("/api/v1/billing/subscribe", json={"plan": "pro"}).status_code == 409
        assert client.post("/api/v1/billing/topup").status_code == 409
    finally:
        settings.billing_mode = old_mode


def test_admin_revenue_counts_plans(client) -> None:
    from app.models import User

    owner = _seed_owner(client, "m13-rev@example.com", "m13rev")
    client.post("/api/v1/billing/subscribe", json={"plan": "premier"})
    with client.app.state.db.session() as session:
        session.get(User, owner[4:]).role = "admin"
        session.commit()
    billing = client.get("/api/v1/admin/billing").json()
    assert billing["revenue"] >= 24
    assert billing["subscribers"] >= 1


def test_stems_listing(client) -> None:
    owner = _seed_owner(client, "m13-stems@example.com", "m13stems")
    asset_id = _seed_asset(client, owner, "Stem Source")
    response = client.get(f"/api/v1/artifacts/{asset_id}/stems")
    assert response.status_code == 200
    assert response.json()["stems"] == []
    assert client.get("/api/v1/artifacts/nonexistent/stems").status_code == 404
