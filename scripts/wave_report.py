#!/usr/bin/env python3
"""Wave checkpoint report: catalog, tags, lyrics, jobs, disk (read-only).

Usage: OAL_ADMIN_KEY=... scripts/wave_report.py [--base http://10.203.0.1:50555]
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.request
from collections import Counter


def get(base: str, key: str, path: str) -> dict:
    req = urllib.request.Request(base + path,
                                 headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://10.203.0.1:50555")
    args = ap.parse_args()
    key = os.environ.get("OAL_ADMIN_KEY", "")
    base = args.base + "/api/v1/admin/model-lab"

    tags, lyric_origin, genres = Counter(), Counter(), Counter()
    total = 0
    off = 0
    while True:
        rows = get(base, key, f"/recordings?limit=200&offset={off}")["recordings"]
        if not rows:
            break
        for r in rows:
            total += 1
            tags[r["tags_state"]] += 1
            lyric_origin[r["lyrics_origin"] or "none"] += 1
            if r.get("genre_raw"):
                genres[r["genre_raw"]] += 1
        off += len(rows)

    batches = get(base, key, "/batches")["batches"]
    batch_states = Counter(b["state"] for b in batches)
    print(f"recordings: {total}")
    print("tags_state:  " + "  ".join(f"{k}={v}" for k, v in tags.most_common()))
    print("lyrics:      " + "  ".join(f"{k}={v}" for k, v in lyric_origin.most_common()))
    print(f"distinct genres: {len(genres)}; top: "
          + ", ".join(f"{g}({n})" for g, n in genres.most_common(8)))
    print(f"import batches: " + "  ".join(f"{k}={v}" for k, v in batch_states.most_common()))
    running = [b for b in batches if b["state"] == "running"][:3]
    for b in running:
        print(f"  running: {b['id'][:8]} scanned={b['scanned']} counts={b['counts']}")


if __name__ == "__main__":
    main()
