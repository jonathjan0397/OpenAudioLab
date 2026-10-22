"""Batch 4: rights gates, splits, lyric training text, acceptance, disk guard."""

from __future__ import annotations

import hashlib

import pytest

_SEQ = iter(range(1, 10000))


@pytest.fixture(autouse=True)
def _admin_session(client):
    from app.models import User

    client.post("/api/v1/auth/logout")
    resp = client.post("/api/v1/auth/register",
                       json={"email": f"b4{next(_SEQ)}@example.com",
                             "username": f"b4a{next(_SEQ)}", "password": "super-secret-1"})
    uid = resp.json()["user"]["id"]
    with client.app.state.db.session() as session:
        session.get(User, uid).role = "admin"
        session.commit()


def _rec(client, *, artist="Alabama", title=None, lyrics=None, origin=None,
         tags_state="parsed", review="approved"):
    from app.models import MlRecording, MlSource, new_uuid

    title = title or f"Song {next(_SEQ)}"
    with client.app.state.db.session() as session:
        src = MlSource(id=new_uuid(), name=f"b4s-{next(_SEQ)}", status="approved")
        session.add(src)
        session.commit()
        rec = MlRecording(id=new_uuid(), source_id=src.id, path=f"/x/{title}.mp3",
                          sha256=f"b4-{next(_SEQ)}", duration_seconds=200.0, bytes=8_000_000,
                          artist=artist, title=title, genre_raw="Country",
                          review_status=review, dataset_eligible=True,
                          tags_state=tags_state, lyrics_text=lyrics, lyrics_origin=origin)
        session.add(rec)
        session.commit()
        return rec.id


def _grant(client, ids, scopes=("recording",)):
    from app.models import MlRightsRecord, new_uuid

    with client.app.state.db.session() as session:
        for rid in ids:
            for scope in scopes:
                session.add(MlRightsRecord(id=new_uuid(), recording_id=rid, holder="owner",
                                           scope=scope, evidence="test"))
        session.commit()


def test_freeze_requires_rights(client) -> None:
    rid = _rec(client)
    r = client.post("/api/v1/admin/model-lab/datasets",
                    json={"name": f"nr-{next(_SEQ)}", "recording_ids": [rid]})
    assert r.status_code == 422 and "rights declarations missing" in r.json()["error"]["message"]
    _grant(client, [rid])
    ok = client.post("/api/v1/admin/model-lab/datasets",
                     json={"name": f"gr-{next(_SEQ)}", "recording_ids": [rid]})
    assert ok.status_code == 201


def test_voice_dataset_requires_identity_and_lyrics(client) -> None:
    rid = _rec(client, tags_state="parsed")
    _grant(client, [rid], scopes=("recording",))
    r = client.post("/api/v1/admin/model-lab/datasets",
                    json={"name": f"v-{next(_SEQ)}", "recording_ids": [rid], "kind": "voice"})
    assert "singer" in r.json()["error"]["message"]  # missing singer_identity scope
    _grant(client, [rid], scopes=("singer_identity",))
    r2 = client.post("/api/v1/admin/model-lab/datasets",
                     json={"name": f"v2-{next(_SEQ)}", "recording_ids": [rid], "kind": "voice"})
    assert r2.status_code == 422 and "missing lyrics" in r2.json()["error"]["message"]
    r3 = client.post("/api/v1/admin/model-lab/datasets",
                     json={"name": f"v3-{next(_SEQ)}", "recording_ids": [rid], "kind": "voice",
                           "allow_instrumental": True})
    assert r3.status_code == 201 and r3.json()["report"]["splits"]


def test_splits_are_grouped_by_artist_and_stable(client) -> None:
    a1, a2 = _rec(client, artist="Alabama"), _rec(client, artist="Alabama")
    b1 = _rec(client, artist="Eric Church")
    ids = [a1, a2, b1]
    _grant(client, ids)
    ds = client.post("/api/v1/admin/model-lab/datasets",
                     json={"name": f"sp-{next(_SEQ)}", "recording_ids": ids}).json()
    from app.models import MlDataset
    from sqlalchemy import select

    with client.app.state.db.session() as session:
        entries = session.get(MlDataset, ds["id"]).manifest_json["entries"]
    splits = [e["split"] for e in entries]
    assert set(splits) <= {"train", "validation", "holdout"}
    from app.model_lab_train import assign_split

    assert assign_split("Alabama", 2026) == assign_split("alabama", 2026)
    buckets = {assign_split(f"Artist {i}", 2026) for i in range(500)}
    assert len(buckets) == 3  # all three splits reachable at scale


