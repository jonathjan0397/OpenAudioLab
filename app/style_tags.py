"""Deterministic style-tag derivation over the versioned taxonomy (T2).

Pure function of the frozen metadata already on a recording (genre_raw plus
nfo style/mood hints persisted in tags_provenance_json). No network, no LLM.
Multi-label: compounds ("Rock/Pop", "Alternative & Punk") resolve to every
part; aliases, typos and separators are normalized through the taxonomy map.
Results: subgenre ids -> families_json, coverage rollups for curation.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from sqlalchemy import select

_TAX_PATH = Path(__file__).parent / "style_data" / "style_taxonomy.json"
_cache: dict | None = None


def taxonomy() -> dict:
    global _cache
    if _cache is None:
        data = json.loads(_TAX_PATH.read_text(encoding="utf-8"))
        data["_amap"] = {normalize(k): v for k, v in data["alias_map"].items()}
        data["_junk"] = {normalize(j) for j in data["junk_genres"]}
        _cache = data
    return _cache


def normalize(text: object) -> str:
    t = str(text or "").lower()
    t = t.replace("&", " & ").replace("’", "'").replace("–", "-").replace("—", "-")
    t = t.replace(".", " ")
    t = re.sub(r"[\u00b4\u2019`]", "", t)
    t = re.sub(r"[_|+|]+", " ", t)
    t = t.replace("-", " ")
    t = re.sub(r"\s+", " ", t)
    return t.strip()


_SPLIT_RE = re.compile(r"\s+&\s+|/|,|\s\band\s+|\s\+\s")


def split_genre(text: str) -> list[str]:
    parts = [p.strip() for p in _SPLIT_RE.split(normalize(text)) if p.strip()]
    out: list[str] = []
    for p in parts:
        if p not in ("&", "and"):
            out.append(p)
    return out


def derive_tags(rec) -> dict:
    """Resolve a recording's genre evidence into taxonomy tags."""
    tx = taxonomy()
    amap, junk = tx["_amap"], tx["_junk"]
    raw = (getattr(rec, "genre_raw", None) or "").strip()
    extras: list[str] = []
    prov = getattr(rec, "tags_provenance_json", None) or {}
    for key in ("styles", "moods"):
        extras.extend(str(x) for x in (prov.get(key) or []))
    subgenres: list[str] = []
    families: list[str] = []
    unknown: list[str] = []
    seen = set()

    def add_tag(tag: str) -> None:
        if tag in seen:
            return
        seen.add(tag)
        if tag.startswith("FAM:"):
            families.append(tag[4:])
        else:
            subgenres.append(tag)
            fam = tx_by_id().get(tag, {}).get("family")
            if fam:
                families.append(fam)

    for source in ([raw] if raw else []) + extras:
        norm = normalize(source)
        if not norm or norm in junk:
            continue
        whole = amap.get(norm)
        if whole:
            add_tag(whole)
            continue
        for part in split_genre(source):
            hit = amap.get(part)
            if hit:
                add_tag(hit)
            else:
                unknown.append(part)
    return {"subgenres": sorted(set(subgenres)), "families": sorted(set(families)),
            "unknown_parts": sorted(set(unknown)),
            "taxonomy_version": tx["version"],
            "junk": bool(raw) and normalize(raw) in junk}


_tx_index: dict[str, dict] | None = None


def tx_by_id() -> dict[str, dict]:
    global _tx_index
    if _tx_index is None:
        _tx_index = {s["id"]: s for s in taxonomy()["subgenres"]}
    return _tx_index


def caption_for(rec) -> str | None:
    """Subgenre caption phrases (generation-prompt vocabulary) for a record."""
    ids = (getattr(rec, "families_json", None) or [])
    parts = [tx_by_id()[i]["caption"] for i in ids if i in tx_by_id()]
    return " · ".join(parts) if parts else None


def apply_style_tags(rec) -> dict:
    """Recompute and persist taxonomy tags for one recording (caller commits)."""
    result = derive_tags(rec)
    prior = [x for x in (rec.families_json or [])
             if "." not in x and not x.startswith("fam:")]  # selector lanes survive
    rec.families_json = sorted(set(prior)) + result["subgenres"] + \
        [f"fam:{f}" for f in result["families"]]
    prov = dict(rec.tags_provenance_json or {})
    prov["taxonomy_version"] = result["taxonomy_version"]
    if result["unknown_parts"]:
        prov["style_unknown"] = result["unknown_parts"]
    else:
        prov.pop("style_unknown", None)
    rec.tags_provenance_json = prov
    return result


def recompute_all(db) -> dict:
    """Idempotent whole-catalog restyle (pure DB read + deterministic tags)."""
    from .models import MlRecording

    counts = {"total": 0, "tagged": 0, "family_only": 0, "junk": 0, "unresolved": 0}
    with db.session() as session:
        for rec in session.execute(select(MlRecording)).scalars():
            counts["total"] += 1
            res = apply_style_tags(rec)
            if res["subgenres"]:
                counts["tagged"] += 1
            elif res["families"]:
                counts["family_only"] += 1
            if res["junk"]:
                counts["junk"] += 1
            if res["unknown_parts"]:
                counts["unresolved"] += 1
        session.commit()
    return counts



