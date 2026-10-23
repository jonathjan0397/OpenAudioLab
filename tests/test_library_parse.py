"""Batch 1: deterministic tag/lyric parsing + scan wiring."""

from __future__ import annotations

import hashlib

from app.library_parse import (artist_title_from_filename, clean_value,
                               decide_tags_state, derive_artist_from_path,
                               enrich_recording, find_lyrics_sidecar,
                               lrc_to_plain, parse_nfo, resolve_tag_fields)

_SEQ = iter(range(1, 10000))


def test_clean_value_junk_heuristics() -> None:
    assert clean_value("www.youtube.com") is None
    assert clean_value("freemake.com") is None
    assert clean_value("Unknown Artist") is None
    assert clean_value("  ") is None
    assert clean_value("Alabama") == "Alabama"


def test_artist_title_from_filename() -> None:
    assert artist_title_from_filename("Alabama - Mountain Music") == ("Alabama", "Mountain Music")
    assert artist_title_from_filename("Old Dominion  - Break Up With Him") == \
        ("Old Dominion", "Break Up With Him")
    assert artist_title_from_filename("Strip It Down") is None
    assert artist_title_from_filename("A - B - C") is None  # ambiguous separator
    assert artist_title_from_filename("Song (Official Lyric Video)") is None
    assert artist_title_from_filename("Alabama - Song (Official Video)") == \
        ("Alabama", "Song")  # parenthetical stripped before count


def test_derive_artist_from_path() -> None:
    p = "/mnt/truenas/Media Library/Music/Music Library/Alabama/Pass It On Down/10 Gulf.mp3"
    assert derive_artist_from_path(__import__("pathlib").Path(p)) == "Alabama"
    assert derive_artist_from_path(__import__("pathlib").Path("/x/y/z.mp3")) is None


def test_parse_nfo_valid_and_malformed(tmp_path) -> None:
    nfo = tmp_path / "album.nfo"
    nfo.write_text('<?xml version="1.0"?><album><genre>Country</genre>'
                   '<mood>Rowdy</mood><year>1993</year></album>', encoding="utf-8")
    parsed = parse_nfo(nfo)
    assert parsed["genres"] == ["Country"] and parsed["year"] == 1993
    bad = tmp_path / "bad.nfo"
    bad.write_text("<album><genre>Country</genre><unclosed>", encoding="utf-8")
    assert parse_nfo(bad)["genres"] == ["Country"]  # regex fallback
    assert parse_nfo(tmp_path / "missing.nfo") == {}


def test_lrc_to_plain_strips_meta_and_timestamps() -> None:
    lrc = "[ar:Alabama]\n[ti:Song]\n[00:30.10]First line\n[00:33.20]Second line\nlast"
    assert lrc_to_plain(lrc) == "First line\nSecond line\nlast"


def test_find_lyrics_sidecar_prefers_lrc(tmp_path) -> None:
    (tmp_path / "song.mp3").write_bytes(b"audio")
    (tmp_path / "song.lrc").write_text("[00:01.00]la la", encoding="utf-8")
    (tmp_path / "song.txt").write_text("notes notes", encoding="utf-8")
    hit = find_lyrics_sidecar(tmp_path / "song.mp3")
    assert hit["kind"] == "lrc" and hit["sha256"] == hashlib.sha256(
        "[00:01.00]la la".encode()).hexdigest()
    (tmp_path / "song.lrc").unlink(); (tmp_path / "song.txt").unlink()
    assert find_lyrics_sidecar(tmp_path / "song.mp3") is None


