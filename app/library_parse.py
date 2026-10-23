"""Deterministic library tag/lyric parsing (local pipeline Batch 1).

Pure functions over data the scanner already collects: ffprobe ``format_tags``,
Kodi ``.nfo`` XML, folder structure, filenames and ``.lrc``/``.txt`` lyric
sidecars. No LLM, no network — every value carries explicit provenance so
external verification (MusicBrainz) and admin review can override it. Junk
heuristics are conservative: bad YouTube-ripper tags must never poison a
training caption.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path
from typing import Callable
from xml.etree import ElementTree

TAG_KEYS = ("artist", "title", "genre", "year", "album")
_JUNK_SUBSTRINGS = ("youtube.com", "freemake", "www.", "makeovervideo")
_JUNK_EXACT = {"", "unknown", "unknown artist", "unknown album", "unknown title",
               "various", "various artists", "n/a", "na", "none"}
# Windows Media Player / ripper era garbage written into TCON frames.
_JUNK_GENRE_RE = re.compile(
    r"^(mp3\s*\d*|\d+\s*k?bps(\s*(mp3|wma|aac|vbr|cbr))?|audio ?grabber|www\.?|"
    r"itn?\d*|uncredited|other\d*)$", re.I)

# Provenance priority: ffprobe/ID3 first, then Kodi nfo, then folder structure,
# then the "Artist - Title" filename convention (lowest confidence).
PROVENANCE_PRIORITY = ("id3", "album.nfo", "artist.nfo", "path", "filename")

_LRC_TIME = re.compile(r"^\[\d{1,2}:\d{2}(?:[.:]\d{1,3})?\]")
_LRC_META = re.compile(r"^\[(?:ar|ti|al|by|offset|length|ve):[^\]]*\]", re.I)


def clean_value(raw: object) -> str | None:
    """Normalize a tag value; None when empty or a known junk marker."""
    if raw is None:
        return None
    text = str(raw).strip()
    lowered = text.lower()
    if lowered in _JUNK_EXACT:
        return None
    if any(marker in lowered for marker in _JUNK_SUBSTRINGS):
        return None
    return text or None


def clean_genre(raw: object) -> str | None:
    """Genre values only: also rejects codec/bitrate garbage ('MP3 1')."""
    value = clean_value(raw)
    if value and _JUNK_GENRE_RE.match(value.strip()):
        return None
    return value


def year_from(value: object) -> int | None:
    match = re.search(r"(1[89]\d{2}|20\d{2})", str(value or ""))
    return int(match.group(1)) if match else None


def decade(year: int | None) -> str | None:
    return f"{(year // 10) * 10}s" if year else None


def read_format_tags(path: Path, ffprobe_bin: str = "ffprobe") -> dict[str, str]:
    """ID3/Vorbis-style format tags via ffprobe; {} on any failure."""
    try:
        out = subprocess.run(
            [ffprobe_bin, "-v", "error", "-show_entries", "format_tags",
             "-of", "json", str(path)],
            capture_output=True, timeout=25, check=False)
        import json as _json
        data = _json.loads(out.stdout.decode() or "{}")
        tags = (data.get("format") or {}).get("tags") or {}
        return {str(k): str(v) for k, v in tags.items() if not str(k).startswith("id3v2_priv")}
    except Exception:
        return {}


def parse_media_tags(tags: dict[str, str]) -> dict:
    """Map ffprobe format_tags onto our fields; returns values + lyrics text."""
    lowered = {k.lower(): v for k, v in tags.items()}

    def pick(*keys: str) -> str | None:
        for key in keys:
            value = clean_value(lowered.get(key))
            if value:
                return value
        return None

    return {
        "artist": pick("artist", "albumartist"),
        "title": pick("title"),
        "genre": clean_genre(lowered.get("genre")),
        "year": year_from(lowered.get("date") or lowered.get("year")),
        "album": pick("album"),
        "lyrics_embedded": lowered.get("lyrics") or lowered.get("unsynchronized lyrics"),
    }


def artist_title_from_filename(stem: str) -> tuple[str, str] | None:
    """'Artist - Title' convention; only when the separator is unambiguous."""
    core = re.sub(r"\((?:official|lyrics?|audio|video|hd|hq)[^)]*\)", "", stem, flags=re.I)
    if core.count(" - ") != 1:
        return None
    left, right = (part.strip() for part in core.split(" - ", 1))
    left, right = clean_value(left), clean_value(right)
    if left and right and len(left) > 1 and len(right) > 1:
        return left, right
    return None


def derive_artist_from_path(path: Path, marker: str = "Music Library") -> str | None:
    """By-artist folder layout: .../Music Library/<Artist>/<Album>/track.mp3."""
    parts = path.parts
    if marker not in parts:
        return None
    index = len(parts) - 1 - parts[::-1].index(marker)
    if index + 1 < len(parts) - 1:  # artist dir must not be the file's own dir
        return clean_value(parts[index + 1])
    return None


def _nfo_texts(root, tag: str) -> list[str]:
    return [node.text.strip() for node in root.iter(tag) if node.text and node.text.strip()]


def parse_nfo(nfo_path: Path) -> dict:
    """Kodi album.nfo / artist.nfo: genres, moods, styles, year (tolerant)."""
    try:
        text = nfo_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    genres: list[str] = []
    moods: list[str] = []
    styles: list[str] = []
    year: int | None = None
    try:
        root = ElementTree.fromstring(text)
        genres = _nfo_texts(root, "genre")
        moods = _nfo_texts(root, "mood")
        styles = _nfo_texts(root, "style")
        year = year_from(" ".join(_nfo_texts(root, "year") + _nfo_texts(root, "formed")))
    except ElementTree.ParseError:
        grab = lambda tag: [m.strip() for m in re.findall(rf"<{tag}>(.*?)</{tag}>", text, re.S) if m.strip()]  # noqa: E731
        genres, moods, styles = grab("genre"), grab("mood"), grab("style")
        year = year_from(" ".join(grab("year") + grab("formed")))
    genres = [g for g in (clean_genre(v) for v in genres) if g]
    return {"genres": genres, "moods": moods, "styles": styles, "year": year}


def find_lyrics_sidecar(audio_path: Path) -> dict | None:
    """<stem>.lrc preferred, then <stem>.lyrics.txt, then <stem>.txt."""
    stem = audio_path.with_suffix("")
    for suffix, kind in ((".lrc", "lrc"), (".lyrics.txt", "txt"), (".txt", "txt")):
        candidate = stem.parent / (stem.name + suffix)
        if candidate.is_file():
            raw = candidate.read_text(encoding="utf-8", errors="replace")
            if raw.strip():
                return {"kind": kind, "path": str(candidate),
                        "raw": raw, "sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest()}
    return None


def lrc_to_plain(lrc_text: str) -> str:
    """Strip LRC timestamp and [meta:] lines; keep lyric lines verbatim."""
    lines = []
    for line in lrc_text.splitlines():
        stripped = line.strip()
        if not stripped or _LRC_META.match(stripped):
            continue
        if _LRC_TIME.match(stripped):
            stripped = _LRC_TIME.sub("", stripped).strip()
        lines.append(stripped)
    return "\n".join(lines).strip()


def lyrics_training_text(sidecar: dict) -> tuple[str, bool]:
    """(training text, was-stripped) — raw bytes stay canonical on the record."""
    if sidecar["kind"] == "lrc":
        plain = lrc_to_plain(sidecar["raw"])
        return plain, plain != sidecar["raw"].strip()
    return sidecar["raw"].strip(), False


def resolve_tag_fields(*, id3: dict, album_nfo: dict, artist_nfo: dict,
                       path_artist: str | None, filename_pair: tuple | None) -> tuple[dict, dict]:
    """First non-junk value per field wins (id3 > album.nfo > artist.nfo >
    path > filename). Junk is filtered before this point by clean_value."""
    values: dict = {}
    provenance: dict = {}

    values["artist"], provenance["artist"] = _first_pairs(
        [(id3.get("artist"), "id3"),
         (path_artist, "path"),
         (filename_pair[0] if filename_pair else None, "filename")])
    values["title"], provenance["title"] = _first_pairs(
        [(id3.get("title"), "id3"),
         (filename_pair[1] if filename_pair else None, "filename")])
    values["genre"], provenance["genre"] = _first_pairs(
        [(id3.get("genre"), "id3"),
         (album_nfo.get("genres", [None])[0] if album_nfo.get("genres") else None, "album.nfo"),
         (artist_nfo.get("genres", [None])[0] if artist_nfo.get("genres") else None, "artist.nfo")])
    values["year"], provenance["year"] = _first_pairs(
        [(id3.get("year"), "id3"), (album_nfo.get("year"), "album.nfo"),
         (artist_nfo.get("year"), "artist.nfo")])
    values["album"], provenance["album"] = _first_pairs(
        [(id3.get("album"), "id3"), (album_nfo.get("album"), "album.nfo")])
    styles = (album_nfo.get("styles") or []) + (artist_nfo.get("styles") or [])
    moods = (album_nfo.get("moods") or []) + (artist_nfo.get("moods") or [])
    if styles:
        provenance["styles"] = "nfo"
    if moods:
        provenance["moods"] = "nfo"
    values["styles"] = [clean_value(s) for s in styles if clean_value(s)]
    values["moods"] = [clean_value(m) for m in moods if clean_value(m)]
    return values, {k: v for k, v in provenance.items() if v}


def _first_pairs(pairs):
    for value, source in pairs:
        if value:
            return value, source
    return None, None


def decide_tags_state(values: dict, provenance: dict) -> str:
    """parsed = trusted sources cover artist+title; suspect = fallbacks/junk;
    invalid = neither present at all."""
    artist_src = provenance.get("artist")
    title_src = provenance.get("title")
    if not values.get("artist") and not values.get("title"):
        return "invalid"
    weak = {None, "path", "filename"}
    if artist_src in weak or title_src in weak or not artist_src or not title_src:
        return "suspect"
    return "parsed"


def enrich_recording(rec, path: Path, *, tags_reader: Callable[[Path], dict] | None = None,
                     sidecar_finder: Callable[[Path], dict | None] | None = None) -> str:
    """Apply parsed tags + sidecar lyrics to an MlRecording (caller commits).

    Never overwrites values that are already set (submitted/locked data wins);
    fills empties from deterministic sources with provenance. Returns tags_state.
    """
    reader = tags_reader or read_format_tags
    finder = sidecar_finder or find_lyrics_sidecar

    id3 = parse_media_tags(reader(path))
    album_nfo = parse_nfo(path.parent / "album.nfo")
    artist_nfo = parse_nfo(path.parent.parent / "artist.nfo") if path.parent.parent else {}
    filename_pair = artist_title_from_filename(path.stem)
    values, provenance = resolve_tag_fields(
        id3=id3, album_nfo=album_nfo, artist_nfo=artist_nfo,
        path_artist=derive_artist_from_path(path), filename_pair=filename_pair)

    if values.get("artist") and not rec.artist:
        rec.artist = values["artist"]
    if values.get("title") and not rec.title:
        rec.title = values["title"]
    if values.get("genre") and not rec.genre_raw:
        rec.genre_raw = values["genre"]
    if values.get("year") and not rec.year:
        rec.year = values["year"]
        rec.decade = decade(values["year"])

    state = decide_tags_state(
        {"artist": rec.artist, "title": rec.title},
        dict(provenance))
    prov = provenance
    rec.tags_state = state
    rec.tags_provenance_json = prov

    if not rec.lyrics_text:
        embedded = clean_value(id3.get("lyrics_embedded") or "")
        sidecar = finder(path)
        if sidecar:
            rec.lyrics_text = sidecar["raw"]
            rec.lyrics_sha256 = sidecar["sha256"]
            rec.lyrics_origin = "sidecar"
            training, stripped = lyrics_training_text(sidecar)
            rec.lyrics_provenance_json = {"kind": sidecar["kind"], "path": sidecar["path"],
                                          "stripped_for_training": stripped,
                                          "training_sha256": hashlib.sha256(
                                              training.encode("utf-8")).hexdigest()}
        elif embedded:
            rec.lyrics_text = str(id3.get("lyrics_embedded")).strip()
            rec.lyrics_sha256 = hashlib.sha256(rec.lyrics_text.encode("utf-8")).hexdigest()
            rec.lyrics_origin = "id3"
            rec.lyrics_provenance_json = {"kind": "id3-LYRICS"}

    prov["styles"] = values.get("styles") or []
    prov["moods"] = values.get("moods") or []
    rec.tags_provenance_json = prov

    if state == "suspect":
        rec.review_required = True
    try:
        from .style_tags import apply_style_tags
        apply_style_tags(rec)
    except (OSError, ValueError):  # taxonomy asset unavailable (e.g. old bundle)
        pass
    return state