def test_lrc_sidecar_stripped_for_training_in_manifest(client) -> None:
    raw = "[00:10.00]First line\n[00:22.50]Second line"
    rid = _rec(client, lyrics=raw, origin="sidecar")
    with client.app.state.db.session() as session:
        from app.models import MlRecording
        rec = session.get(MlRecording, rid)
        rec.lyrics_provenance_json = {"kind": "lrc", "path": "/x/a.lrc"}
        session.commit()
    _grant(client, [rid], scopes=("recording", "singer_identity"))
    ds = client.post("/api/v1/admin/model-lab/datasets",
                     json={"name": f"lrc-{next(_SEQ)}", "recording_ids": [rid],
                           "kind": "voice"}).json()
    from app.models import MlDataset

    with client.app.state.db.session() as session:
        entry = session.get(MlDataset, ds["id"]).manifest_json["entries"][0]
    assert entry["lyrics"] == "First line\nSecond line"
    assert entry["lyrics_sha256"] == hashlib.sha256(entry["lyrics"].encode()).hexdigest()
    assert entry["caption"].startswith("Alabama - ")


def test_rights_routes_roundtrip(client) -> None:
    rid = _rec(client)
    declared = client.post(f"/api/v1/admin/model-lab/recordings/{rid}/rights",
                           json={"holder": "Owner Co", "scope": "recording",
                                 "evidence": "purchase archive"})
    assert declared.status_code == 201
    listing = client.get(f"/api/v1/admin/model-lab/recordings/{rid}/rights").json()["records"]
    assert len(listing) == 1 and listing[0]["state"] == "declared"
    revoked = client.post(f"/api/v1/admin/model-lab/rights/{listing[0]['id']}/revoke")
    assert revoked.json()["state"] == "revoked"
    blocked = client.post("/api/v1/admin/model-lab/datasets",
                          json={"name": f"rev-{next(_SEQ)}", "recording_ids": [rid]})
    assert blocked.status_code == 422
    bulk = client.post("/api/v1/admin/model-lab/rights/declare-selected",
                       json={"recording_ids": [rid], "holder": "Owner Co", "scope": "recording",
                             "scopes": ["recording", "singer_identity"]})
    assert bulk.status_code == 201 and bulk.json()["records_created"] == 2


def test_recordings_list_never_leaks_lyric_text(client) -> None:
    _rec(client, lyrics="secret human lyric text", origin="submitted")
    body = client.get("/api/v1/admin/model-lab/recordings?limit=200").json()
    assert all("lyrics_text" not in r for r in body["recordings"])
    assert any(r["lyrics_chars"] > 0 and r["lyrics_origin"] == "submitted"
               for r in body["recordings"])


def test_disk_preflight_fails_explicitly(client, monkeypatch) -> None:
    from types import SimpleNamespace
    import app.training_worker as tw
    from app.model_lab_train import attach_job, get_budget, open_attempt
    from app.models import MlBudget, MlDataset, MlTrainingAttempt, new_uuid

    client.app.state.settings.model_lab_train_command = "echo train"
    ds = MlDataset(id=new_uuid(), name="disk-gate", frozen_sha256="f",
                   manifest_json={"entries": [{"sha256": "a", "path": "/a", "bytes": 9_000_000,
                                               "seconds": 200.0, "caption": "c",
                                               "split": "train", "lyrics": None}]})
    with client.app.state.db.session() as session:
        session.add(ds)
        budget = get_budget(session, client.app.state.settings)
        session.commit()
        attempt = open_attempt(session, ds, budget, est_hours=0.1, est_spend_usd=0.1)
        job = attach_job(session, attempt, "model-lab", client.app.state.settings)
        attempt_id, job_id = attempt.id, job.id

    def tiny_free(path):
        return SimpleNamespace(total=2 * 2 ** 40, used=0, free=1024)

    import shutil

    monkeypatch.setattr(shutil, "disk_usage", tiny_free)
    w = SimpleNamespace(db=client.app.state.db, storage=client.app.state.storage,
                        settings=client.app.state.settings, worker_id="w-disk",
                        node_key="disk-node")

    from app.fleet_nodes import register_node

    with client.app.state.db.session() as session:
        register_node(session, "disk-node", worker_id="w-disk")
    w._release_node = lambda: tw.TrainingWorker._release_node(w)
    tw.TrainingWorker._model_lab_train(w, job_id, attempt_id, "lease-x")
    with client.app.state.db.session() as session:
        att = session.get(MlTrainingAttempt, attempt_id)
        assert att.state == "failed" and "INSUFFICIENT_DISK" in (att.error or "")
        assert session.get(MlBudget, att.budget_id).reserved_usd == 0.0
