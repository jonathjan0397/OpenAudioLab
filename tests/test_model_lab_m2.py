"""Model Lab M2: importer classification, identification pipeline, coverage, selection."""

from __future__ import annotations

import json
import pathlib

from app import model_lab, tagging
from conftest import auth


_ADMIN_SEQ = iter(range(1, 1000))


def _make_admin(client) -> None:
    from app.models import User

    client.post("/api/v1/auth/logout")
    email = f"mladmin{next(_ADMIN_SEQ)}@example.com"
    resp = client.post("/api/v1/auth/register",
                       json={"email": email, "username": email.split("@")[0],
                             "password": "super-secret-1"})
    uid = resp.json()["user"]["id"]
    with client.app.state.db.session() as session:
        session.get(User, uid).role = "admin"
        session.commit()


def _mkfile(p: pathlib.Path, body: bytes = b"audio-bytes") -> pathlib.Path:
    p.write_bytes(body)
    return p


def _source(client, tmp: pathlib.Path, manifest: list[dict] | None = None):
    from app.models import MlSource, new_uuid

    if manifest is not None:
        root = tmp / "manifest.jsonl"
        root.write_text("\n".join(json.dumps(m) for m in manifest), encoding="utf-8")
        path = str(root)
    else:
        path = str(tmp)
    with client.app.state.db.session() as session:
        src = MlSource(id=new_uuid(), name=f"src-{next(_SRC_SEQ)}", path=path, status="approved")
        session.add(src)
        session.commit()
        session.expunge(src)
        return src


_SRC_SEQ = iter(range(1, 1000))


