"""Admin model pricing: availability, credit multiplier, base cost, popular banner."""

from __future__ import annotations

from app.models import User
from conftest import TOKEN_A, auth


def _login_admin(client, email: str) -> None:
    client.post("/api/v1/auth/logout")
    r = client.post("/api/v1/auth/register",
                    json={"email": email, "username": email.split("@")[0].replace(".", ""),
                          "password": "super-secret-1"})
    assert r.status_code == 201
    with client.app.state.db.session() as session:
        session.get(User, r.json()["user"]["id"]).role = "admin"
        session.commit()


def _quote(client, body=None):
    return client.post("/api/v1/generation/quote",
                       json=body or {"operation": "music.generate", "music_description": "a tune",
                                     "instrumental": True, "duration_seconds": 30, "outputs": ["mix_wav"],
                                     "model_selection": "ace-step-1.5-turbo"},
                       headers=auth(TOKEN_A))


def test_model_pricing_view_defaults(client) -> None:
    _login_admin(client, "mp1@example.com")
    r = client.get("/api/v1/admin/model-pricing")
    assert r.status_code == 200
    data = r.json()
    assert data["base_credit_cost"] == data["base_default"]
    ids = {p["profile_id"] for p in data["profiles"]}
    assert "turbo-fast-v1" in ids


def test_model_pricing_update_persists(client) -> None:
    _login_admin(client, "mp2@example.com")
    r = client.put("/api/v1/admin/model-pricing", json={
        "base_credit_cost": 20,
        "profiles": {"turbo-fast-v1": {"availability": "available", "multiplier": 1.5}},
    })
    assert r.status_code == 200
    view = r.json()
    assert view["base_credit_cost"] == 20
    turbo = next(p for p in view["profiles"] if p["profile_id"] == "turbo-fast-v1")
    assert turbo["multiplier"] == 1.5 and turbo["availability"] == "available"
    assert client.get("/api/v1/admin/model-pricing").json()["base_credit_cost"] == 20


def test_model_pricing_validation(client) -> None:
    _login_admin(client, "mp3@example.com")
    assert client.put("/api/v1/admin/model-pricing", json={"profiles": {"x": {"multiplier": 50}}}).status_code == 422
    assert client.put("/api/v1/admin/model-pricing", json={"profiles": {"x": {"availability": "banana"}}}).status_code == 422
    assert client.put("/api/v1/admin/model-pricing", json={"base_credit_cost": 0}).status_code == 422


def test_quote_uses_effective_pricing(client) -> None:
    _login_admin(client, "mp4@example.com")
    base = client.get("/api/v1/admin/model-pricing").json()["base_default"]
    q = _quote(client)
    assert q.status_code == 200, q.text
    assert q.json()["reserved_credits"] == base
    client.put("/api/v1/admin/model-pricing", json={"base_credit_cost": 20})
    assert _quote(client).json()["reserved_credits"] == 20
    client.put("/api/v1/admin/model-pricing",
               json={"base_credit_cost": 20, "profiles": {"turbo-fast-v1": {"multiplier": 1.5}}})
    assert _quote(client).json()["reserved_credits"] == 30


def test_disabled_model_rejects_quote(client) -> None:
    _login_admin(client, "mp5@example.com")
    client.put("/api/v1/admin/model-pricing",
               json={"profiles": {"turbo-fast-v1": {"availability": "disabled"}}})
    q = _quote(client)
    assert q.status_code == 409 and q.json()["error"]["code"] == "MODEL_DISABLED"


def test_pricing_popular_and_reorder(client) -> None:
    _login_admin(client, "mp6@example.com")
    rows = client.get("/api/v1/admin/pricing").json()
    items = [{**p, "popular": p["id"] == rows["plan"][0]["id"]} for p in rows["plan"]]
    packs = list(reversed(rows["pack"]))
    items += [{**p, "position": i} for i, p in enumerate(packs)]
    r = client.put("/api/v1/admin/pricing", json={"items": items})
    assert r.status_code == 200
    pub = client.get("/api/v1/billing/pricing")
    plans = [p for p in pub.json()["plans"] if p.get("visible", True)]
    packs_pub = [p for p in pub.json()["packs"] if p.get("visible", True)]
    assert plans[0]["popular"] is True
    assert any(p["popular"] for p in plans)
    assert packs_pub[0]["id"] == packs[0]["id"]


def test_model_pricing_nonadmin_denied(client) -> None:
    client.post("/api/v1/auth/logout")
    r = client.post("/api/v1/auth/register",
                    json={"email": "mp7@example.com", "username": "mp7", "password": "super-secret-1"})
    assert r.status_code == 201
    assert client.get("/api/v1/admin/model-pricing").status_code == 403


def test_display_name_override_flows_to_catalog(client) -> None:
    _login_admin(client, "mp8@example.com")
    r = client.put("/api/v1/admin/model-pricing", json={
        "profiles": {"turbo-fast-v1": {"display_name": "Starter Beat"}}})
    assert r.status_code == 200
    turbo = next(p for p in r.json()["profiles"] if p["profile_id"] == "turbo-fast-v1")
    assert turbo["display_name"] == "Starter Beat"
    selections = client.get("/api/v1/model-selections").json()
    release = next(s for s in selections if s["model_selection"] == "ace-step-1.5-turbo")
    assert release["display_name"] == "Starter Beat"  # release-level card name overridden
    assert release["profiles"][0]["display_name"] == "Starter Beat"
    other = next(s for s in selections if s["model_selection"] != "ace-step-1.5-turbo")
    assert other["display_name"] != "Starter Beat"  # untouched models keep catalog names


def test_display_name_validation(client) -> None:
    _login_admin(client, "mp9@example.com")
    assert client.put("/api/v1/admin/model-pricing",
                      json={"profiles": {"x": {"display_name": "   "}}}).status_code == 422
    assert client.put("/api/v1/admin/model-pricing",
                      json={"profiles": {"x": {"display_name": "x" * 121}}}).status_code == 422
