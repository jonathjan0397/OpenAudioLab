"""Batch 3: external verify/lyrics passes (fake fetchers; no network in tests)."""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

from app.library_external import (ExternalError, lrclib_lookup, musicbrainz_lookup,
                                  musicbrainz_score)
from app.orchestration import claim_attempt
from app.training_worker import TrainingWorker

_SEQ = iter(range(1, 10000))


@pytest.fixture(autouse=True)
def _admin_session(client):
    from app.models import User

    client.post("/api/v1/auth/logout")
    resp = client.post("/api/v1/auth/register",
                       json={"email": f"b3{next(_SEQ)}@example.com",
                             "username": f"b3a{next(_SEQ)}", "password": "super-secret-1"})
    uid = resp.json()["user"]["id"]
    with client.app.state.db.session() as session:
        session.get(User, uid).role = "admin"
        session.commit()


def test_musicbrainz_score_basics() -> None:
    rec = {"title": "Song Of The South", "credit": [{"name": "Alabama"}],
           "length": 241000}
    assert musicbrainz_score(rec, "Alabama", "Song Of The South", 241.2) >= 9
    assert musicbrainz_score(rec, "Alabama", "Song of the South (Remaster)", 241.0) >= 7
    assert musicbrainz_score(rec, "Nobody", "Else", 999) <= 4


def test_musicbrainz_lookup_match_and_errors() -> None:
    def fetcher(url, params=None, timeout=25.0):
        if "recording" in url:
            return 200, {"recordings": [{"id": "mb-1", "title": "Song Of The South",
                                         "credit": [{"name": "Alabama"}], "length": 241000,
                                         "tags": [{"name": "country", "count": 40}],
                                         "releases": [{"id": "rl-1", "title": "Pass It On Down",
                                                       "date": "1993-08-01"}]}]}
        raise AssertionError(url)

    out = musicbrainz_lookup("Alabama", "Song Of The South", 241.2, fetcher=fetcher)
    assert out["matched"] and out["mbid"] == "mb-1" and out["genre"] == "country"
    assert out["year"] == 1993

    def limited(url, params=None, timeout=25.0):
        return 503, None

    with pytest.raises(ExternalError):
        musicbrainz_lookup("A", "B", None, fetcher=limited)


def test_lrclib_get_then_search_fallback() -> None:
    def fetcher(url, params=None, timeout=25.0):
        if url.endswith("/api/get"):
            return 404, None
        return 200, [{"trackName": "Talladega", "artistName": "Eric Church",
                      "duration": 265, "plainLyrics": "Cruisin' down every back road",
                      "syncedLyrics": "[00:20.00]Cruisin'", "id": 42}]

    out = lrclib_lookup("Eric Church", "Talladega", 264.0, fetcher=fetcher)
    assert out["found"] and out["lyrics"] == "Cruisin' down every back road"
    assert out["synced"] is True

    def no_plain(url, params=None, timeout=25.0):
        if url.endswith("/api/get"):
            return 200, {"plainLyrics": ""}
        return 200, []

    assert lrclib_lookup("A", "B", None, fetcher=no_plain)["reason"] == "no-plain-lyrics"


def _rec(client, *, origin=None, text=None, artist="Alabama", title="Mountain Music"):
    from app.models import MlRecording, MlSource, new_uuid

    with client.app.state.db.session() as session:
        src = MlSource(id=new_uuid(), name=f"b3-{next(_SEQ)}", status="approved")
        session.add(src)
        rec = MlRecording(id=new_uuid(), source_id=src.id, path="/x/a.mp3",
                          sha256=f"b3-{next(_SEQ)}", duration_seconds=241.0,
                          artist=artist, title=title,
                          lyrics_text=text, lyrics_origin=origin)
        session.add(rec)
        session.commit()
        return rec.id


def _run_pass(client, job_id, method, _unused=None):
    claim = claim_attempt(client.app.state.db, job_id, "w-b3")
    assert claim is not None
    _, att, lease = claim
    w = SimpleNamespace(db=client.app.state.db, storage=client.app.state.storage,
                        settings=client.app.state.settings)
    w._lease_beat = lambda *a: TrainingWorker._lease_beat(w, *a)
    w._external_pass = lambda *a, **k: TrainingWorker._external_pass(w, *a, **k)
    w._verify_one = lambda *a, **k: TrainingWorker._verify_one(w, *a, **k)
    w._lyrics_one = lambda *a, **k: TrainingWorker._lyrics_one(w, *a, **k)
    getattr(TrainingWorker, method)(w, job_id, att, lease)


def test_verify_route_and_pass(client, monkeypatch) -> None:
    rid = _rec(client)
    import app.library_external as ext

    r = client.post(f"/api/v1/admin/model-lab/recordings/{rid}/verify")
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    monkeypatch.setattr(ext, "musicbrainz_lookup", lambda *a, **k: {
        "matched": True, "mbid": "mb-9", "artist": "Alabama",
        "title": "Mountain Music", "genre": "country", "year": 1981, "source": "musicbrainz"})
    monkeypatch.setattr(ext, "lrclib_lookup", lambda *a, **k: {"found": False})
    _run_pass(client, job_id, "_model_lab_verify")

    from app.models import MlMetadataClaim, MlRecording
    with client.app.state.db.session() as session:
        rec = session.get(MlRecording, rid)
        assert rec.identify_status == "brainz:mb-9"
        assert (rec.tags_provenance_json or {}).get("mbid") == "mb-9"
        claims = session.query(MlMetadataClaim).filter(
            MlMetadataClaim.recording_id == rid).all()
        assert {c.field for c in claims} == {"genre", "year"}  # artist/title already equal
        assert all(c.status == "suggested" for c in claims)


def test_lyrics_pass_fills_and_respects_priority(client, monkeypatch) -> None:
    import app.library_external as ext

    empty = _rec(client)
    submitted = _rec(client, text="human exact", origin="submitted")
    monkeypatch.setattr(ext, "lrclib_lookup", lambda *a, **k: {
        "found": True, "lyrics": "site lyric text", "synced": False, "id": 7,
        "artist": "Alabama", "title": "Mountain Music", "source": "lrclib"})

    r = client.post("/api/v1/admin/model-lab/lyrics-fetch-selected",
                    json={"recording_ids": [empty, submitted]})
    assert r.status_code == 202
    _run_pass(client, r.json()["job_id"], "_model_lab_lyrics")

    from app.models import MlRecording
    with client.app.state.db.session() as session:
        a = session.get(MlRecording, empty)
        assert a.lyrics_origin == "site" and a.lyrics_text == "site lyric text"
        assert a.lyrics_sha256 == hashlib.sha256(b"site lyric text").hexdigest()
        b = session.get(MlRecording, submitted)
        assert b.lyrics_text == "human exact" and b.lyrics_origin == "submitted"


def test_external_network_error_is_counted(client, monkeypatch) -> None:
    import app.library_external as ext
    from app.library_external import ExternalError

    rid = _rec(client)
    monkeypatch.setattr(ext, "musicbrainz_lookup",
                        lambda *a, **k: (_ for _ in ()).throw(ExternalError("boom")))
    r = client.post(f"/api/v1/admin/model-lab/recordings/{rid}/verify")
    _run_pass(client, r.json()["job_id"], "_model_lab_verify")
    from app.models import MlRecording
    with client.app.state.db.session() as session:
        assert not session.get(MlRecording, rid).identify_status.startswith("brainz:")
