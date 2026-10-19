"""M14c: styles endpoints, LLM draft, auto-LoRA matching, variations cost."""

from __future__ import annotations

from sqlalchemy import select

from app.worker import generate_fixture_wav
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
            return '{"lyrics": "[Verse]\\nfake line", "style": "lofi, chill", "title": "Rainy Page"}'

    client.app.state.llm = FakeLlm()
    response = client.post(
        "/api/v1/llm/draft",
        json={"prompt": "rainy study session", "lora_tags": ["lofi", "rainy"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["lyrics"].startswith("[Verse]")
    assert body["style"] == "lofi, chill"
    assert body["title"] == "Rainy Page"
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


def test_billing_webhook_records_event_idempotently(client, monkeypatch) -> None:
    import json

    import stripe
    from sqlalchemy import select

    from app.models import BillingEvent, CreditEntry, User

    owner = _seed_owner(client, "m14-webhook@example.com", "m14webhook")
    settings = client.app.state.settings
    old_secret = settings.stripe_webhook_secret
    settings.stripe_webhook_secret = "whsec_test"
    monkeypatch.setattr(stripe.Webhook, "construct_event", lambda body, sig, secret: json.loads(body))
    payload = {
        "id": "evt_pack",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test",
                "client_reference_id": owner,
                "metadata": {"kind": "pack", "pack": "small", "credits": "1000"},
                "amount_total": 500,
                "payment_intent": "pi_test",
            }
        },
    }
    body = json.dumps(payload).encode()
    headers = {"content-type": "application/json"}
    try:
        first = client.post("/api/v1/billing/webhook", content=body, headers=headers)
        assert first.status_code == 200
        assert first.json() == {"received": True, "duplicate": False}
        second = client.post("/api/v1/billing/webhook", content=body, headers=headers)
        assert second.json() == {"received": True, "duplicate": True}
        with client.app.state.db.session() as session:
            events = list(session.execute(select(BillingEvent)).scalars())
            credits = list(session.execute(select(CreditEntry).where(CreditEntry.owner_id == f"usr_{owner}")).scalars())
            user = session.get(User, owner)
        assert len(events) == 1
        assert events[0].status == "credited"
        assert events[0].amount_usd == 500
        assert credits[0].delta == 1000
        assert user.credits_balance == 2000
    finally:
        settings.stripe_webhook_secret = old_secret


def _seed_admin(client, email: str, username: str) -> str:
    from app.models import User

    owner = _seed_owner(client, email, username)
    with client.app.state.db.session() as session:
        session.get(User, owner).role = "admin"
        session.commit()
    return owner


def test_admin_lora_pipeline(client) -> None:
    from app.models import ArtistProfileVersion, Job
    from sqlalchemy import select as _select

    owner = _seed_admin(client, "m14-lora@example.com", "m14lora")
    wav = generate_fixture_wav("lora1", 5, 2)
    files = [
        ("files", ("01 - Midnight Drive.wav", wav, "audio/wav")),
        ("files", ("Sunrise Avenue [official].wav", wav, "audio/wav")),
    ]
    response = client.post(
        "/api/v1/admin/loras/upload",
        data={"name": "Test Artist", "tags": "lofi, rainy"},
        files=files,
    )
    assert response.status_code == 202
    body = response.json()
    assert body["titles"] == ["Midnight Drive", "Sunrise Avenue"]
    with client.app.state.db.session() as session:
        job = session.execute(_select(Job).where(Job.id == body["job_id"])).scalar_one()
        assert job.operation == "artist.train"

    assert client.get("/api/v1/admin/loras").json()["loras"] == []

    with client.app.state.db.session() as session:
        version = ArtistProfileVersion(
            profile_id="p1", owner_id="usr_" + owner, mechanism="fine_tuned_adapter",
            base_model_id="ace-step-1.5", base_revision="r", recipe_revision="rec",
            artifacts_json={"adapter_object_prefix": "owners/x/adapters/v1", "adapter_files": ["a.safetensors"]},
            state="candidate",
        )
        session.add(version)
        session.commit()
        version_id = version.id
    response = client.post(
        "/api/v1/admin/loras",
        json={"profile_version_id": version_id, "name": "Test Artist Style", "tags": "lofi, midnight drive"},
    )
    assert response.status_code == 201
    lora_id = response.json()["id"]

    rows = client.get("/api/v1/admin/loras").json()["loras"]
    assert rows[0]["name"] == "Test Artist Style" and rows[0]["auto_apply"] is True

    response = client.patch(f"/api/v1/admin/loras/{lora_id}", json={"auto_apply": False, "state": "retired"})
    assert response.status_code == 200 and response.json()["state"] == "retired"
    assert client.delete(f"/api/v1/admin/loras/{lora_id}").status_code == 204


def test_upload_path_body_limit_exempt(client) -> None:
    """The 1 MB JSON cap must not apply to /upload paths (admin LoRA uploads)."""
    response = client.post(
        "/api/v1/admin/loras/upload",
        data={"blob": "x" * 1_500_000},
        files=[("files", ("song.wav", b"wav-bytes", "audio/wav"))],
    )
    assert response.status_code != 413


def test_title_asset_naming(client, orch) -> None:
    """A submitted title names the resulting assets; takes get numbered suffixes."""
    from app.models import Asset

    _seed_owner(client, "m14-title@example.com", "m14title")
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
            "title": "Moonlit Road",
        },
        headers={"Idempotency-Key": "m14-title-1"},
    )
    assert response.status_code == 202
    orch.dispatcher.publish_once()
    orch.worker.run_once()
    with client.app.state.db.session() as session:
        titles = [
            a.title
            for a in session.execute(
                select(Asset).where(Asset.job_id == response.json()["job_id"])
            ).scalars()
        ]
    assert titles == ["Moonlit Road"]