def coverage(session) -> dict:
    """Trainable counts per tag: parsed/verified rows, rights + approval aware."""
    from .models import MlRecording, MlRightsRecord

    tag_counts: dict[str, dict[str, int]] = {}
    for rec in session.execute(select(MlRecording)).scalars():
        tags = rec.families_json or []
        approved = rec.review_status == "approved"
        has_rights = session.execute(
            select(MlRightsRecord.id).where(
                MlRightsRecord.recording_id == rec.id,
                MlRightsRecord.state == "declared").limit(1)).scalar_one_or_none() is not None
        for t in tags:
            cell = tag_counts.setdefault(t, {"total": 0, "approved": 0, "rights_ok": 0,
                                             "trainable": 0})
            cell["total"] += 1
            if approved:
                cell["approved"] += 1
            if has_rights:
                cell["rights_ok"] += 1
            if approved and has_rights:
                cell["trainable"] += 1
    ordered = dict(sorted(tag_counts.items(), key=lambda kv: -kv[1]["trainable"]))
    return {"taxonomy_version": taxonomy()["version"], "tags": ordered}


def has_tag(rec, tag: str) -> bool:
    if tag.startswith("fam:"):
        tag = tag[4:]
    tags = rec.families_json or []
    if "." in tag:
        return tag in tags
    return f"fam:{tag}" in tags or any(x.startswith(tag + ".") for x in tags)


def select_for_style_tag(session, tag: str, *, target: int = 200, floor: int = 40,
                         min_bytes: int = 2_500_000, max_bytes: int = 25_000_000) -> list:
    """House curation rules over tagged records: size filter, decade round-robin,
    per-artist cap 3 (relaxing upward if the floor needs it). Deterministic."""
    from .models import MlRecording

    rows = [r for r in session.execute(select(MlRecording)).scalars()
            if r.tags_state in ("parsed", "verified") and has_tag(r, tag)]
    eligible = [r for r in rows if r.bytes and min_bytes <= r.bytes <= max_bytes]
    fallback = eligible or rows  # small niche tags: drop the size filter at the floor
    groups: dict[str, list] = {}
    for r in sorted(fallback, key=lambda r: (r.artist or "", r.title or "")):
        groups.setdefault(r.decade or "??", []).append(r)
    order = sorted(groups)
    ptr = {d: 0 for d in order}
    for cap in (3, 6, 12, 10 ** 9):
        picked, seen_artist = [], {a: 0 for a in {r.artist for g in groups.values() for r in g}}
        while len(picked) < target:
            advanced = False
            for d in order:
                lst = groups[d]
                while ptr[d] < len(lst):
                    r = lst[ptr[d]]
                    key = r.artist or r.id
                    if seen_artist.get(key, 0) >= cap:
                        ptr[d] += 1
                        continue
                    ptr[d] += 1
                    seen_artist[key] = seen_artist.get(key, 0) + 1
                    picked.append(r)
                    advanced = True
                    break
                if len(picked) >= target:
                    break
            if not advanced or len(picked) >= target:
                break
        if len(picked) >= target or cap == 10 ** 9:
            return picked
        ptr = {d: 0 for d in order}
    return picked


NEUTRAL_CONTROL = {"name": "control-neutral",
                   "caption": "instrumental control, neutral mood, balanced mix"}


def _tag_counts(session) -> dict[str, int]:
    from .models import MlRecording

    counts: dict[str, int] = {}
    for row in session.execute(select(MlRecording)).scalars():
        for tag in row.families_json or []:
            if "." in tag:
                counts[tag] = counts.get(tag, 0) + 1
    return counts


def eval_prompts_for(session, tag: str, *, siblings: int = 2) -> list[dict]:
    """A/B prompts for a checkpoint: the trained subgenre, its two densest
    family siblings (in-family discrimination) and a neutral control."""
    from .review import slug

    subs = tx_by_id()
    counts = _tag_counts(session)
    fam = subs[tag]["family"] if tag in subs else tag
    if tag in subs:
        target = tag
    else:  # family-level tag: densest subgenre within the family wins
        kin = [s for s in subs if subs[s]["family"] == fam]
        target = max(kin, key=lambda s: counts.get(s, 0), default=None)
    prompts: list[dict] = []
    if target:
        prompts.append({"name": slug(target), "caption": subs[target]["caption"]})
    kin = [s for s in subs if subs[s]["family"] == fam and s != target]
    for s in sorted(kin, key=lambda x: -counts.get(x, 0))[:siblings]:
        prompts.append({"name": slug(s), "caption": subs[s]["caption"]})
    prompts.append(dict(NEUTRAL_CONTROL))
    return prompts


def voice_eval_prompts(dataset) -> list[dict]:
    """Voice-chain prompts: two of the trained lyric passages + instrumental control."""
    entries = [e for e in (dataset.manifest_json or {}).get("entries", [])
               if (e.get("lyrics") or "").strip()][:2]
    prompts = [{"name": f"voice-trained-{i + 1}",
                "caption": (e.get("caption") or "vocal test"), "lyrics": e["lyrics"]}
               for i, e in enumerate(entries)]
    prompts.append({"name": "control-instr",
                    "caption": "instrumental control, neutral mood, balanced mix",
                    "instrumental": True})
    return prompts
