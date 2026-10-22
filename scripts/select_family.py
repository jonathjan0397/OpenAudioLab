#!/usr/bin/env python3
"""Per-family house-LoRA selector (lean ~200/family).

Usage: select_family.py <family> [target]

Normalizes the messy genre strings into 13 families (multilabel: a track may
belong to several; the first specific match is the primary), then picks ~target
tracks for one family with decade round-robin balancing, a per-artist cap, and
content-hash dedupe. Vocal status is estimated from genre evidence plus an
ffmpeg vocal-band heuristic — tracks are no longer blanket-marked
[Instrumental]. Writes curation/selection_perfamily/<family>.jsonl and
<family>_dataset.json in the exact format the preprocess runner expects.
"""
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

CUR = Path(os.environ.get("OAL_CURATION_DIR", "/Cold-Archive/OpenAudioLab/curation"))
SEL = CUR / "selection_perfamily"

# 13 families, specific -> general. Gospel separate from R&B/Soul; Score
# separate from generic classical; Punk/Alt separate from Rock.
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
# Genre evidence that reliably means "no lead vocal expected".
INSTRUMENTAL_GENRE_WORDS = ("instrumental", "concerto", "symphony", "sonata", "chamber",
                            "soundtrack", "film score", "orchestral", "ambient")
# Vocal-band energy ratio (300-3400 Hz RMS vs full-band RMS) decision band.
VOCAL_RATIO_VOCAL, VOCAL_RATIO_INSTR = 0.55, 0.30


def norm_families(g):
    """All matching families, most specific first (multilabel, no silent single-match)."""
    if not g:
        return []
    s = " " + g.lower() + " "
    return [fam for fam, keys in FAMILY_MAP if any(k in s for k in keys)]


def norm_family(g):
    fams = norm_families(g)
    return fams[0] if fams else None


def caption(t, fam):
    """Caption names the recording, not just the artist (title included)."""
    bits = [f"{t['artist']} - {t['title']}" if t.get("title") else t["artist"], fam]
    if t.get("decade"):
        bits.append(t["decade"])
    return ", ".join(bits)


def _rms_db(path, af):
    cmd = ["ffmpeg", "-v", "error", "-i", str(path), "-af", f"{af},astats=metadata=1:reset=0",
           "-f", "null", "-"]
    try:
        done = subprocess.run(cmd, capture_output=True, timeout=120, check=True)
    except (OSError, subprocess.SubprocessError):
        return None
    text = done.stderr.decode("utf-8", "replace")
    val = None
    for line in text.splitlines():
        if "RMS level dB" in line:
            try:
                val = float(line.rsplit("=", 1)[1])
            except ValueError:
                return None
    return val


def vocal_estimate(t):
    """'vocal' | 'instrumental' | 'unknown' from genre evidence + ffmpeg band heuristic.

    Heuristic basis, not a calibrated detector: ambiguous material stays
    'unknown' and is flagged review_required instead of being silently called
    instrumental.
    """
    g = (t.get("genre") or "").lower()
    if any(w in g for w in INSTRUMENTAL_GENRE_WORDS):
        return "instrumental"
    full = _rms_db(t["path"], "volume=1")
    band = _rms_db(t["path"], "highpass=f=300,lowpass=f=3400")
    if full is None or band is None:
        return "unknown"
    ratio = 10 ** ((band - full) / 20.0)
    if ratio >= VOCAL_RATIO_VOCAL:
        return "vocal"
    if ratio <= VOCAL_RATIO_INSTR:
        return "instrumental"
    return "unknown"


def content_key(t, cache):
    """Content-hash dedupe key; falls back to path only when the file is unreadable."""
    p = t["path"]
    if p in cache:
        return cache[p]
    try:
        h = hashlib.sha256(Path(p).read_bytes()).hexdigest()
    except OSError:
        h = "path:" + p
    cache[p] = h
    return h


def main():
    fam = sys.argv[1]
    target = int(sys.argv[2]) if len(sys.argv) > 2 else 200
    if fam not in FAMILIES:
        sys.exit(f"unknown family '{fam}'; choose one of: {', '.join(FAMILIES)}")

    tracks = [json.loads(l) for l in (CUR / "tracks.jsonl").open()]
    for t in tracks:
        t["fams"] = norm_families(t.get("genre"))
        t["fam"] = t["fams"][0] if t["fams"] else None
    cand = [t for t in tracks
            if fam in (t["fams"] or []) and t.get("year") and t.get("decade")
            and MIN_SIZE <= t.get("size", 0) <= MAX_SIZE]

    by_decade = defaultdict(list)
    for t in cand:
        by_decade[t["decade"]].append(t)
    for d in by_decade:
        by_decade[d].sort(key=lambda t: (-t["size"],))
    decades = sorted(by_decade)

    picked, seen = [], set()
    per_artist = Counter()
    hashes = {}

    def try_pick(t, cap):
        key = content_key(t, hashes)
        if key in seen:
            return False
        if per_artist[t["artist"]] >= cap:
            return False
        per_artist[t["artist"]] += 1
        seen.add(key)
        picked.append(t)
        return True

    # Round-robin across decades for balance; relax the artist cap in passes.
    idx = {d: 0 for d in decades}
    used_cap = 3
    for cap in (3, 6, 12, 999):
        used_cap = cap
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

    # Vocal status per picked track (evidence + heuristic; unknown -> review).
    for t in picked:
        t["vocal_status"] = vocal_estimate(t)

    SEL.mkdir(parents=True, exist_ok=True)
    with (SEL / f"{fam}.jsonl").open("w") as out:
        for t in picked:
            out.write(json.dumps({"path": t["path"], "artist": t["artist"], "title": t.get("title"),
                                  "genre": t.get("genre"), "decade": t.get("decade"), "year": t.get("year"),
                                  "families": t["fams"], "vocal_status": t["vocal_status"],
                                  "sha256": hashes.get(t["path"], "").removeprefix("path:"),
                                  "caption": caption(t, fam)}, ensure_ascii=False) + "\n")

    samples = []
    for t in picked:
        instrumental = t["vocal_status"] == "instrumental"
        samples.append({"audio_path": t["path"], "filename": os.path.basename(t["path"]),
                        "caption": caption(t, fam), "lyrics": "[Instrumental]" if instrumental else "",
                        "genre": fam, "vocal_status": t["vocal_status"],
                        "is_instrumental": instrumental, "labeled": instrumental,
                        "review_required": t["vocal_status"] == "unknown"})
    all_instr = bool(samples) and all(s["is_instrumental"] for s in samples)
    (SEL / f"{fam}_dataset.json").write_text(json.dumps(
        {"name": fam, "custom_tag": "", "all_instrumental": all_instr, "samples": samples}, ensure_ascii=False))

    dec = Counter(t["decade"] for t in picked)
    vs = Counter(t["vocal_status"] for t in picked)
    cap_note = " (cap relaxed to unlimited)" if used_cap == 999 else ""
    print(f"{fam}: {len(picked)} tracks, {len(per_artist)} artists, decades={dict(sorted(dec.items()))}, "
          f"vocal={dict(sorted(vs.items()))}, artist_cap={used_cap}{cap_note}")


if __name__ == "__main__":
    main()