def test_resolve_priority_and_state() -> None:
    values, prov = resolve_tag_fields(
        id3={"artist": "Alabama", "title": "Song Of The South", "genre": None,
             "year": 1993, "album": "Pass It On Down"},
        album_nfo={"genres": ["Country"], "moods": [], "styles": [], "year": None},
        artist_nfo={}, path_artist="Alabama",
        filename_pair=("Alabama", "Song Of The South"))
    assert values["artist"] == "Alabama" and prov["artist"] == "id3"
    assert values["genre"] == "Country" and prov["genre"] == "album.nfo"
    assert decide_tags_state({"artist": values["artist"], "title": values["title"]}, prov) \
        == "parsed"
    # filename/path-only identity stays suspect; missing both is invalid
    v2, p2 = resolve_tag_fields(id3={}, album_nfo={}, artist_nfo={},
                                path_artist="Alabama",
                                filename_pair=("Alabama", "Mountain Music"))
    assert decide_tags_state({"artist": v2["artist"], "title": v2["title"]}, p2) == "suspect"
    v3, p3 = resolve_tag_fields(id3={}, album_nfo={}, artist_nfo={},
                                path_artist=None, filename_pair=None)
    assert decide_tags_state({"artist": v3["artist"], "title": v3["title"]}, p3) == "invalid"


def _rec():
    from app.models import MlRecording, new_uuid

    return MlRecording(id=new_uuid(), source_id="s1", path="/x/a.mp3", sha256="a" * 64,
                       bytes=1)


def test_enrich_recording_trusted_id3(tmp_path) -> None:
    audio = tmp_path / "Alabama - Mountain Music.mp3"
    audio.write_bytes(b"audio")
    rec = _rec()
    state = enrich_recording(
        rec, audio,
        tags_reader=lambda p: {"artist": "Alabama", "title": "Mountain Music",
                               "genre": "Country", "date": "1981", "album": "Feelin Is"},
        sidecar_finder=lambda p: None)
    assert state == "parsed"
    assert rec.artist == "Alabama" and rec.genre_raw == "Country"
    assert rec.year == 1981 and rec.decade == "1980s"
    assert rec.tags_provenance_json["title"] == "id3"
    assert not rec.review_required


def test_enrich_recording_junk_id3_falls_back_and_grabs_sidecar(tmp_path) -> None:
    artist_dir = tmp_path / "Music Library" / "Eric Church" / "Album"
    artist_dir.mkdir(parents=True)
    audio = artist_dir / "Eric Church - Talladega.mp3"
    audio.write_bytes(b"x")
    lrc = artist_dir / "Eric Church - Talladega.lrc"
    lrc.write_text("[ar:Eric Church]\n[01:02.00]Cruisin' down every back road", encoding="utf-8")
    rec = _rec()
    state = enrich_recording(
        rec, audio,
        tags_reader=lambda p: {"artist": "www.youtube.com", "title": "Eric Church - Talladega"},
        sidecar_finder=None)  # default real finder used below via file
    # junk id3 artist dropped; title from id3, artist from path/filename
    assert rec.artist == "Eric Church"
    assert state in ("parsed", "suspect")
    assert rec.lyrics_text and rec.lyrics_origin == "sidecar"
    assert rec.lyrics_sha256 == hashlib.sha256(lrc.read_text().encode()).hexdigest()
    assert rec.lyrics_provenance_json["kind"] == "lrc"
    assert rec.lyrics_provenance_json["stripped_for_training"] is True


def test_enrich_never_overwrites_existing_fields(tmp_path) -> None:
    audio = tmp_path / "song.mp3"
    audio.write_bytes(b"x")
    rec = _rec()
    rec.artist = "Submitted Artist"; rec.title = "Submitted Title"
    rec.lyrics_text = "exact human lyrics"; rec.lyrics_sha256 = "deadbeef"
    rec.lyrics_origin = "submitted"
    enrich_recording(rec, audio,
                     tags_reader=lambda p: {"artist": "Alabama", "title": "Other"},
                     sidecar_finder=lambda p: {"kind": "txt", "path": "x", "raw": "y",
                                               "sha256": "z"})
    assert rec.artist == "Submitted Artist" and rec.lyrics_text == "exact human lyrics"
    assert rec.lyrics_origin == "submitted"


