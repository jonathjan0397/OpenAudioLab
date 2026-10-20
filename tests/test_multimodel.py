"""Phase 3 multi-model catalog: entitlement, availability, Turbo lock, quotes."""

from __future__ import annotations

from datetime import timedelta

from app.auth import token_sha256
from app.models import ApiKey, User, WorkerCapability, utcnow
from conftest import auth


def _base(**over):
    body = {
        "operation": "music.generate",
        "music_description": "a tune",
        "instrumental": True,
        "duration_seconds": 30,
        "outputs": ["mix_wav"],
    }
    body.update(over)
    return body


def _paid_token(client, *, plan="beginner", subscription="active") -> str:
    """Create an account with a paid subscription + an API key owned by it; return bearer."""
    token = "paid-" + token_sha256(plan + (subscription or "") + str(utcnow()))[:24]
    with client.app.state.db.session() as session:
        user = User(
            id=None, email=f"{token}@e.io", username=token[:20], password_hash="x",
            role="user", state="active", plan=plan, subscription_status=subscription,
            credits_balance=1000,
        )
        session.add(user)
        session.flush()
        session.add(ApiKey(owner_id="usr_" + user.id, name="t", key_sha256=token_sha256(token), key_prefix=token[:8]))
        session.commit()
    return "Bearer " + token


def _grant_sft_worker(client) -> None:
    with client.app.state.db.session() as session:
        session.add(WorkerCapability(
            worker_id="test-sft-worker", model_selection="ace-step-1.5-sft",
            execution_profile_id="sft-quality-v1", engine_model="acestep-v15-sft",
            planner_model="acestep-5Hz-lm-1.7B", tasks_json=["text2music", "cover"],
            max_duration_seconds=600, enabled=True,
        ))
        session.commit()


def _post(client, token, body, key):
    return client.post("/api/v1/jobs", json=body, headers={**auth(token), "Idempotency-Key": key})


def _quote(client, token, body):
    return client.post("/api/v1/generation/quote", json=body, headers=auth(token))


from app.entitlements import has_paid_subscription
from app.models import User


def _u(plan, status=None, period=None, state="active"):
    return User(id="x", email="e@e.io", username="u", password_hash="x", state=state,
                plan=plan, subscription_status=status, current_period_end=period)


def test_has_paid_subscription_matrix():
    from datetime import datetime, timedelta, timezone
    future = datetime.now(timezone.utc) + timedelta(days=10)
    past = datetime.now(timezone.utc) - timedelta(days=1)
    # paid tiers, various status/period states -> entitled
    assert has_paid_subscription(_u("beginner", "active", future)) is True
    assert has_paid_subscription(_u("pro", "active", future)) is True
    assert has_paid_subscription(_u("premier", "active", None)) is True
    assert has_paid_subscription(_u("pro", None, None)) is True          # tier set, no status row (the bug)
    assert has_paid_subscription(_u("premier", None, future)) is True
    assert has_paid_subscription(_u("beginner", "canceling", future)) is True
    # not entitled
    assert has_paid_subscription(_u("free", "active", future)) is False
    assert has_paid_subscription(_u("pro", "canceled", None)) is False   # explicit cancellation
    assert has_paid_subscription(_u("pro", "active", past)) is False     # expired period
    assert has_paid_subscription(_u("premier", "unpaid", None)) is False
    assert has_paid_subscription(_u("pro", "active", future, state="disabled")) is False
    assert has_paid_subscription(None) is False


def test_pro_and_premier_can_run_sft(client) -> None:
    _grant_sft_worker(client)
    for plan in ("pro", "premier"):
        tok = _paid_token(client, plan=plan, subscription="active")
        body = _base(model_selection="ace-step-1.5-sft", controls={"inference_steps": 50, "dcw_enabled": False})
        q = _quote(client, tok, body)
        assert q.status_code == 200, (plan, q.text)
        r = _post(client, tok, dict(body, quote_id=q.json()["quote_id"]), f"mm-tier-{plan}")
        assert r.status_code == 202, (plan, r.text)


