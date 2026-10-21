"""M18: admin media catalog — cross-owner browse/listen + moderation + purge."""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from app.models import Asset, Job, User, new_uuid, utcnow


def _login(client: TestClient, email: str, *, admin: bool = False) -> str:
    client.post("/api/v1/auth/logout")
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "username": email.split("@")[0].replace(".", ""), "password": "super-secret-1"},
    )
    uid = response.json()["user"]["id"]
    if admin:
        with client.app.state.db.session() as session:
            user = session.get(User, uid)
            user.role = "admin"
            session.commit()
    return uid


def _put_asset(client: TestClient, owner_id: str, *, role="mix_wav", title=None, state="live", job_id=None):
    """Insert an Asset row (and its bytes) directly; returns (asset_id, storage_key)."""
    storage = client.app.state.storage
    now = utcnow()
    asset_id = new_uuid()
    storage_key = f"owners/{owner_id}/jobs/{job_id or 'manual'}/{asset_id}/{role}.wav"
    body = b"RIFFfake-wav-bytes-for-admin-catalog-tests"
    storage.put(storage_key, body)
    fields = dict(
        id=asset_id,
        job_id=job_id or "job-" + new_uuid()[:8],
        owner_id=owner_id,
        storage_key=storage_key,
        role=role,
        kind="generated",
        mime="audio/wav",
        bytes=len(body),
        sha256="x" * 64,
        duration_seconds=12.5,
        title=title,
        created_at=now,
        expires_at=now + timedelta(days=7),
    )
    if state == "expired":
        fields["expires_at"] = now - timedelta(hours=1)
    elif state == "trashed":
        fields["deleted_at"] = now
        fields["purge_after"] = now + timedelta(hours=48)
    elif state == "purged":
        fields["deleted_at"] = now
        fields["purged_at"] = now
        storage.delete(storage_key)
    elif state == "shared":
        fields["shared"] = True
    with client.app.state.db.session() as session:
        session.add(Asset(**fields))
        session.commit()
    return fields["id"], storage_key


def test_assets_listing_requires_admin(client) -> None:
    _login(client, "m18-plain@example.com")
    assert client.get("/api/v1/admin/assets").status_code == 403
    client.post("/api/v1/auth/logout")
    assert client.get("/api/v1/admin/assets").status_code == 401


def test_assets_lists_all_owners_and_states(client) -> None:
    alice = "usr_" + _login(client, "m18-alice@example.com")
    _login(client, "m18-admin2@example.com", admin=True)  # re-login as admin (cookie is per-client)
    live_id, _ = _put_asset(client, alice, title="Live Song")
    exp_id, _ = _put_asset(client, alice, title="Old Song", state="expired")
    trash_id, _ = _put_asset(client, alice, title="Trashed Song", state="trashed")
    purged_id, _ = _put_asset(client, alice, title="Gone Song", state="purged")

    body = client.get("/api/v1/admin/assets?user_id=" + alice[4:] + "&limit=200").json()
    by_id = {row["asset_id"]: row for row in body["items"]}
    assert {live_id, exp_id, trash_id, purged_id} <= set(by_id)
    assert by_id[live_id]["state"] == "live"
    assert by_id[exp_id]["state"] == "expired"
    assert by_id[trash_id]["state"] == "trashed"
    assert by_id[purged_id]["state"] == "purged"
    assert by_id[live_id]["user"] == "m18-alice"
    # expired/trashed remain playable bytes; purged does not
    assert by_id[exp_id]["playable"] and by_id[trash_id]["playable"]
    assert not by_id[purged_id]["playable"] and not by_id[purged_id]["byte_present"]

    # status filter narrows to trashed only
    only_trash = client.get("/api/v1/admin/assets?user_id=" + alice[4:] + "&status=trashed").json()
    assert {r["asset_id"] for r in only_trash["items"]} == {trash_id}


def test_admin_content_streams_expired_and_trashed(client) -> None:
    owner = "usr_" + _login(client, "m18-ownerx@example.com")
    _login(client, "m18-adminx2@example.com", admin=True)
    exp_id, key = _put_asset(client, owner, state="expired")
    trash_id, _ = _put_asset(client, owner, state="trashed")
    purged_id, _ = _put_asset(client, owner, state="purged")

    # expired asset: the ordinary owner path would 410, admin streams 200 with real bytes
    r = client.get(f"/api/v1/admin/artifacts/{exp_id}/content")
    assert r.status_code == 200
    assert r.headers["accept-ranges"] == "bytes"
    assert r.content.startswith(b"RIFF")

    # Range request returns 206 with Content-Range
    rr = client.get(f"/api/v1/admin/artifacts/{trash_id}/content", headers={"Range": "bytes=0-3"})
    assert rr.status_code == 206
    assert rr.headers["content-range"].startswith("bytes 0-3/")
    assert rr.content == b"RIFF"

    # download sets a friendly Content-Disposition
    dl = client.get(f"/api/v1/admin/artifacts/{exp_id}/content?download=1")
    assert "attachment" in dl.headers["content-disposition"]
    assert ".wav" in dl.headers["content-disposition"]

    # purged: bytes gone -> 410
    assert client.get(f"/api/v1/admin/artifacts/{purged_id}/content").status_code == 410


