#!/usr/bin/env python3
"""Select the house-LoRA union dataset: decade x genre category picks plus
featured-artist picks. Outputs curation/selection.jsonl + selection.md."""
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

CUR = Path("/Cold-Archive/OpenAudioLab/curation")
EXCLUDE_ARTISTS = {"Library", "Various Artists", "Various", "Unknown", "Soundtrack"}
COMP_RE = re.compile(r"now that's|greatest|best of|best-of|collection|compilation|\bhits?\b|gold|platinum|superstars|duets", re.I)

GENRE_MAP = [
    ("metal", ["metal", "thrash", "grindcore", "death", "black metal", "doom"]),
    ("punk", ["punk", "new wave", "newwave", "ska", "power pop", "goth", "post-punk"]),
    ("hiphop", ["rap", "hip-hop", "hip hop", "hiphop", "crunk"]),
    ("rnb_soul", ["r&b", "rnb", "r & b", "soul", "funk", "gospel", "motown", "doo wop"]),
    ("country", ["country", "bluegrass", "americana", "nashville"]),
    ("dance", ["dance", "electronic", "techno", "house", "industrial", "disco", "eurodance", "trance", "synth"]),
    ("jazz", ["jazz", "swing", "big band", "bebop", "bossa", "lounge"]),
    ("blues", ["blues"]),
    ("folk", ["folk", "singer-songwriter", "celtic", "irish"]),
    ("classical", ["classical", "orchestral", "opera", "symphony", "choral", "instrumental", "soundtrack", "film", "score"]),
    ("pop", ["pop", "top 40", "oldies", "vocal", "teen", "adult contemporary", "soft rock"]),
    ("rock", ["rock", "alternative", "alt", "indie", "grunge", "britpop", "psychedelic", "progressive", "jam"]),
]
CATEGORIES = ["rock", "pop", "country", "hiphop", "rnb_soul", "dance", "metal", "punk", "jazz", "blues", "folk", "classical"]
DECADES = ["1970s", "1980s", "1990s", "2000s", "2010s"]
FEATURED = [
    "Green Day", "Eminem", "Nine Inch Nails", "Tim McGraw", "Garth Brooks",
    "George Strait", "The Rolling Stones", "The Beatles", "Elvis Presley",
    "Queen", "Metallica", "Depeche Mode", "The Cure", "Foo Fighters",
    "Linkin Park", "Red Hot Chili Peppers", "Bruce Springsteen", "Nelly",
    "Jimmy Buffett", "NOFX", "Dolly Parton", "Johnny Cash",
]
PER_CATEGORY = 25
PER_ARTIST_CAP = 4
PER_FEATURED = 20
MIN_ARTIST_TRACKS = 10
MIN_CELL_CANDIDATES = 25
MIN_CELL_ARTISTS = 5
MAX_CELLS = 40


def norm_genre(g):
    if not g:
        return None
    s = g.lower()
    for cat, keys in GENRE_MAP:
        for k in keys:
            if k in s:
                return cat
    return None


def main():
    tracks = [json.loads(l) for l in (CUR / "tracks.jsonl").open()]
    artist_tracks = Counter(t["artist"] for t in tracks)
    ok = [t for t in tracks
          if t["artist"] not in EXCLUDE_ARTISTS
          and artist_tracks[t["artist"]] >= MIN_ARTIST_TRACKS
          and t["decade"] in DECADES
          and norm_genre(t["genre"])
          and 2_500_000 <= t["size"] <= 25_000_000
          and not COMP_RE.search(t["album"])]
    for t in ok:
        t["cat"] = norm_genre(t["genre"])

    cells = defaultdict(list)
    for t in ok:
        cells[(t["decade"], t["cat"])].append(t)
    qualified = []
    for key, ts in cells.items():
        artists = {t["artist"] for t in ts}
        if len(ts) >= MIN_CELL_CANDIDATES and len(artists) >= MIN_CELL_ARTISTS:
            qualified.append((key, ts))
    qualified.sort(key=lambda kv: -len(kv[1]))
    chosen_cells = qualified[:MAX_CELLS]

    picked = {}
    def pick(t, why):
        if t["path"] not in picked:
            picked[t["path"]] = (t, why)

    cell_report = []
    for (decade, cat), ts in chosen_cells:
        ts.sort(key=lambda t: (-artist_tracks[t["artist"]], -t["size"]))
        per_artist = Counter()
        n = 0
        for t in ts:
            if per_artist[t["artist"]] >= PER_ARTIST_CAP or n >= PER_CATEGORY:
                continue
            per_artist[t["artist"]] += 1
            n += 1
            pick(t, f"category:{decade}-{cat}")
        cell_report.append((decade, cat, len(ts), n))

    feat_report = []
    for artist in FEATURED:
        ts = [t for t in ok if t["artist"] == artist]
        ts.sort(key=lambda t: -t["size"])
        n = 0
        for t in ts[:PER_FEATURED]:
            n += 1
            pick(t, f"featured:{artist}")
        feat_report.append((artist, len(ts), n))

    with (CUR / "selection.jsonl").open("w") as out:
        for path, (t, why) in picked.items():
            out.write(json.dumps({**t, "pick_reason": why}, ensure_ascii=False) + "\n")

    lines = [f"# House LoRA selection — {len(picked)} tracks", "",
             f"## Categories ({len(chosen_cells)} cells)",
             "| decade | genre | candidates | picked |", "|--|--|--|--|"]
    for decade, cat, cand, n in sorted(cell_report):
        lines.append(f"| {decade} | {cat} | {cand} | {n} |")
    lines += ["", "## Featured artists", "| artist | tracks in lib | picked |", "|--|--|--|"]
    for artist, total, n in feat_report:
        lines.append(f"| {artist} | {total} | {n} |")
    lines += ["", f"Total union: **{len(picked)}** tracks, "
              f"{len({t['artist'] for t, _ in picked.values()})} artists, "
              f"~{sum(t['size'] for t, _ in picked.values())/1e9:.1f} GB"]
    (CUR / "selection.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[-8:]))


if __name__ == "__main__":
    main()
