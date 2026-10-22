"""Model Lab M3: vocal scan, singer clustering, group review, BYOL gate."""

from __future__ import annotations

import math
from array import array

import pytest

from app import model_lab_voice
from conftest import auth


def _sine(freq: float, seconds: float = 1.0, amp: float = 0.3) -> array:
    n = int(16000 * seconds)
    return array("h", [int(amp * 32767 * math.sin(2 * math.pi * freq * i / 16000)) for i in range(n)])


def _seed_rec(client, tmp_path, duration=20.0):
    from app.models import MlRecording, MlSource, new_uuid

    path = tmp_path / "song.mp3"
    path.write_bytes(b"x")
    with client.app.state.db.session() as session:
        src = MlSource(id=new_uuid(), name=f"v-src-{next(_SEQ)}", status="approved")
        session.add(src)
        session.commit()
        rec = MlRecording(id=new_uuid(), source_id=src.id, path=str(path),
                          sha256=f"v-sha-{next(_SEQ)}", duration_seconds=duration)
        session.add(rec)
        session.commit()
        session.expunge(rec)
        return rec


_SEQ = iter(range(1, 10000))


@pytest.fixture(autouse=True)
def _admin_session(client):
    from app.models import User

    client.post("/api/v1/auth/logout")
    email = f"ml3admin{next(_SEQ)}@example.com"
    resp = client.post("/api/v1/auth/register",
                       json={"email": email, "username": f"ml3a{next(_SEQ)}",
                             "password": "super-secret-1"})
    uid = resp.json()["user"]["id"]
    with client.app.state.db.session() as session:
        session.get(User, uid).role = "admin"
        session.commit()


def test_byol_challenger_fails_closed() -> None:
    from app.config import get_settings

    class S:
        voice_embedding_model = "mfcc-stats-v1"
        voice_identity_challenger = "byol-v1"

    with pytest.raises(model_lab_voice.VoiceLabError):
        model_lab_voice.resolve_identity_model(S())
    S.voice_identity_challenger = ""
    assert model_lab_voice.resolve_identity_model(S()) == "mfcc-stats-v1"


def test_voice_scan_energy_gate_and_embeddings(client, tmp_path, monkeypatch) -> None:
    rec = _seed_rec(client, tmp_path, duration=12.0)
    crops = {"n": 0}

    def fake_crop(ffmpeg_bin, path, start, seconds):
        crops["n"] += 1
        return _sine(220.0) if start >= 3.0 else array("h", [0] * 16000)  # first window silent

    monkeypatch.setattr(model_lab_voice, "decode_crop", fake_crop)
    with client.app.state.db.session() as session:
        from app.models import MlEmbeddingVector, MlRecording, MlVoiceSegment

        result = model_lab_voice.scan_recording(session, session.get(MlRecording, rec.id),
                                                client.app.state.settings)
        assert result["segments"] >= 1 and result["model"] == "mfcc-stats-v1"
        segs = session.query(MlVoiceSegment).filter_by(recording_id=rec.id).all()
        assert all(s.crop_start >= 3.0 for s in segs)  # silent window skipped
        assert session.query(MlEmbeddingVector).filter(
            MlEmbeddingVector.segment_id.in_([s.id for s in segs])).count() == len(segs)


def test_cluster_groups_similar_voices(client, tmp_path) -> None:
    from app.models import (MlEmbeddingVector, MlRecording, MlSource, MlVoiceSegment,
                            MlVoiceGroup, new_uuid)

    with client.app.state.db.session() as session:
        src = MlSource(id=new_uuid(), name=f"cl-src-{next(_SEQ)}", status="approved")
        session.add(src)
        session.commit()
        rec = MlRecording(id=new_uuid(), source_id=src.id, path="/x/s.mp3",
                          sha256=f"cl-{next(_SEQ)}", duration_seconds=10.0)
        session.add(rec)
        session.commit()
        voices = [[1.0, 0.0, 0.5], [0.99, 0.01, 0.5], [0.0, 1.0, 0.2]]
        for v in voices:
            seg = MlVoiceSegment(id=new_uuid(), recording_id=rec.id, crop_start=0, crop_end=6)
            session.add(seg)
            session.flush()
            session.add(MlEmbeddingVector(id=new_uuid(), segment_id=seg.id,
                                          model="mfcc-stats-v1", vector_json=v))
        session.commit()
        result = model_lab_voice.cluster_segments(session, client.app.state.settings)
        assert result["groups"] == 1  # two similar voices form one group; singleton dropped
        grp = session.query(MlVoiceGroup).one()
        assert grp.member_count == 2 and grp.state == "suggested"
        grp_id = grp.id

    r = client.post(f"/api/v1/admin/model-lab/voice-groups/{grp_id}/review",
                    json={"decision": "approve"})
    assert r.status_code == 200 and r.json()["state"] == "approved"
    segs = client.get(f"/api/v1/admin/model-lab/voice-segments?group_id={grp_id}").json()["segments"]
    assert all(s["state"] == "accepted" for s in segs)


def test_group_merge_and_validation(client, tmp_path) -> None:
    from app.models import (MlEmbeddingVector, MlRecording, MlSource, MlVoiceSegment,
                            MlVoiceGroup, new_uuid)

    with client.app.state.db.session() as session:
        src = MlSource(id=new_uuid(), name=f"mg-src-{next(_SEQ)}", status="approved")
        session.add(src)
        session.commit()
        rec = MlRecording(id=new_uuid(), source_id=src.id, path="/x/m.mp3",
                          sha256=f"mg-{next(_SEQ)}", duration_seconds=10.0)
        session.add(rec)
        session.commit()
        groups = []
        for v in ([1.0, 0.0], [0.0, 1.0]):
            grp = MlVoiceGroup(id=new_uuid(), embedding_model="mfcc-stats-v1",
                               centroid_json=v, member_count=1)
            session.add(grp)
            session.flush()
            seg = MlVoiceSegment(id=new_uuid(), recording_id=rec.id, crop_start=0,
                                 crop_end=6, group_id=grp.id)
            session.add(seg)
            groups.append(grp.id)
        session.commit()
        a, b = groups
    bad = client.post(f"/api/v1/admin/model-lab/voice-groups/{a}/review",
                      json={"decision": "merge"})
    assert bad.status_code == 422  # merge without target
    r = client.post(f"/api/v1/admin/model-lab/voice-groups/{a}/review",
                    json={"decision": "merge", "merge_into": b})
    assert r.status_code == 200 and r.json()["state"] == "merged"
    groups = client.get("/api/v1/admin/model-lab/voice-groups").json()["groups"]
    target = next(g for g in groups if g["id"] == b)
    assert target["member_count"] == 2


def test_voice_scan_endpoint_404(client) -> None:
    r = client.post("/api/v1/admin/model-lab/recordings/nope/voice-scan")
    assert r.status_code == 404
