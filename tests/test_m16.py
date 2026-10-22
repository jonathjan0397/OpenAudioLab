"""M16: Vast registry admin endpoints + internal asset content."""

from __future__ import annotations


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


def _seed_vast(client, cid: str = "12345", state: str = "stopped") -> None:
    from app.models import VastInstance, new_uuid

    with client.app.state.db.session() as session:
        session.add(VastInstance(id=new_uuid(), vast_instance_id=cid, role="training",
                                 gpu_model="RTX 4090", state=state))
        session.commit()


def test_admin_vast_instances_list(client) -> None:
    _seed_admin(client, "m16-vast@example.com")
    _seed_vast(client)
    response = client.get("/api/v1/admin/vast/instances")
    assert response.status_code == 200
    body = response.json()
    match = [i for i in body["instances"] if i["vast_instance_id"] == "12345"]
    assert match and match[0]["state"] == "stopped" and match[0]["role"] == "training"


def test_admin_vast_action_stop_and_destroy(client, monkeypatch) -> None:
    from app.models import VastInstance

    _seed_admin(client, "m16-act@example.com")
    _seed_vast(client, cid="22222")
    calls = []
    monkeypatch.setattr(
        "app.routes.admin._vast_request",
        lambda request, method, path, json_body=None: calls.append((method, path, json_body)) or {"success": True},
    )
    stopped = client.post("/api/v1/admin/vast/instances/22222/action", json={"action": "stop"})
    assert stopped.status_code == 200
    assert calls[0][0] == "PUT" and calls[0][2] == {"state": "shutdown"}
    with client.app.state.db.session() as session:
        rec = session.query(VastInstance).filter_by(vast_instance_id="22222").one()
        assert rec.state == "stopped"

    destroyed = client.post("/api/v1/admin/vast/instances/22222/action", json={"action": "destroy"})
    assert destroyed.status_code == 200
    assert calls[-1][0] == "DELETE" and calls[-1][1] == "/instances/22222/"
    with client.app.state.db.session() as session:
        assert session.query(VastInstance).filter_by(vast_instance_id="22222").one_or_none() is None


def test_admin_vast_action_rejects_unknown(client) -> None:
    _seed_admin(client, "m16-bad@example.com")
    response = client.post("/api/v1/admin/vast/instances/999/action", json={"action": "reboot"})
    assert response.status_code == 422


def test_internal_asset_content(client) -> None:
    from app.models import Asset, new_uuid, utcnow

    key = "owners/usr_test/asset.bin"
    client.app.state.storage.put(key, b"audio-bytes")
    asset_id = new_uuid()
    with client.app.state.db.session() as session:
        session.add(Asset(id=asset_id, owner_id="usr_test", storage_key=key, role="mix_wav",
                          kind="uploaded", mime="audio/wav", bytes=11, sha256="x" * 64,
                          title="t", finalized_at=utcnow()))
        session.commit()
    secret = client.app.state.settings.secret_key
    wrong = client.get(f"/internal/v1/assets/{asset_id}/content?x_oal_secret=nope")
    assert wrong.status_code == 401
    ok = client.get(f"/internal/v1/assets/{asset_id}/content?x_oal_secret={secret}")
    assert ok.status_code == 200
    assert ok.content == b"audio-bytes"
    missing = client.get(f"/internal/v1/assets/does-not-exist/content?x_oal_secret={secret}")
    assert missing.status_code == 404