def test_pro_null_subscription_status_can_run_sft(client) -> None:
    # Reproduces the reported failure: paid tier with no populated subscription_status.
    _grant_sft_worker(client)
    tok = _paid_token(client, plan="pro", subscription=None)
    body = _base(model_selection="ace-step-1.5-sft", controls={"inference_steps": 50, "dcw_enabled": False})
    q = _quote(client, tok, body)
    assert q.status_code == 200, q.text
    r = _post(client, tok, dict(body, quote_id=q.json()["quote_id"]), "mm-pro-null")
    assert r.status_code == 202, r.text


def test_premier_unprovisioned_premium_gets_503_not_403(client) -> None:
    # A higher tier must not be told it lacks a subscription for a model that is
    # simply not provisioned here; availability (503) is the honest answer.
    tok = _paid_token(client, plan="premier", subscription="active")
    for sel in ("ace-step-1.5-xl-sft", "ace-step-1.5-merge-sft-turbo"):
        r = _post(client, tok, _base(model_selection=sel), f"mm-503-{sel}")
        assert r.status_code == 503, (sel, r.text)
        assert r.json()["error"]["code"] == "MODEL_UNAVAILABLE"


def test_free_account_premium_still_403(client) -> None:
    # Free accounts (any tier below paid) remain gated for provisioned premium.
    _grant_sft_worker(client)
    r = _post(client, "Bearer user-a-secret-token", _base(model_selection="ace-step-1.5-sft"), "mm-free-sft")
    assert r.status_code == 403 and r.json()["error"]["code"] == "PREMIUM_MODEL_REQUIRES_PAID_PLAN"


def test_turbo_locks_steps_and_cfg(client) -> None:
    tok = _paid_token(client)
    r = _post(client, tok, _base(model_selection="ace-step-1.5-turbo", controls={"inference_steps": 16}), "mm-1")
    assert r.status_code == 422 and r.json()["error"]["code"] == "MODEL_PARAMETER_CONFLICT"
    r = _post(client, tok, _base(model_selection="ace-step-1.5-turbo", controls={"guidance_scale": 7}), "mm-2")
    assert r.status_code == 422 and r.json()["error"]["code"] == "MODEL_PARAMETER_CONFLICT"
    r = _post(client, tok, _base(model_selection="ace-step-1.5-turbo", controls={"shift": 3}), "mm-3")
    assert r.status_code == 422 and r.json()["error"]["code"] == "CONTROL_UNSUPPORTED"
    r = _post(client, tok, _base(model_selection="ace-step-1.5-turbo", controls={"sampler_mode": "euler"}), "mm-4")
    assert r.status_code == 422 and r.json()["error"]["code"] == "MODEL_PARAMETER_CONFLICT"


def test_turbo_admits_with_quote_free_and_uncharged_multiplier(client) -> None:
    # Turbo requires no quote; charge equals existing base (multiplier 1.0).
    tok = _paid_token(client)
    r = _post(client, tok, _base(model_selection="ace-step-1.5-turbo"), "mm-turbo")
    assert r.status_code == 202, r.text


def test_sft_requires_paid(client) -> None:
    # TOKEN_A is a non-account API-key owner -> not a paid subscription.
    r = _post(client, "Bearer user-a-secret-token", _base(model_selection="ace-step-1.5-sft"), "mm-sft-guest")
    assert r.status_code == 403 and r.json()["error"]["code"] == "PREMIUM_MODEL_REQUIRES_PAID_PLAN"


def test_unconfigured_release_is_503(client) -> None:
    tok = _paid_token(client)
    for sel in ("ace-step-1.5-xl-sft", "ace-step-1.5-merge-sft-turbo"):
        r = _post(client, tok, _base(model_selection=sel), "mm-" + sel)
        assert r.status_code == 503, r.text
        assert r.json()["error"]["code"] == "MODEL_UNAVAILABLE"


