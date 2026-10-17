"""M14c: styles endpoints, LLM draft, auto-LoRA matching, variations cost."""

from __future__ import annotations

from sqlalchemy import select

from conftest import submit


def _seed_owner(client, email: str, username: str) -> str:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "username": username, "password": "pass-1234"},
    )
    assert response.status_code == 201
    return response.json()["user"]["id"]


def test_styles_endpoints(client) -> None:
    response = client.get("/api/v1/styles/cheatsheet")
    assert response.status_code == 200
    body = response.json()
    names = [c["name"] for c in body["categories"]]
    assert "Genres" in names and "Vocals" in names

    first = client.get("/api/v1/styles/suggest?limit=4&seed=7").json()["tags"]
    second = client.get("/api/v1/styles/suggest?limit=4&seed=7").json()["tags"]
    assert len(first) == 4
    assert first == second  # deterministic per seed
    assert all("tag" in t and "source" in t for t in first)


def test_llm_draft(client) -> None:
    _seed_owner(client, "m14-draft@example.com", "m14draft")

    class FakeLlm:
        def chat(self, system, user, max_tokens=400, temperature=0.8):
            self.last_user = user
            return '{"lyrics": "[Verse]\\nfake line", "style": "lofi, chill, female vocals"}'

    client.app.state.llm = FakeLlm()
    response = client.post(
        "/api/v1/llm/draft",
        json={"prompt": "rainy study session", "lora_tags": ["lofi", "rainy"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["lyrics"].startswith("[Verse]")
    assert body["style"] == "lofi, chill, female vocals"
    assert "rainy study session" in client.app.state.llm.last_user
    assert "lofi, rainy" in client.app.state.llm.last_user  # vocabulary seeded
    client.app.state.llm = None


def test_auto_lora_match(client) -> None:
    from app.models import Lora

    _seed_owner(client, "m14-auto@example.com", "m14auto")
    with client.app.state.db.session() as session:
        lora = Lora(id="lora-m14-a", name="Rainy LoFi", tags_json=["lofi", "rainy"], storage_prefix="p", files_json=["x"])
        session.add(lora)
        session.commit()

    response = submit(client, key="m14-auto-1", music_description="lofi beats for a rainy night", controls={"mood": "chill"})
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    with client.app.state.db.session() as session:
        from app.models import Job

        job = session.execute(select(Job).where(Job.id == job_id)).scalar_one()
        assert job.request_json["lora_id"] == "lora-m14-a"
        assert job.request_json["lora_match"]["mode"] == "auto"
        assert "lofi" in job.request_json["lora_match"]["tags"]

    # Explicit selection wins over auto-match.
    response = submit(client, key="m14-auto-2", music_description="lofi beats", lora_id="lora-m14-a")
    with client.app.state.db.session() as session:
        from app.models import Job

        job = session.execute(select(Job).where(Job.id == response.json()["job_id"])).scalar_one()
        assert "lora_match" not in job.request_json

    # auto_apply=False excludes the LoRA.
    with client.app.state.db.session() as session:
        session.get(Lora, "lora-m14-a").auto_apply = False
        session.commit()
    response = submit(client, key="m14-auto-3", music_description="lofi beats")
    with client.app.state.db.session() as session:
        from app.models import Job

        job = session.execute(select(Job).where(Job.id == response.json()["job_id"])).scalar_one()
        assert job.request_json.get("lora_id") is None


def test_variations_cost(client) -> None:
    from app.models import User

    owner = _seed_owner(client, "m14-var@example.com", "m14var")
    response = client.post(
        "/api/v1/jobs",
        json={
            "operation": "music.generate",
            "model_id": "ace-step-1.5",
            "music_description": "indie pop",
            "lyrics": "[Verse]\ntest",
            "lyrics_origin": "frontend_llm",
            "instrumental": False,
            "outputs": ["mix_wav"],
            "controls": {"variations": 2},
        },
        headers={"Idempotency-Key": "m14-var-1"},
    )
    assert response.status_code == 202
    with client.app.state.db.session() as session:
        from app.models import CreditEntry

        entry = session.execute(
            select(CreditEntry).where(CreditEntry.job_id == response.json()["job_id"])
        ).scalar_one()
        spent = -entry.delta
        from app.config import Settings

        assert spent == 2 * Settings().credit_cost_per_generation


def test_stripe_checkout_disabled(client) -> None:
    _seed_owner(client, "m14-stripe@example.com", "m14stripe")
    response = client.post("/api/v1/billing/checkout", json={"kind": "pack", "pack": "small"})
    assert response.status_code == 503  # no stripe key in test env
    response = client.post("/api/v1/billing/checkout", json={"kind": "plan"})
    assert response.status_code == 422


def test_admin_credit_adjust_and_ledger(client) -> None:
    owner = _seed_owner(client, "m14-ledger@example.com", "m14ledger")
    # promote to admin for the admin routes
    from app.models import User

    with client.app.state.db.session() as session:
        session.get(User, owner).role = "admin"
        session.commit()
    response = client.post(f"/api/v1/admin/users/{owner}/credits", json={"delta": 250, "note": "goodwill"})
    assert response.status_code == 200
    assert response.json()["credits_balance"] == 1250
    response = client.post(f"/api/v1/admin/users/{owner}/credits", json={"delta": -500, "note": "correction"})
    assert response.json()["credits_balance"] == 750
    ledger = client.get(f"/api/v1/admin/users/{owner}/credits").json()["entries"]
    assert ledger[0]["delta"] == -500 and ledger[0]["note"] == "correction"
    assert ledger[1]["delta"] == 250


def test_billing_webhook_signature(client) -> None:
    response = client.post("/api/v1/billing/webhook", content=b"{}", headers={"content-type": "application/json"})
    assert response.status_code == 503  # no webhook secret configured in tests
