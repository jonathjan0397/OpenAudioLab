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
    token = "paid-" + token_sha256(plan + subscription + str(utcnow()))[:24]
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