def test_sft_needs_compatible_worker_else_503(client) -> None:
    tok = _paid_token(client)
    r = _post(client, tok, _base(model_selection="ace-step-1.5-sft"), "mm-sft-noworker")
    assert r.status_code == 503 and r.json()["error"]["code"] == "NO_COMPATIBLE_WORKER"


def test_sft_premium_requires_quote(client) -> None:
    tok = _paid_token(client)
    _grant_sft_worker(client)
    r = _post(client, tok, _base(model_selection="ace-step-1.5-sft"), "mm-sft-noquote")
    assert r.status_code == 422 and r.json()["error"]["code"] == "QUOTE_REQUIRED"


def test_quote_then_sft_admission_binds_and_charges(client) -> None:
    tok = _paid_token(client)
    _grant_sft_worker(client)
    body = _base(model_selection="ace-step-1.5-sft", controls={"inference_steps": 50, "guidance_scale": 2.5, "dcw_enabled": False})
    q = _quote(client, tok, body)
    assert q.status_code == 200, q.text
    qd = q.json()
    assert qd["reserved_credits"] == 20 and qd["policy_version"]  # base 10 * 2.0 mult
    r = _post(client, tok, dict(body, quote_id=qd["quote_id"]), "mm-sft-quoted")
    assert r.status_code == 202, r.text


def test_quote_tamper_mismatch_rejected(client) -> None:
    tok = _paid_token(client)
    _grant_sft_worker(client)
    body = _base(model_selection="ace-step-1.5-sft")
    qd = _quote(client, tok, body).json()
    # Change the request after quoting (steps) -> hash/compute mismatch.
    tampered = dict(body, controls={"inference_steps": 60, "guidance_scale": 2.5, "dcw_enabled": False})
    r = _post(client, tok, dict(tampered, quote_id=qd["quote_id"]), "mm-tamper")
    assert r.status_code == 409 and r.json()["error"]["code"] in ("QUOTE_MISMATCH",)


def test_quote_expiry_rejected(client) -> None:
    tok = _paid_token(client)
    _grant_sft_worker(client)
    body = _base(model_selection="ace-step-1.5-sft", controls={"inference_steps": 50, "dcw_enabled": False})
    qd = _quote(client, tok, body).json()
    from app.models import Quote
    with client.app.state.db.session() as session:
        quote = session.get(Quote, qd["quote_id"])
        quote.expires_at = utcnow() - timedelta(minutes=1)
        session.commit()
    r = _post(client, tok, dict(body, quote_id=qd["quote_id"]), "mm-expiry")
    assert r.status_code == 409 and r.json()["error"]["code"] == "QUOTE_EXPIRED"


def test_model_selections_catalog_public(client) -> None:
    r = client.get("/api/v1/model-selections")
    assert r.status_code == 200
    by_id = {s["model_selection"]: s for s in r.json()}
    assert {"ace-step-1.5-turbo", "ace-step-1.5-sft", "ace-step-1.5-xl-sft", "ace-step-1.5-merge-sft-turbo"} <= set(by_id)
    turbo = by_id["ace-step-1.5-turbo"]["profiles"][0]
    assert turbo["availability"] == "available" and turbo["requires_paid"] is False
    assert turbo["control_ranges"]["inference_steps"]["max"] == 8
    assert turbo["control_ranges"]["guidance_scale"]["locked"] is True
    sft = by_id["ace-step-1.5-sft"]["profiles"][0]
    assert sft["requires_paid"] is True and sft["control_ranges"]["inference_steps"]["min"] == 50
    assert sft["control_ranges"]["dcw_forced_off"] is True
    assert by_id["ace-step-1.5-merge-sft-turbo"]["availability"] == "unconfigured"
    # no private engine path leaked
    assert "/opt" not in r.text and "/root" not in r.text


def test_openapi_exposes_new_contracts(client) -> None:
    spec = client.get("/api/v1/openapi.json")
    if spec.status_code == 404:
        spec = client.get("/openapi.json")
    assert spec.status_code == 200
    paths = spec.json()["paths"]
    assert "/api/v1/generation/quote" in paths
    assert "/api/v1/model-selections" in paths