def test_scan_source_wiring_via_client(client, monkeypatch) -> None:
    import json
    from pathlib import Path

    monkeypatch.setattr("app.library_parse.quick_decode_ok", lambda p, **k: True)
    from app.model_lab import scan_source
    from app.models import MlRecording, MlSource, new_uuid
    from sqlalchemy import select

    root = Path(client.app.state.settings.storage_dir) / "libroot"
    album = root / "Music Library" / "Alabama" / "Feels So Good"
    album.mkdir(parents=True, exist_ok=True)
    audio = album / "Alabama - Mountain Music.mp3"
    audio.write_bytes(b"not-really-audio")
    (album / "Alabama - Mountain Music.lrc").write_text(
        "[00:04.00]mountain music playing", encoding="utf-8")
    (album / "album.nfo").write_text("<album><genre>Country</genre><year>1981</year></album>",
                                     encoding="utf-8")
    manifest = root / "m.jsonl"
    manifest.write_text(json.dumps({"path": str(audio)}) + "\n", encoding="utf-8")
    with client.app.state.db.session() as session:
        src = MlSource(id=new_uuid(), name=f"lib-{next(_SEQ)}", kind="manifest",
                       path=str(manifest), status="approved")
        session.add(src)
        session.commit()
        result = scan_source(session, src, preview=False)
        assert result["counts"]["new"] == 1
        rec = session.execute(select(MlRecording)
                              .where(MlRecording.source_id == src.id)).scalars().one()
        assert rec.artist == "Alabama"
        assert rec.tags_state in ("parsed", "suspect")
        assert rec.lyrics_origin == "sidecar" and rec.lyrics_text
        assert rec.tags_provenance_json.get("genre") == "album.nfo"


def test_clean_genre_rejects_codec_bitrate_garbage() -> None:
    from app.library_parse import clean_genre

    for junk in ("MP3 1", "MP3 2", "mp3", "128kbps", "192 Kbps MP3", "Audio Grabber",
                 "Uncredited", "other5", "www"):
        assert clean_genre(junk) is None, junk
    for good in ("Country", "Rock", "Rap & Hip Hop", "Pop", "Metal 1"):
        assert clean_genre(good) == good, good


def test_parse_media_tags_drops_junk_genre() -> None:
    from app.library_parse import parse_media_tags

    out = parse_media_tags({"artist": "2Pac", "title": "Word Is Bond", "genre": "MP3 1"})
    assert out["genre"] is None and out["artist"] == "2Pac"


def test_nfo_junk_genre_filtered(tmp_path) -> None:
    from app.library_parse import parse_nfo
    nfo = tmp_path / "album.nfo"
    nfo.write_text("<album><genre>MP3 1</genre><genre>Country</genre></album>", encoding="utf-8")
    assert parse_nfo(nfo)["genres"] == ["Country"]


def test_caption_excludes_junk_genre_even_on_stored_rows() -> None:
    from types import SimpleNamespace
    from app.model_lab import deterministic_caption

    rec = SimpleNamespace(artist="311", title="Galaxy", genre_raw="MP3 1")
    assert deterministic_caption(rec, "/x/Galaxy.mp3") == "311 - Galaxy"


def test_scan_flags_undecodable_sources(client, tmp_path, monkeypatch) -> None:
    import json

    import app.model_lab as ml
    from app.models import MlSource, new_uuid

    good = tmp_path / "good.mp3"
    good.write_bytes(b"fake-audio")
    bad = tmp_path / "bad.mp3"
    bad.write_bytes(b"fake-audio-bad")
    (tmp_path / "m.jsonl").write_text(
        json.dumps({"path": str(good)}) + "\n" + json.dumps({"path": str(bad)}))
    monkeypatch.setattr(ml, "probe_file", lambda p, **k: {"duration_seconds": 200.0})
    monkeypatch.setattr("app.library_parse.read_format_tags",
                        lambda p: {"artist": "A", "title": p.stem})
    monkeypatch.setattr("app.library_parse.quick_decode_ok",
                        lambda p, **k: p.name != "bad.mp3")
    with client.app.state.db.session() as session:
        src = MlSource(id=new_uuid(), name=f"qc-{next(_SEQ)}", kind="manifest",
                       path=str(tmp_path / "m.jsonl"), status="approved")
        session.add(src)
        session.commit()
        ml.scan_source(session, src, preview=False)
        from app.models import MlRecording
        from sqlalchemy import select
        rows = {r.path: r for r in session.execute(
            select(MlRecording).where(MlRecording.source_id == src.id)).scalars()}
    assert rows[str(bad)].tags_state == "invalid" and rows[str(bad)].review_required
    assert rows[str(good)].tags_state != "invalid"
