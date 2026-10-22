"""Model Lab M1: legacy repairs (tagging contract, tag hygiene, offer units, selector)."""

from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess

from app import tagging
from conftest import auth


def _load_script(name: str):
    root = pathlib.Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(name, root / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- tagging

def test_fingerprint_reads_fingerprint_key(monkeypatch) -> None:
    class Done:
        stdout = json.dumps({"duration": 12.5, "fingerprint": "AQDC123"}).encode()

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Done())
    fp = tagging.fingerprint(pathlib.Path("/tmp/x.mp3"))
    assert fp == {"duration": 12.5, "fingerprint": "AQDC123"}


def test_fingerprint_legacy_signature_key_fallback(monkeypatch) -> None:
    class Done:
        stdout = json.dumps({"duration": 3.0, "signature": "AAA"}).encode()

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Done())
    assert tagging.fingerprint(pathlib.Path("/tmp/x.mp3"))["fingerprint"] == "AAA"


class _Resp:
    def __init__(self, body):
        self._b = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._b


def test_acoustid_lookup_uses_fingerprint_param_and_artist_array(monkeypatch) -> None:
    import httpx

    seen: dict = {}

    body = {"status": "ok", "results": [{"score": 0.91, "recordings": [
        {"id": "r1", "title": "Song", "artists": [
            {"name": "Alpha", "joinphrase": " feat. "}, {"name": "Beta"}]}]}]}

    def fake_get(url, params=None, headers=None, timeout=None):
        seen.update(params or {})
        return _Resp(body)

    monkeypatch.setattr(httpx, "get", fake_get)
    out = tagging.acoustid_lookup("FPDATA", 30.0, "client-key")
    assert out["status"] == "ok"
    assert seen["fingerprint"] == "FPDATA" and "signature" not in seen
    m = out["matches"][0]
    assert m["artist"] == "Alpha feat. Beta" and m["artists"] == ["Alpha", "Beta"]


def test_acoustid_status_distinguishes_failure_from_no_match(monkeypatch) -> None:
    import httpx

    assert tagging.acoustid_lookup("FP", 1.0, "")["status"] == "no_key"

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Resp({"status": "ok", "results": []}))
    assert tagging.acoustid_lookup("FP", 1.0, "k")["status"] == "no_match"

    def boom(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "get", boom)
    out = tagging.acoustid_lookup("FP", 1.0, "k")
    assert out["status"] == "provider_error" and out["matches"] == []


# ------------------------------------------------------------ tag hygiene

def test_suggestions_exclude_identity_and_private_tags(client) -> None:
    from app.models import Asset, Lora

    with client.app.state.db.session() as session:
        session.add(Asset(id="m1-a1", job_id="j", owner_id="o", storage_key="k", role="output",
                          kind="audio", mime="audio/wav", bytes=1, sha256="x", synthetic=False,
                          tags_json=["artist:Radiohead", "title:Paranoid Android", "energetic"]))
        session.add(Lora(id="m1-l1", name="house-private", kind="genre", tags_json=["secret_house"],
                         state="active", visibility="private"))
        session.add(Lora(id="m1-l2", name="house-public", kind="genre", tags_json=["open_house"],
                         state="active", visibility="public"))
        session.commit()
    from app.routes.styles import _active_lora_tags, _trending_tags

    with client.app.state.db.session() as session:
        trending = _trending_tags(session)
        lora_tags = _active_lora_tags(session)
    assert "energetic" in trending
    assert "artist:Radiohead" not in trending and "title:Paranoid Android" not in trending
    assert "open_house" in lora_tags and "secret_house" not in lora_tags
    resp = client.get("/api/v1/styles/suggest", headers=auth())
    assert resp.status_code == 200


# ------------------------------------------------------------- vast offers

def test_cuda_version_tuple_comparison() -> None:
    from app.vast_offers import _ver_tuple, criteria_defaults, ineligible_reason, normalize

    assert _ver_tuple("12.10") > _ver_tuple("12.8")
    crit = criteria_defaults()
    ok = normalize({"id": 1, "gpu_name": "X", "gpu_ram": 24576, "cuda_max_good": 12.10,
                    "geolocation": "Texas, US", "reliability2": 0.99, "dph_total": 0.10,
                    "disk_space": 200.0, "verified": True, "rentable": True})
    ok["cuda"] = "12.10"
    assert ineligible_reason(ok, crit) is None
    low = dict(ok, cuda="12.4")
    assert ineligible_reason(low, crit) == "CUDA_UNSUPPORTED"


def test_unknown_reliability_scores_neutral() -> None:
    from app.vast_offers import criteria_defaults, normalize, score

    crit = criteria_defaults()
    base = {"id": 1, "gpu_name": "X", "gpu_ram": 24576, "cuda_max_good": 12.8,
            "geolocation": "Texas, US", "dph_total": 0.10, "disk_space": 200.0,
            "verified": True, "rentable": True}
    unknown = normalize(dict(base, reliability2=None))
    neutral = normalize(dict(base, reliability2=0.5))
    assert score(unknown, crit) == score(neutral, crit)


# --------------------------------------------------------------- selector

def test_selector_multilabel_caption_and_vocal_evidence() -> None:
    sf = _load_script("select_family")
    assert sf.norm_families("country rock") == ["country", "rock"]  # multilabel, specific first
    assert sf.norm_family("free jazz") == "jazz"
    cap = sf.caption({"artist": "The Band", "title": "The Weight", "decade": "1960s"}, "country")
    assert "The Weight" in cap and "The Band" in cap
    # Genre evidence marks instrumental without touching ffmpeg.
    assert sf.vocal_estimate({"genre": "Instrumental Jazz", "path": "/nope"}) == "instrumental"
    # Ambiguous material without ffmpeg data stays unknown (never silent instrumental).
    monkey_off = sf.vocal_estimate({"genre": "pop", "path": "/definitely/missing.mp3"})
    assert monkey_off == "unknown"


def test_lora_visibility_defaults_public(client) -> None:
    from app.models import Lora

    with client.app.state.db.session() as session:
        session.add(Lora(id="m1-l3", name="default-vis", kind="voice"))
        session.commit()
        assert session.get(Lora, "m1-l3").visibility == "public"
