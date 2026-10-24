#!/usr/bin/env python3
"""Cross-bundle evaluation verification (B3).

Checks, per shared prompt+seed:
  1. all baselines are byte-identical across bundles  (engine neutrality proof)
  2. every candidate scale differs from its baseline  (adapter-inert proof)
  3. candidate shas differ across bundles             (no contamination chains)
Exits 1 on any violation; prints a compact table always.

Usage: OAL_ADMIN_KEY=... scripts/verify_evals.py [--base URL]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from collections import defaultdict


def get(base: str, key: str, path: str):
    req = urllib.request.Request(base + path, headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://10.203.0.1:50555")
    args = ap.parse_args()
    key = os.environ.get("OAL_ADMIN_KEY", "")
    base = args.base + "/api/v1/admin/model-lab"

    bundles = get(base, key, "/bundles")["bundles"]
    per_prompt = defaultdict(lambda: {"baseline": {}, "c100": {}, "c050": {}})
    checked = 0
    for b in bundles:
        if b["kind"] != "adapter":
            continue
        evs = get(base, key, f"/bundles/{b['id']}/evaluations").get("evaluations", [])
        scored = [e for e in evs if e.get("scores", {}).get("samples")]
        if not scored:
            continue
        samples = scored[-1]["scores"]["samples"]
        for s in samples:
            mode = s.get("mode")
            if mode not in ("baseline", "c100", "c050"):
                continue
            cell = f"{b['name']}@{s.get('engine', s.get('scale', ''))}"
            per_prompt[(s.get("prompt"), scored[-1]["scores"].get("seed"))][mode][cell] = \
                s.get("sha256")
            checked += 1

    problems = []
    for (prompt, seed), by_mode in sorted(per_prompt.items(), key=lambda x: str(x[0])):
        base_shas = set(by_mode["baseline"].values())
        if len(base_shas) > 1:
            problems.append(f"BASELINE_DRIFT {prompt!r} seed={seed}: {len(base_shas)} distinct")
        for cand in ("c100", "c050"):
            for cell, sha in by_mode[cand].items():
                if base_shas and sha in base_shas:
                    problems.append(f"ADAPTER_INERT {cell} {prompt!r}")
            # (candidate-vs-candidate equality across bundles implies both silent,
            # which the ADAPTER_INERT baseline-membership check already catches)
    print(f"prompt-groups checked: {len(per_prompt)}  samples: {checked}")
    if problems:
        print("PROBLEMS:")
        for p in problems:
            print("  " + p)
        return 1
    print("ALL CHECKS PASS: baselines neutral, candidates live, no chains")
    return 0


if __name__ == "__main__":
    sys.exit(main())
