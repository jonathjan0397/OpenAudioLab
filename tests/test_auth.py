from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _clear_cookies(client: TestClient):
    client.cookies.clear()
    yield
    client.cookies.clear()


def _register(client: TestClient, email: str = "jona@example.com", username: str = "jona") -> dict:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "username": username, "password": "super-secret-1"},
    )
    assert response.status_code == 201
    return response.json()["user"]


def test_register_login_me_logout(client) -> None:
    user = _register(client)
    assert user["role"] == "user"
    assert user["credits_balance"] == 1000

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "jona@example.com"

    client.post("/api/v1/auth/logout")
    assert client.get("/api/v1/auth/me").status_code == 401

    login = client.post(
        "/api/v1/auth/login", json={"email": "jona@example.com", "password": "super-secret-1"}
    )
    assert login.status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 200


def test_register_duplicate_email(client) -> None:
    _register(client)
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "other@example.com", "username": "other", "password": "super-secret-1"},
    )
    assert response.status_code == 200 or response.status_code == 201
    dup = client.post(
        "/api/v1/auth/register",
        json={"email": "jona@example.com", "username": "third", "password": "super-secret-1"},
    )
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "EMAIL_TAKEN"


def test_login_wrong_password(client) -> None:
    _register(client)
    client.post("/api/v1/auth/logout")
    response = client.post(
        "/api/v1/auth/login", json={"email": "jona@example.com", "password": "wrong-password"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_me_requires_cookie(client) -> None:
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_admin_requires_admin_role(client) -> None:
    _register(client)
    response = client.get("/api/v1/admin/users")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ADMIN_REQUIRED"


def _seed_admin(client) -> None:
    from app.auth import hash_password
    from app.main import create_app
    from app.models import User

    with client.app.state.db.session() as session:
        session.add(
            User(
                email="root@example.com",
                username="root",
                password_hash=hash_password("root-password-1"),
                role="admin",
            )
        )
        session.commit()


def test_admin_user_management(client) -> None:
    _seed_admin(client)
    login = client.post(
        "/api/v1/auth/login", json={"email": "root@example.com", "password": "root-password-1"}
    )
    assert login.status_code == 200

    listing = client.get("/api/v1/admin/users")
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    admin_id = listing.json()["users"][0]["id"]

    created = client.post(
        "/api/v1/admin/users",
        json={"email": "new@example.com", "username": "newuser", "password": "password-123"},
    )
    assert created.status_code == 201
    new_id = created.json()["user"]["id"]

    patched = client.patch(f"/api/v1/admin/users/{new_id}", json={"state": "disabled"})
    assert patched.json()["user"]["state"] == "disabled"

    patched = client.patch(f"/api/v1/admin/users/{admin_id}", json={"role": "user"})
    assert patched.json()["user"]["role"] == "user"


def test_disabled_user_cannot_use_session(client) -> None:
    user = _register(client)
    with client.app.state.db.session() as session:
        from app.models import User

        row = session.get(User, user["id"])
        row.state = "disabled"
        session.commit()
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "USER_DISABLED"


def test_template_setting_roundtrip(client) -> None:
    _seed_admin(client)
    client.post(
        "/api/v1/auth/login", json={"email": "root@example.com", "password": "root-password-1"}
    )
    put = client.put("/api/v1/admin/settings/template", json={"value": "analog-soul"})
    assert put.status_code == 200
    settings = client.get("/api/v1/admin/settings")
    assert settings.json()["settings"]["template"] == "analog-soul"
    bad = client.put("/api/v1/admin/settings/template", json={"value": "vaporwave"})
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "TEMPLATE_UNKNOWN"
