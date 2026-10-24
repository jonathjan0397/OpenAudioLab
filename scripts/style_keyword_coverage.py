#!/usr/bin/env python3
"""Style keyword coverage matrix: taxonomy <-> cheat sheet <-> trained adapters.

Offline parts always run; the live section reads the public cheat sheet and
the admin bundle list when OAL_ADMIN_KEY is set. Read-only; safe to run any
time. Usage:
  OAL_ADMIN_KEY=... .venv/bin/python scripts/style_keyword_coverage.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.style_tags import cheat_sheet_categories, resolve_style_text, taxonomy  # noqa: E402
from app.styles_data import ALL_CURATED_TAGS  # noqa: E402

BASE = os.environ.get("OAL_API_BASE", "http://10.203.0.1:50555")


def _norm(s: str) -> str:
    from app.style_tags import normalize

    return normalize(s)


def main() -> int:
    tx = taxonomy()
    aliases = {_norm(k) for k in tx["alias_map"]}
    ids = {s["id"] for s in tx["subgenres"]}
    sections = cheat_sheet_categories()
    tax_terms = {_norm(t) for sect in sections for t in sect["tags"]}
    curated = {_norm(t) for t in ALL_CURATED_TAGS}

    print(f"taxonomy: {len(ids)} subgenres / {len(aliases)} aliases / "
          f"{len(sections)} families / {len(tx['junk_genres'])} junk")
    print(f"cheat sheet: {len(sections)} family sections, "
          f"{len(tax_terms)} normalized family terms")
    overlap = curated & aliases
    print(f"curated dimensions: {len(curated)} tags; "
          f"{len(overlap)} resolve in the taxonomy alias map; "
          f"{len(curated - overlap)} are mood/era/instrument vocabulary "
          f"(intentionally non-genre)")
    unmatched = [t for t in sorted(ALL_CURATED_TAGS)
                 if not resolve_style_text(t)[0]
                 and _norm(t) not in aliases]
    print(f"curated tags with NO taxonomy match: {len(unmatched)}")

    key = os.environ.get("OAL_ADMIN_KEY")
    if not key:
        print("live section skipped (set OAL_ADMIN_KEY)")
        return 0
    req = urllib.request.Request(BASE + "/api/v1/styles/cheatsheet")
    sheet = json.loads(urllib.request.urlopen(req, timeout=30).read())
    live_terms = {_norm(t) for c in sheet["categories"] for t in c["tags"]}
    print(f"live cheat sheet: {len(sheet['categories'])} categories / "
          f"{len(live_terms)} unique terms; family terms present: "
          f"{len(tax_terms & live_terms)}/{len(tax_terms)}")
    areq = urllib.request.Request(BASE + "/api/v1/admin/model-lab/bundles",
                                  headers={"Authorization": f"Bearer {key}"})
    bundles = json.loads(urllib.request.urlopen(areq, timeout=30).read())["bundles"]
    released = [b for b in bundles if b["state"] == "released"
                and b["name"].startswith("style-")]
    lora_norm = {_norm(t) for t in sheet["lora_tags"]}
    print(f"released style bundles: {len(released)}; "
          f"trained keywords on the sheet: {len(lora_norm)}; "
          f"of which taxonomy-matched: "
          f"{len([t for t in lora_norm if t in aliases])}")
    for b in released:
        print("  -", b["name"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
