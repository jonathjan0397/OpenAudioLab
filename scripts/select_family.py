#!/usr/bin/env python3
"""Per-family house-LoRA selector (lean ~200/family).

Usage: select_family.py <family> [target]

Normalizes the messy genre strings into 13 families, then picks ~target tracks
for one family with decade round-robin balancing, a per-artist cap, and dedupe.
Writes curation/selection_perfamily/<family>.jsonl and <family>_dataset.json in
the exact format the preprocess runner expects.
"""
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

CUR = Path("/Cold-Archive/OpenAudioLab/curation")
SEL = CUR / "selection_perfamily"

# 13 families, first-match-wins (specific -> general). Gospel separate from
# R&B/Soul; Score separate from generic classical; Punk/Alt separate from Rock.
FAMILY_MAP = [
    ("gospel",     ["gospel", "christian", "worship", "hymn", "spiritual", "ccm"]),
    ("metal",      ["metal", "thrash", "grindcore", "death metal", "black metal", "doom", "metalcore", "hardcore metal"]),
    ("punk_alt",   ["punk", "hardcore", "new wave", "newwave", "ska", "post-punk", "goth", "alternative", "alt-", " alt", "indie", "grunge", "britpop", "college rock"]),
    ("hiphop",     ["rap", "hip-hop", "hip hop", "hiphop", "crunk", "trap"]),
    ("rnb_soul",   ["r&b", "rnb", "r & b", "soul", "funk", "motown", "doo wop", "neo soul"]),
    ("country",    ["country", "bluegrass", "americana", "nashville", "western swing"]),
    ("folk",       ["folk", "singer-songwriter", "celtic", "irish", "acoustic"]),
    ("jazz",       ["jazz", "swing", "big band", "bebop", "bossa", "lounge"]),
    ("blues",      ["blues"]),
    ("electronic", ["dance", "electronic", "techno", "house", "industrial", "disco", "eurodance", "trance", "synth", "edm", "ambient", "dubstep"]),
    ("score",      ["classical", "orchestral", "opera", "symphony", "choral", "soundtrack", "film score", "score", "concerto", "sonata", "chamber"]),
    ("pop",        ["pop", "top 40", "oldies", "vocal", "teen", "adult contemporary", "soft rock"]),
    ("rock",       ["rock", "classic rock", "hard rock", "progressive", "psychedelic", "jam", "album rock", "aor"]),
]
FAMILIES = [f for f, _ in FAMILY_MAP]
COMP_RE_WORDS = ("now that's", "greatest", "best of", "best-of", "compilation")
MIN_SIZE, MAX_SIZE = 2_500_000, 25_000_000


def norm_family(g):
    if not g:
        return None
    s = " " + g.lower() + " "
    for fam, keys in FAMILY_MAP:
        for k in keys:
            if k in s:
                return fam
    return None


def caption(t, fam):
    return f"{t['artist']}, {fam}, {t.get('decade') or ''}".strip().rstrip(",")


def main():
    fam = sys.argv[1]
    target = int(sys.argv[2]) if len(sys.argv) > 2 else 200
    if fam not in FAMILIES:
        sys.exit(f"unknown family '{fam}'; choose one of: {', '.join(FAMILIES)}")

    tracks = [json.loads(l) for l in (CUR / "tracks.jsonl").open()]
    for t in tracks:
        t["fam"] = norm_family(t.get("genre"))
    cand = [t for t in tracks
            if t["fam"] == fam and t.get("year") and t.get("decade")
            and MIN_SIZE <= t.get("size", 0) <= MAX_SIZE]

    by_decade = defaultdict(list)
    for t in cand:
        by_decade[t["decade"]].append(t)
    for d in by_decade:
        by_decade[d].sort(key=lambda t: (-t["size"],))
    decades = sorted(by_decade)

    picked, seen = [], set()
    per_artist = Counter()

    def try_pick(t, cap):
        if t["path"] in seen:
            return False
        if per_artist[t["artist"]] >= cap:
            return False
        per_artist[t["artist"]] += 1
        seen.add(t["path"])
        picked.append(t)
        return True

    # Round-robin across decades for balance; relax the artist cap in passes.
    idx = {d: 0 for d in decades}
    for cap in (3, 6, 12, 999):
        while len(picked) < target:
            progressed = False
            for d in decades:
                if len(picked) >= target:
                    break
                lst = by_decade[d]
                while idx[d] < len(lst) and not try_pick(lst[idx[d]], cap):
                    idx[d] += 1
                if idx[d] < len(lst):
                    idx[d] += 1
                    progressed = True
            if not progressed:
                break

    SEL.mkdir(parents=True, exist_ok=True)
    with (SEL / f"{fam}.jsonl").open("w") as out:
        for t in picked:
            out.write(json.dumps({"path": t["path"], "artist": t["artist"], "title": t.get("title"),
                                  "genre": t.get("genre"), "decade": t.get("decade"), "year": t.get("year"),
                                  "caption": caption(t, fam)}, ensure_ascii=False) + "\n")

    samples = [{"audio_path": t["path"], "filename": os.path.basename(t["path"]),
                "caption": caption(t, fam), "lyrics": "[Instrumental]", "genre": fam,
                "is_instrumental": True, "labeled": True} for t in picked]
    (SEL / f"{fam}_dataset.json").write_text(json.dumps(
        {"name": fam, "custom_tag": "", "all_instrumental": True, "samples": samples}, ensure_ascii=False))

    dec = Counter(t["decade"] for t in picked)
    print(f"{fam}: {len(picked)} tracks, {len(per_artist)} artists, decades={dict(sorted(dec.items()))}")


if __name__ == "__main__":
    main()