def test_admin_unshare_trash_restore(client) -> None:
    _login(client, "m18-mod@example.com", admin=True)
    owner = "usr_" + _login(client, "m18-owner-mod@example.com")
    _login(client, "m18-mod2@example.com", admin=True)
    shared_id, key = _put_asset(client, owner, title="Shared", state="shared")

    assert client.patch(f"/api/v1/admin/assets/{shared_id}", json={"shared": False}).status_code == 200
    with client.app.state.db.session() as session:
        assert session.get(Asset, shared_id).shared is False

    # move to trash sets deleted_at + 48h purge window, bytes still present
    client.patch(f"/api/v1/admin/assets/{shared_id}", json={"trash": True})
    with client.app.state.db.session() as session:
        asset = session.get(Asset, shared_id)
        assert asset.deleted_at is not None
        assert (asset.purge_after - asset.deleted_at) == timedelta(hours=48)
    assert client.get(f"/api/v1/admin/artifacts/{shared_id}/content").status_code == 200

    # restore
    client.patch(f"/api/v1/admin/assets/{shared_id}", json={"trash": False})
    with client.app.state.db.session() as session:
        assert session.get(Asset, shared_id).deleted_at is None
        assert session.get(Asset, shared_id).purge_after is None

    from app.models import AdminAudit

    with client.app.state.db.session() as session:
        audits = list(session.query(AdminAudit).all())
    assert any(a.action == "asset.patch" for a in audits)


def test_admin_purge_single_and_content(client) -> None:
    _login(client, "m18-purge@example.com", admin=True)
    owner = "usr_" + _login(client, "m18-powner@example.com")
    _login(client, "m18-purge2@example.com", admin=True)
    a1, k1 = _put_asset(client, owner, title="One")
    a2, k2 = _put_asset(client, owner, title="Two", role="mix_mp3")

    r = client.post(f"/api/v1/admin/assets/{a1}/purge")
    assert r.status_code == 200 and r.json()["purged"] is True
    assert not client.app.state.storage.exists(k1)
    with client.app.state.db.session() as session:
        assert session.get(Asset, a1).purged_at is not None  # metadata row kept

    # purge the whole user's remaining content
    owner_id = owner
    uid = owner[4:]
    r2 = client.post(f"/api/v1/admin/users/{uid}/purge-content")
    assert r2.json()["assets_purged"] == 1  # only a2 left unpurged
    assert not client.app.state.storage.exists(k2)
    # already-purged asset stays purged (idempotent listing)
    assert client.post(f"/api/v1/admin/assets/{a1}/purge").json()["already_purged"] is True


def test_admin_user_detail(client) -> None:
    _login(client, "m18-detail@example.com", admin=True)
    target = _login(client, "m18-target@example.com")
    _login(client, "m18-detail2@example.com", admin=True)
    _put_asset(client, "usr_" + target, title="T1")
    _put_asset(client, "usr_" + target, title="T2", state="trashed")
    _put_asset(client, "usr_" + target, title="T3", state="purged")

    body = client.get(f"/api/v1/admin/users/{target}").json()
    counts = body["counts"]
    assert counts["assets_total"] == 3
    assert counts["assets_trashed"] == 1
    assert counts["assets_purged"] == 1
    assert len(body["recent_assets"]) == 3
    assert client.get(f"/api/v1/admin/users/{target}/assets?status=trashed").json()["total"] == 1


def test_expire_once_purges_trash_window(client, monkeypatch) -> None:
    from app.maintenance import expire_once

    owner = "usr_" + _login(client, "m18-expowner@example.com")
    trashed_id, key = _put_asset(client, owner, title="Doomed", state="trashed")
    with client.app.state.db.session() as session:
        asset = session.get(Asset, trashed_id)
        asset.purge_after = utcnow() - timedelta(minutes=1)
        session.commit()

    assert expire_once(client.app.state.db, client.app.state.storage) >= 1
    assert not client.app.state.storage.exists(key)
    with client.app.state.db.session() as session:
        asset = session.get(Asset, trashed_id)
        assert asset.purged_at is not None
        assert asset.deleted_at is not None


def test_user_delete_opens_48h_trash_window(client) -> None:
    uid = _login(client, "m18-userdel@example.com")
    owner = "usr_" + uid
    asset_id, _key = _put_asset(client, owner, title="Delete Me")

    assert client.delete(f"/api/v1/assets/{asset_id}").status_code == 204
    with client.app.state.db.session() as session:
        asset = session.get(Asset, asset_id)
        assert asset.deleted_at is not None
        assert asset.purged_at is None
        assert (asset.purge_after - asset.deleted_at) == timedelta(hours=48)
    # immediately hidden from the owner's own library
    ids = {t["asset_id"] for t in client.get("/api/v1/tracks").json()["tracks"]}
    assert asset_id not in ids