def test_importer_classification(client, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(model_lab, "probe_file", lambda p, ffprobe_bin="ffprobe":
                        {"duration_seconds": 12.0, "format": "mp3", "sample_rate": 44100, "channels": 2})
    a = _mkfile(tmp_path / "a.mp3", b"alpha-content")
    b = _mkfile(tmp_path / "b.flac", b"bravo-content")
    _mkfile(tmp_path / "notes.txt", b"hi")
    src = _source(client, tmp_path)

    with client.app.state.db.session() as session:
        r1 = model_lab.scan_source(session, src, preview=False)
        assert r1["counts"]["new"] == 2 and r1["counts"]["excluded"] == 1
        r2 = model_lab.scan_source(session, src, preview=False)
        assert r2["counts"]["cached"] == 2
        a.write_bytes(b"alpha-changed!")  # changed content -> new sha
        r3 = model_lab.scan_source(session, src, preview=False)
        assert r3["counts"]["changed"] == 1 and r3["counts"]["new"] == 0
        _mkfile(tmp_path / "c.mp3", b"alpha-changed!")  # same sha as a -> duplicate
        r4 = model_lab.scan_source(session, src, preview=False)
        assert r4["counts"]["duplicate"] == 1


def test_importer_manifest_supplier_claims(client, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(model_lab, "probe_file", lambda p, ffprobe_bin="ffprobe":
                        {"duration_seconds": 200.0, "format": "mp3", "sample_rate": 44100, "channels": 2})
    _mkfile(tmp_path / "s1.mp3")
    src = _source(client, tmp_path, manifest=[
        {"path": str(tmp_path / "s1.mp3"), "title": "Song One", "artist": "Performer",
         "genre": "country", "families": ["country_americana"]}])
    with client.app.state.db.session() as session:
        model_lab.scan_source(session, src, preview=False)
        from app.models import MlMetadataClaim, MlRecording

        rec = session.query(MlRecording).filter_by(source_id=src.id).first()
        assert rec.families_json[0] == "country_americana"  # supplier lane first
            assert "country.country" in rec.families_json and "fam:country" in rec.families_json
        claims = session.query(MlMetadataClaim).filter_by(recording_id=rec.id).all()
        assert {c.field for c in claims} == {"title", "artist", "genre"}
        assert all(c.provenance == "supplier" for c in claims)


def _seed_recording(client, tmp_path, sha_body: bytes = b"rec-bytes"):
    from app.models import MlRecording, MlSource, new_uuid

    path = _mkfile(tmp_path / "rec.mp3", sha_body)
    with client.app.state.db.session() as session:
        src = MlSource(id=new_uuid(), name=f"ident-src-{next(_SRC_SEQ)}", status="approved")
        session.add(src)
        session.commit()
        rec = MlRecording(id=new_uuid(), source_id=src.id, path=str(path),
                          sha256=f"sha-{next(_SRC_SEQ)}", duration_seconds=30.0)
        session.add(rec)
        session.commit()
        session.expunge(rec)
        return rec


def test_identify_match_creates_pending_claims_and_enriches(client, tmp_path, monkeypatch) -> None:
    rec = _seed_recording(client, tmp_path)
    monkeypatch.setattr(tagging, "fingerprint", lambda p: {"duration": 30.0, "fingerprint": "FP"})
    calls = {"acoustid": 0, "mb": 0}

    def fake_lookup(fp, dur, key):
        calls["acoustid"] += 1
        return {"status": "ok", "matches": [{"score": 0.95, "title": "Matched",
                                             "artist": "Matched Artist", "recording_id": "mb-1"}]}

    def fake_mb(session, mbid, base, ua, rate_limit_s=1.0):
        calls["mb"] += 1
        return {"title": "MB Title", "artist-credit": [{"name": "MB Artist", "joinphrase": ""}],
                "isrcs": ["USX1X2345678"]}

    monkeypatch.setattr(tagging, "acoustid_lookup", fake_lookup)
    monkeypatch.setattr(model_lab, "musicbrainz_recording", fake_mb)
    with client.app.state.db.session() as session:
        from app.models import MlMetadataClaim, MlRecording

        status = model_lab.identify_recording(session, session.get(MlRecording, rec.id),
                                              client.app.state.settings)
        assert status == "review_required"
        claims = session.query(MlMetadataClaim).filter_by(recording_id=rec.id).all()
        by_prov = {c.provenance for c in claims}
        assert {"acoustid", "musicbrainz"} <= by_prov
        assert all(c.status == "suggested" for c in claims)  # never auto-approved
        # provider cache: second identify does not re-hit AcoustID
        model_lab.identify_recording(session, session.get(MlRecording, rec.id),
                                     client.app.state.settings)
        assert calls["acoustid"] == 1 and calls["mb"] == 2  # MB cache lives in the real fn


def test_identify_no_match_and_outage_statuses(client, tmp_path, monkeypatch) -> None:
    rec = _seed_recording(client, tmp_path)
    monkeypatch.setattr(tagging, "fingerprint", lambda p: {"duration": 30.0, "fingerprint": "FP"})
    with client.app.state.db.session() as session:
        from app.models import MlRecording

        monkeypatch.setattr(tagging, "acoustid_lookup",
                            lambda fp, dur, key: {"status": "no_match", "matches": []})
        assert model_lab.identify_recording(session, session.get(MlRecording, rec.id),
                                            client.app.state.settings) == "no_match"
        from app.models import MlProviderCache

        session.query(MlProviderCache).delete()  # drop the cached no_match before outage test
        monkeypatch.setattr(tagging, "acoustid_lookup",
                            lambda fp, dur, key: {"status": "provider_error", "matches": []})
        assert model_lab.identify_recording(session, session.get(MlRecording, rec.id),
                                            client.app.state.settings) == "provider_outage"


def test_review_and_dataset_eligibility(client, tmp_path) -> None:
    _make_admin(client)
    rec = _seed_recording(client, tmp_path)
    from app.models import MlRecording as _R
    from app.models import MlSource

    with client.app.state.db.session() as session:
        rec_source_id = [session.get(_R, rec.id).source_id]
    r = client.post(f"/api/v1/admin/model-lab/recordings/{rec.id}/review",
                    json={"decision": "approved"})
    assert r.status_code == 200
    # source is approved, so eligible; then restrict the source -> eligibility must drop
    assert r.json()["dataset_eligible"] is True
    with client.app.state.db.session() as session:
        src = session.query(MlSource).filter_by(id=rec_source_id[0]).first()
        sid = src.id
    r = client.patch(f"/api/v1/admin/model-lab/sources/{sid}",
                     json={"status": "restricted"})
    assert r.status_code == 200
    r = client.get(f"/api/v1/admin/model-lab/recordings/{rec.id}")
    assert r.json()["dataset_eligible"] is False
    bad = client.post(f"/api/v1/admin/model-lab/recordings/{rec.id}/review",
                      json={"decision": "bogus"})
    assert bad.status_code == 422


def test_coverage_no_double_count(client, tmp_path) -> None:
    _make_admin(client)
    from app.models import MlRecording, MlSource, new_uuid

    with client.app.state.db.session() as session:
        before = model_lab.coverage(session)
        src = MlSource(id=new_uuid(), name=f"cov-src-{next(_SRC_SEQ)}", status="approved")
        session.add(src)
        session.commit()
        session.add(MlRecording(id=new_uuid(), source_id=src.id, path="/x/1.mp3", sha256="c1",
                                duration_seconds=100.0, artist="A", title="T1",
                                families_json=["folk_acoustic", "metal"]))
        session.add(MlRecording(id=new_uuid(), source_id=src.id, path="/x/2.mp3", sha256="c2",
                                duration_seconds=50.0, artist="B", title="T2",
                                families_json=["metal"]))
        session.commit()
        cov = model_lab.coverage(session)
    assert cov["recordings"] - before["recordings"] == 2
    assert cov["total_seconds"] - before["total_seconds"] == 150.0  # physical total
    assert cov["lanes"]["folk_acoustic"]["recordings"] == 1
    assert cov["lanes"]["metal"]["recordings"] == 2  # multilabel overlap allowed per lane
    assert cov["lanes"]["metal"]["seconds"] == 150.0


def test_selection_policy_defaults_and_validation(client) -> None:
    _make_admin(client)
    sel = client.get("/api/v1/admin/model-lab/selection").json()
    assert sel == {"replay_pct": 60, "weak_model_pct": 30, "rare_pct": 10,
                   "performer_cap_pct": 10}
    r = client.patch("/api/v1/admin/model-lab/selection",
                     json={"replay_pct": 50, "weak_model_pct": 40})
    assert r.status_code == 200 and r.json()["weak_model_pct"] == 40
    bad = client.patch("/api/v1/admin/model-lab/selection",
                       json={"replay_pct": 90, "weak_model_pct": 5, "rare_pct": 5})
    assert bad.status_code == 200  # 90+5+5 = 100 is valid
    bad2 = client.patch("/api/v1/admin/model-lab/selection",
                        json={"replay_pct": 70})
    assert bad2.status_code == 422  # 70+30+10 = 110


def test_tag_registry_and_assignment(client, tmp_path) -> None:
    _make_admin(client)
    rec = _seed_recording(client, tmp_path)
    tags = client.get("/api/v1/admin/model-lab/tags").json()
    assert len(tags["lanes"]) == 24
    assert any(t["id"].startswith("mood:") or ":" in t["id"] for t in tags["terms"])
    term_id = tags["terms"][0]["id"]
    r = client.post(f"/api/v1/admin/model-lab/recordings/{rec.id}/tags",
                    json={"term_id": term_id, "provenance": "curator"})
    assert r.status_code == 201
    bad = client.post(f"/api/v1/admin/model-lab/recordings/{rec.id}/tags",
                      json={"term_id": "nope:missing"})
    assert bad.status_code == 422
