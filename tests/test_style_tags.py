"""Style taxonomy: derivation, restyle, coverage, and tag-driven datasets."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

_SEQ = iter(range(1, 10000))


@pytest.fixture(autouse=True)
def _admin_session(client):
    from app.models import User

    client.post("/api/v1/auth/logout")
    resp = client.post("/api/v1/auth/register",
                       json={"email": f"st{next(_SEQ)}@example.com",
                             "username": f"st{next(_SEQ)}", "password": "super-secret-1"})
    with client.app.state.db.session() as session:
        session.get(User, resp.json()["user"]["id"]).role = "admin"
        session.commit()


def _make(client, *, artist="Some Band", title="Song", genre="Rock", decade="1990s",
          bytes_=8_000_000, review="unreviewed"):
    from app.models import MlRecording, MlSource, new_uuid

    with client.app.state.db.session() as session:
        src = MlSource(id=new_uuid(), name=f"st-s{next(_SEQ)}", status="approved")
        session.add(src)
        session.commit()
        rec = MlRecording(id=new_uuid(), source_id=src.id, path=f"/x/{next(_SEQ)}.mp3",
                          sha256=f"st-{next(_SEQ)}", bytes=bytes_, duration_seconds=200.0,
                          artist=artist, title=title, genre_raw=genre,
                          decade=decade, review_status=review, tags_state="parsed")
        session.add(rec)
        session.commit()
        return rec.id


def test_derive_compounds_and_junk() -> None:
    from app.style_tags import derive_tags

    d = lambda g: derive_tags(SimpleNamespace(genre_raw=g, tags_provenance_json={}))
    assert d("R&B")["families"] == ["rnb_soul"]
    assert "pop" in d("Rock/Pop")["families"] and "rock" in d("Rock/Pop")["families"]
    assert d("MP3 1")["junk"] is True
    assert d("Hard Rock")["subgenres"] == ["rock.hard-rock"]
    r = d("Blaarg & Metal")
    assert r["unknown_parts"] == ["blaarg"] and r["families"] == ["metal"]
    assert d("Blaarg")["unknown_parts"] == ["blaarg"] and not d("Blaarg")["families"]


def test_enrich_persists_nfo_styles_and_tags(tmp_path, monkeypatch) -> None:
    from app.library_parse import enrich_recording
    from app.models import MlRecording, new_uuid

    album = tmp_path / "Some Band" / "Album"
    album.mkdir(parents=True)
    (album / "album.nfo").write_text("<album><style>anthemic</style><mood>triumphant</mood>"
                                     "<genre>Heavy Metal</genre></album>", encoding="utf-8")
    audio = album / "track.mp3"
    audio.write_bytes(b"x")
    rec = MlRecording(id=new_uuid(), source_id="s", path=str(audio), sha256="a", bytes=1)
    monkeypatch.setattr("app.library_parse.read_format_tags",
                        lambda p: {"artist": "Some Band", "title": "Track"})
    enrich_recording(rec, audio, tags_reader=lambda p: {}, sidecar_finder=lambda p: None)
    prov = rec.tags_provenance_json
    assert prov.get("styles") == ["anthemic"] and prov.get("moods") == ["triumphant"]
    assert "metal.heavy-metal" in rec.families_json  # from nfo genre via style passthrough


def test_caption_leads_with_taxonomy_phrase() -> None:
    from app.model_lab import deterministic_caption

    rec = SimpleNamespace(artist="Alabama", title="Song", genre_raw="Hard Rock",
                          year=None, decade="1990s", families_json=["rock.hard-rock"])
    cap = deterministic_caption(rec, "/x/a.mp3")
    assert cap.startswith("hard rock, heavy riff-driven guitars")


def test_restyle_route_tags_all_recordings(client) -> None:
    ids = [_make(client, genre="Gothic Rock"), _make(client, genre="Bluegrass"),
           _make(client, genre="Blaarg")]
    r = client.post("/api/v1/admin/model-lab/restyle")
    assert r.status_code == 200 and r.json()["total"] >= 3
    from app.models import MlRecording
    with client.app.state.db.session() as session:
        fams = {i: session.get(MlRecording, i).families_json for i in ids}
    assert "alt.gothic-rock" in fams[ids[0]]
    assert "country.bluegrass" in fams[ids[1]]
    assert not any("." in t for t in fams[ids[2]])  # unknown stays subgenre-free


def test_style_coverage_route(client) -> None:
    for _ in range(4):
        _make(client, genre="Country")
    client.post("/api/v1/admin/model-lab/restyle")
    cov = client.get("/api/v1/admin/model-lab/style-coverage").json()
    key = "fam:country" if "fam:country" in cov["tags"] else "country.country"
    assert cov["tags"][key]["total"] >= 4
    assert cov["tags"][key]["trainable"] == 0  # unreviewed, no rights


def test_style_dataset_build_approve_rights_freeze(client) -> None:
    ids = [_make(client, genre="Country", decade=dec, title=f"T{i}",
                 artist=f"Artist {i % 3}")
           for i, dec in enumerate(["1980s", "1990s", "2000s", "1980s", "1990s",
                                    "2000s", "1980s", "1990s", "2000s", "1980s",
                                    "1990s", "2000s"])]
    client.post("/api/v1/admin/model-lab/restyle")
    r = client.post("/api/v1/admin/model-lab/datasets",
                    json={"name": f"sds-{next(_SEQ)}", "kind": "style", "style_tag": "country",
                          "target": 9, "floor": 3,
                          "declare_rights_for_selection": True, "approve_selection": True})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["recording_count"] == 9
    from app.models import MlDataset, MlRecording, MlRightsRecord
    with client.app.state.db.session() as session:
        entries = session.get(MlDataset, body["id"]).manifest_json["entries"]
        assert all("modern country, telecaster twang" in e["caption"] for e in entries)
        chosen = {e["path"] for e in entries}
        picked_ids = [i for i in ids if session.get(MlRecording, i).path in chosen]
        assert len(picked_ids) == 9
        assert all(session.get(MlRecording, i).review_status == "approved" for i in picked_ids)
        assert session.query(MlRightsRecord).filter(
            MlRightsRecord.purpose == "house-training").count() >= 18  # 2 scopes each
    thin = client.post("/api/v1/admin/model-lab/datasets",
                       json={"name": f"thin-{next(_SEQ)}", "style_tag": "jazz.bebop",
                             "floor": 50, "declare_rights_for_selection": True,
                             "approve_selection": True})
    assert thin.status_code == 422 and thin.json()["error"]["code"] == "STYLE_TAG_THIN"


def test_select_respects_artist_cap_and_decades(client) -> None:
    from app.models import MlRecording
    from app.style_tags import select_for_style_tag, apply_style_tags

    ids = [_make(client, genre="House", artist="Same Artist") for _ in range(30)]
    with client.app.state.db.session() as session:
        for i in ids:
            apply_style_tags(session.get(MlRecording, i))
        session.commit()
        picked = select_for_style_tag(session, "electronic.house", target=20, floor=5)
    assert len(picked) == 20  # single artist: cap ladder relaxes until target is met
