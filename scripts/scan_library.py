#!/usr/bin/env python3
"""Curation scan: walk the TrueNAS music library, index every track with
artist/album/genre/decade from Kodi .nfo files, ID3 tags, and path structure.

Output: curation/tracks.jsonl (one line per track) + coverage summary.
"""
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

ROOT = Path("/mnt/truenas/Media Library/Music/Music Library")
OUT_DIR = Path("/Cold-Archive/OpenAudioLab/curation")
AUDIO_EXT = {".mp3", ".flac", ".m4a", ".wav", ".ogg", ".wma"}
SKIP_DIRS = {".ipynb_checkpoints", ".Trash-1000", "SFX Folder"}


def nfo_text(root, tag):
    el = root.find(tag)
    return (el.text or "").strip() if el is not None and el.text else ""


def nfo_all(root, tag):
    return [(e.text or "").strip() for e in root.iter(tag)
            if e is not None and e.text and e.text.strip()]


def parse_nfo(path):
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
        raw = re.sub(r"^\s*<\?xml.*?\?>", "", raw, count=1).strip()
        root = ET.fromstring(raw)
        return root
    except Exception:
        return None


def id3_year_genre(path):
    try:
        from mutagen.id3 import ID3
        try:
            tags = ID3(str(path))
        except Exception:
            return None, None
        year = None
        for key in ("TDRC", "TDRL", "TORY", "TYER"):
            v = tags.get(key)
            if v:
                m = re.search(r"(1[89]\d{2}|20\d{2})", str(v))
                if m:
                    year = int(m.group(1))
                    break
        genre = None
        g = tags.get("TCON")
        if g:
            s = str(g).strip()
            s = re.sub(r"^\(\d+\)", "", s).strip()
            if s and s.lower() not in ("other", "unknown", "miscellaneous sound track"):
                genre = s
        return year, genre
    except Exception:
        return None, None


def year_from(text):
    m = re.search(r"(1[89]\d{2}|20\d{2})", text or "")
    return int(m.group(1)) if m else None


def decade(year):
    return f"{(year // 10) * 10}s" if year else None


def clean_title(fname):
    stem = Path(fname).stem
    stem = re.sub(r"^\s*\d{1,2}[\s._-]+", "", stem)
    stem = re.sub(r"\s*\(.*?\)|\s*\[.*?\]", "", stem).strip()
    return stem or Path(fname).stem


def audio_files(d):
    try:
        return sorted(p for p in d.iterdir()
                      if p.is_file() and p.suffix.lower() in AUDIO_EXT)
    except PermissionError:
        return []


def album_dirs(artist_dir):
    """Album dirs = subdirs containing audio, or their subdirs (disc splits)."""
    out = []
    try:
        subs = [p for p in artist_dir.iterdir() if p.is_dir() and not p.name.startswith(".")]
    except PermissionError:
        return out
    for s in subs:
        if s.name in SKIP_DIRS:
            continue
        if audio_files(s):
            out.append((s.name, [s]))
        else:
            deeper = [q for q in s.iterdir() if q.is_dir() and audio_files(q)]
            if deeper:
                out.append((s.name, deeper))
    return out


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "tracks.jsonl"
    artists = sorted(p for p in ROOT.iterdir() if p.is_dir() and not p.name.startswith("."))
    stats = Counter()
    genre_src = Counter()
    year_src = Counter()
    n_artists = 0
    with out_path.open("w", encoding="utf-8") as out:
        for ai, adir in enumerate(artists):
            artist = adir.name
            a_genre, a_moods, a_styles, a_formed = [], [], [], None
            nfo = adir / "artist.nfo"
            if nfo.is_file():
                root = parse_nfo(nfo)
                if root is not None:
                    a_genre = nfo_all(root, "genre")
                    a_moods = nfo_all(root, "mood")
                    a_styles = nfo_all(root, "style")
                    a_formed = year_from(nfo_text(root, "formed") or nfo_text(root, "yearsactive"))
            n_artists += 1
            for album_name, dirs in album_dirs(adir):
                al_genre, al_year = [], None
                for d in dirs:
                    anfo = d / "album.nfo"
                    if anfo.is_file():
                        root = parse_nfo(anfo)
                        if root is not None:
                            al_genre += nfo_all(root, "genre")
                            al_year = al_year or year_from(
                                nfo_text(root, "releasedate") or nfo_text(root, "premiered")
                                or nfo_text(root, "originalDate")
                                or nfo_text(root, "date") or nfo_text(root, "year"))
                tracks = []
                for d in dirs:
                    tracks += audio_files(d)
                if not tracks:
                    continue
                stats["albums"] += 1
                id3_done = False
                for t in tracks:
                    year, genre = al_year, (al_genre[0] if al_genre else None)
                    g_src = "album.nfo" if genre else None
                    y_src = "album.nfo" if year else None
                    if (genre is None or year is None) and not id3_done:
                        id3_done = True
                        iy, ig = id3_year_genre(tracks[0])
                        if year is None and iy:
                            year, y_src = iy, "id3"
                        if genre is None and ig:
                            genre, g_src = ig, "id3"
                    if genre is None and a_genre:
                        genre, g_src = a_genre[0], "artist.nfo"
                    if year is None and a_formed:
                        year, y_src = a_formed, "artist.nfo"
                    genre_src[g_src or "none"] += 1
                    year_src[y_src or "none"] += 1
                    stats["tracks"] += 1
                    if genre:
                        stats["with_genre"] += 1
                    if year:
                        stats["with_year"] += 1
                    out.write(json.dumps({
                        "artist": artist, "album": album_name,
                        "title": clean_title(t.name), "path": str(t),
                        "size": t.stat().st_size,
                        "genre": genre, "genre_src": g_src,
                        "year": year, "year_src": y_src,
                        "decade": decade(year),
                        "artist_genres": a_genre[:3], "moods": a_moods[:3],
                        "styles": a_styles[:3],
                    }, ensure_ascii=False) + "\n")
            if (ai + 1) % 250 == 0:
                print(f"{ai+1}/{len(artists)} artists, {stats['tracks']} tracks", flush=True)
    total = stats["tracks"] or 1
    lines = [
        f"artists={n_artists} albums={stats['albums']} tracks={stats['tracks']}",
        f"genre coverage: {stats['with_genre']} ({100*stats['with_genre']/total:.1f}%)  src={dict(genre_src)}",
        f"year coverage:  {stats['with_year']} ({100*stats['with_year']/total:.1f}%)  src={dict(year_src)}",
    ]
    (OUT_DIR / "scan_summary.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    sys.exit(main())
