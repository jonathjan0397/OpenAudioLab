"""Model Lab M2: incremental importer, identification pipeline, coverage, selection.

Identification is metadata work (fpcalc + AcoustID + MusicBrainz), not model
inference, so it runs in the API process with durable status + provider cache
and is retryable. Every provider result is stored as a claim pending review;
nothing here rewrites lyrics or audio.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select

from . import tagging
from .models import (
    MlImportBatch,
    MlLane,
    MlMetadataClaim,
    MlProviderCache,
    MlRecording,
    MlSource,
    MlTagAssignment,
    MlTagTerm,
    SiteSetting,
    new_uuid,
    utcnow,
)

AUDIO_EXTS = {".mp3", ".flac", ".wav", ".m4a", ".ogg", ".opus"}
SELECTION_KEY = "model_lab_selection"
DEFAULT_SELECTION = {"replay_pct": 60, "weak_model_pct": 30, "rare_pct": 10,
                     "performer_cap_pct": 10}
IDENTIFY_STATUSES = ("unidentified", "queued", "fingerprinting", "candidates", "enriching",
                     "review_required", "approved", "no_match", "provider_outage",
                     "quota_exhausted", "restricted")


class ModelLabError(ValueError):
    pass


# ------------------------------------------------------------------ importer

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def probe_file(path: Path, ffprobe_bin: str = "ffprobe") -> dict:
    out = subprocess.run(
        [ffprobe_bin, "-v", "error", "-show_entries",
         "format=duration,format_name:stream=sample_rate,channels,codec_name",
         "-of", "json", str(path)],
        capture_output=True, timeout=60, check=False)
    if out.returncode != 0:
        return {}
    try:
        data = json.loads(out.stdout.decode() or "{}")
    except json.JSONDecodeError:
        return {}
    fmt = data.get("format") or {}
    stream = (data.get("streams") or [{}])[0]
    dur = fmt.get("duration")
    return {
        "duration_seconds": float(dur) if dur else None,
        "format": fmt.get("format_name"),
        "sample_rate": stream.get("sample_rate"),
        "channels": stream.get("channels"),
    }


def _manifest_rows(source: MlSource) -> list[dict]:
    if not source.path:
        return []
    root = Path(source.path)
    if root.is_file():  # jsonl manifest
        rows = []
        for line in root.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
        return rows
    return [{"path": str(p)} for p in sorted(root.rglob("*")) if p.is_file()]


def scan_source(session, source: MlSource, *, preview: bool = True,
                seen_shas: set[str] | None = None) -> dict:
    """Incremental scan: new/cached/changed/duplicate/excluded/review counts."""
    batch = MlImportBatch(source_id=source.id, state="running")
    session.add(batch)
    counts = {"new": 0, "cached": 0, "changed": 0, "duplicate": 0, "excluded": 0, "review": 0}
    seen = seen_shas if seen_shas is not None else set(
        session.execute(select(MlRecording.sha256).where(MlRecording.source_id == source.id))
        .scalars().all())
    rows = _manifest_rows(source)
    for row in rows:
        path = Path(row["path"])
        batch.scanned += 1
        if path.suffix.lower() not in AUDIO_EXTS:
            counts["excluded"] += 1
            continue
        if not path.exists():
            counts["excluded"] += 1
            continue
        sha = sha256_file(path)
        size = path.stat().st_size
        by_path = session.execute(
            select(MlRecording).where(MlRecording.source_id == source.id,
                                      MlRecording.path == str(path))).scalars().first()
        by_sha = session.execute(
            select(MlRecording).where(MlRecording.source_id == source.id,
                                      MlRecording.sha256 == sha)).scalars().first()
        if by_path is not None and by_path.sha256 == sha and size == by_path.bytes:
            counts["cached"] += 1
            continue  # unchanged: no rewrite
        if by_path is not None:
            counts["changed"] += 1
            classification = "changed"
            existing = by_path
        elif by_sha is not None:
            counts["duplicate"] += 1
            continue  # same content already catalogued at another path
        else:
            counts["new"] += 1
            classification = "new"
            existing = None
            seen.add(sha)
        probe = probe_file(path)
        review_required = bool(probe.get("duration_seconds") and probe["duration_seconds"] < 5)
        if preview:
            continue
        if existing is not None:
            existing.classification = classification
            existing.sha256 = sha
            existing.bytes = size
            existing.probe_json = probe or existing.probe_json
            existing.review_required = review_required
        else:
            session.add(MlRecording(
                source_id=source.id, path=str(path), sha256=sha, bytes=size,
                duration_seconds=probe.get("duration_seconds"),
                sample_rate=probe.get("sample_rate"), channels=probe.get("channels"),
                format=probe.get("format"), probe_json=probe,
                review_required=review_required,
                families_json=row.get("families") or [],
                title=row.get("title"), artist=row.get("artist"),
                genre_raw=row.get("genre"), year=row.get("year"), decade=row.get("decade"),
                classification=classification))
        for field in ("title", "artist", "genre", "year", "decade"):
            value = row.get(field)
            if value and not preview:
                rec = session.execute(
                    select(MlRecording).where(MlRecording.source_id == source.id,
                                              MlRecording.sha256 == sha)).scalars().first()
                if rec is not None and not _has_locked_claim(session, rec.id, field):
                    session.add(MlMetadataClaim(
                        recording_id=rec.id, field=field, value=str(value),
                        provenance="supplier", provider=source.name))
    batch.counts_json = counts
    batch.cursor_json = {"scanned": batch.scanned, "at": utcnow().isoformat()}
    batch.state = "completed"
    batch.finished_at = utcnow()
    if preview:
        session.flush()
        batch_id = batch.id
        session.expunge(batch)
        return {"batch_id": batch_id, "scanned": batch.scanned, "counts": counts, "preview": True}
    session.commit()
    return {"batch_id": batch.id, "scanned": batch.scanned, "counts": counts, "preview": False}


def _has_locked_claim(session, recording_id: str, field: str) -> bool:
    return session.execute(
        select(MlMetadataClaim).where(MlMetadataClaim.recording_id == recording_id,
                                      MlMetadataClaim.field == field,
                                      MlMetadataClaim.status == "locked")).scalars().first() is not None


# ------------------------------------------------------------- identification

_MB_LAST_CALL = [0.0]


def _cache_get(session, key: str) -> dict | None:
    row = session.get(MlProviderCache, key)
    if row is None:
        return None
    if row.expires_at is not None:
        exp = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
        if exp < utcnow():
            return None
    return row.body_json


def _cache_put(session, key: str, provider: str, body: dict, ttl_days: int = 30) -> None:
    from datetime import timedelta

    session.merge(MlProviderCache(
        key=key, provider=provider, body_json=body,
        expires_at=utcnow() + timedelta(days=ttl_days)))


def musicbrainz_recording(session, mbid: str, base_url: str, user_agent: str,
                          rate_limit_s: float = 1.0) -> dict | None:
    cached = _cache_get(session, f"musicbrainz:{mbid}")
    if cached is not None:
        return cached
    wait = rate_limit_s - (time.monotonic() - _MB_LAST_CALL[0])
    if wait > 0:
        time.sleep(wait)
    import httpx

    try:
        resp = httpx.get(f"{base_url}/recording/{mbid}",
                         params={"fmt": "json", "inc": "artists+isrcs+release-groups"},
                         headers={"User-Agent": user_agent}, timeout=20)
        resp.raise_for_status()
        body = resp.json()
    except Exception:
        return None
    _MB_LAST_CALL[0] = time.monotonic()
    _cache_put(session, f"musicbrainz:{mbid}", "musicbrainz", body)
    return body


def _add_claim(session, recording_id: str, field: str, value: str, provenance: str,
               provider: str | None, score: float | None) -> None:
    if value is None or str(value) == "":
        return
    if _has_locked_claim(session, recording_id, field):
        return
    session.add(MlMetadataClaim(recording_id=recording_id, field=field, value=str(value),
                                provenance=provenance, provider=provider, score=score))


def identify_recording(session, rec: MlRecording, settings, *, enrich: bool = True) -> str:
    """fpcalc -> cached AcoustID -> optional MusicBrainz; claims stay pending review."""
    key = getattr(settings, "acoustid_client_key", "")
    rec.identify_status = "fingerprinting"
    fp = tagging.fingerprint(Path(rec.path)) if Path(rec.path).exists() else None
    if fp is None:
        rec.identify_status = "provider_outage"
        session.commit()
        return rec.identify_status
    cache_key = f"acoustid:{rec.sha256}"
    body = _cache_get(session, cache_key)
    if body is None:
        body = tagging.acoustid_lookup(fp["fingerprint"], fp.get("duration") or 0.0, key)
        if body["status"] != "provider_outage":
            _cache_put(session, cache_key, "acoustid", body, ttl_days=7)
    if body["status"] == "no_key":
        rec.identify_status = "restricted"
        session.commit()
        return rec.identify_status
    if body["status"] == "provider_error":
        rec.identify_status = "provider_outage"
        session.commit()
        return rec.identify_status
    if body["status"] == "no_match" or not body["matches"]:
        rec.identify_status = "no_match"
        session.commit()
        return rec.identify_status
    best = body["matches"][0]
    min_score = float(getattr(settings, "acoustid_min_score", 0.85))
    if float(best.get("score") or 0.0) < min_score:
        rec.identify_status = "review_required"
        _add_claim(session, rec.id, "title", best.get("title"), "acoustid", "acoustid", best.get("score"))
        _add_claim(session, rec.id, "artist", best.get("artist"), "acoustid", "acoustid", best.get("score"))
        session.commit()
        return rec.identify_status
    rec.identify_status = "candidates"
    _add_claim(session, rec.id, "title", best.get("title"), "acoustid", "acoustid", best.get("score"))
    _add_claim(session, rec.id, "artist", best.get("artist"), "acoustid", "acoustid", best.get("score"))
    mbid = best.get("recording_id")
    if enrich and mbid:
        rec.identify_status = "enriching"
        mb = musicbrainz_recording(session, mbid,
                                   getattr(settings, "musicbrainz_url", "https://musicbrainz.org/ws/2"),
                                   getattr(settings, "musicbrainz_user_agent", "OpenAudioLab/1.0"))
        if mb is None:
            rec.identify_status = "provider_outage"
            session.commit()
            return rec.identify_status
        credits = mb.get("artist-credit")
        if isinstance(credits, list):
            artist = "".join(
                (c.get("name") or "") + (c.get("joinphrase") or "") for c in credits if isinstance(c, dict))
            if artist:
                _add_claim(session, rec.id, "artist", artist, "musicbrainz", "musicbrainz", None)
        if mb.get("title"):
            _add_claim(session, rec.id, "title", mb["title"], "musicbrainz", "musicbrainz", None)
        for isrc in (mb.get("isrcs") or [])[:3]:
            _add_claim(session, rec.id, "isrc", isrc, "musicbrainz", "musicbrainz", None)
    rec.identify_status = "review_required"
    session.commit()
    return rec.identify_status


# ------------------------------------------------------------------- review

def review_recording(session, rec: MlRecording, decision: str, reviewer: str,
                     source: MlSource | None = None) -> dict:
    if decision not in ("approved", "rejected", "restricted"):
        raise ModelLabError(f"unknown review decision: {decision}")
    rec.review_status = decision
    for claim in session.execute(
            select(MlMetadataClaim).where(MlMetadataClaim.recording_id == rec.id,
                                          MlMetadataClaim.status == "suggested")).scalars():
        claim.status = "approved" if decision == "approved" else "rejected"
        claim.reviewed_by = reviewer
    rec.dataset_eligible = decision == "approved" and (source is None or source.status == "approved")
    session.commit()
    return {"review_status": rec.review_status, "dataset_eligible": rec.dataset_eligible}


# ----------------------------------------------------------------- coverage

def compile_caption(session, rec: MlRecording) -> dict:
    """Deterministic caption from the recording's own fields + approved tags.

    No LLM: the compiler only orders and joins evidence that is already on the
    record (invariant 1). Locked/approved claims win over suggestions.
    """
    from .models import MlTagAssignment, MlTagTerm

    fields: dict[str, str] = {}
    for key in ("artist", "title", "genre_raw", "year", "decade"):
        value = getattr(rec, key, None)
        if value not in (None, ""):
            fields[key] = str(value)
    claims = session.execute(
        select(MlMetadataClaim).where(
            MlMetadataClaim.recording_id == rec.id,
            MlMetadataClaim.status.in_(("approved", "locked")),
            MlMetadataClaim.field.notin_(("artist", "title", "genre_raw", "year", "decade")),
        ).order_by(MlMetadataClaim.field)).scalars().all()
    for claim in claims:
        fields.setdefault(claim.field, claim.value)
    if rec.vocal_status and rec.vocal_status != "unknown":
        fields["vocals"] = rec.vocal_status
    rows = session.execute(
        select(MlTagAssignment, MlTagTerm)
        .join(MlTagTerm, MlTagTerm.id == MlTagAssignment.term_id)
        .where(MlTagAssignment.recording_id == rec.id,
               MlTagAssignment.level == "recording",
               MlTagAssignment.status == "approved")
        .order_by(MlTagTerm.namespace, MlTagTerm.label)).all()
    tags = [{"lane": t.namespace, "term": t.label} for a, t in rows]
    parts = [f"{k}: {v}" for k, v in sorted(fields.items())]
    parts += [f"tag[{t['lane']}]: {t['term']}" for t in tags]
    return {"recording_id": rec.id, "text": "; ".join(parts),
            "fields": fields, "tags": tags}


def deterministic_caption(rec: "MlRecording", path: Path | str) -> str:
    """Deterministic training label for a recording (no LLM, invariant 1).

    Prefers the recording's own evidence (artist/title/genre); falls back to
    the filename stem so every sample is always labeled. Never invents a
    style: only joins fields already on the record.
    """
    parts: list[str] = []
    artist = (getattr(rec, "artist", None) or "").strip()
    title = (getattr(rec, "title", None) or "").strip()
    if artist and title:
        parts.append(f"{artist} - {title}")
    elif artist:
        parts.append(artist)
    elif title:
        parts.append(title)
    genre = (getattr(rec, "genre_raw", None) or "").strip()
    if genre:
        parts.append(genre)
    if parts:
        return ", ".join(parts)
    stem = Path(path).stem.strip()
    return stem or "untitled"


AUDIO_SUFFIXES = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".opus", ".aif", ".aiff"}


def browse_directory(settings, path: str | None) -> dict:
    """Read-only TrueNAS file picker under OAL_TRUENAS_BROWSE_ROOT."""
    raw_root = (settings.truenas_browse_root or "").strip()
    root = Path(raw_root)
    if not raw_root or not root.is_dir():
        raise ModelLabError("BROWSE_NOT_CONFIGURED: OAL_TRUENAS_BROWSE_ROOT is not set")
    target = (Path(path).resolve() if path else root)
    if str(target) != str(root) and not str(target).startswith(str(root) + "/"):
        raise ModelLabError("BROWSE_OUT_OF_ROOT: path escapes the browse root")
    if not target.is_dir():
        raise ModelLabError("BROWSE_NOT_A_DIRECTORY: not a directory")
    entries: list[dict] = []
    for p in sorted(target.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
        if p.is_dir():
            entries.append({"name": p.name, "path": str(p), "is_dir": True,
                            "bytes": None, "mtime": None})
        elif p.suffix.lower() in AUDIO_SUFFIXES and p.is_file():
            st = p.stat()
            entries.append({"name": p.name, "path": str(p), "is_dir": False,
                            "bytes": st.st_size,
                            "mtime": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()})
        if len(entries) >= 500:
            break
    return {"path": str(target), "root": str(root),
            "parent": None if str(target) == str(root) else str(target.parent),
            "entries": entries}


def import_selected(session, settings, *, source_name: str, paths: list[str]):
    """Admin-selected TrueNAS files -> manifest source + immediate scan."""
    import re

    raw_root = (settings.truenas_browse_root or "").strip()
    root = Path(raw_root)
    if not raw_root or not root.is_dir():
        raise ModelLabError("BROWSE_NOT_CONFIGURED: OAL_TRUENAS_BROWSE_ROOT is not set")
    if not source_name or not source_name.strip():
        raise ModelLabError("source_name is required")
    if session.execute(select(MlSource).where(MlSource.name == source_name)
                       ).scalar_one_or_none() is not None:
        raise ModelLabError(f"source already exists: {source_name}")
    files = []
    for raw in paths:
        p = Path(raw).resolve()
        if str(p) != str(root) and not str(p).startswith(str(root) + "/"):
            raise ModelLabError(f"BROWSE_OUT_OF_ROOT: {raw}")
        if not p.is_file():
            raise ModelLabError(f"not a readable file: {raw}")
        files.append(p)
    if not files:
        raise ModelLabError("no files selected")
    slug = re.sub(r"[^a-z0-9]+", "-", source_name.lower()).strip("-") or "source"
    manifest_dir = Path(settings.storage_dir) / "ml-manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest = manifest_dir / f"{slug}-{utcnow().strftime('%Y%m%d%H%M%S')}.jsonl"
    manifest.write_text("".join(json.dumps({"path": str(p)}) + "\n" for p in files),
                        encoding="utf-8")
    source = MlSource(id=new_uuid(), name=source_name, kind="manifest",
                      path=str(manifest), status="approved",
                      agreement_json={"pilot-selection": {"state": "approved",
                                                          "evidence": "admin-truenas-selection"}})
    session.add(source)
    session.commit()
    result = scan_source(session, source, preview=False)
    return source, result


def coverage(session) -> dict:
    recs = session.execute(select(MlRecording)).scalars().all()
    total_seconds = sum(r.duration_seconds or 0.0 for r in recs)
    lanes: dict[str, dict] = {}
    for rec in recs:
        for fam in rec.families_json or []:
            lane = lanes.setdefault(fam, {"recordings": 0, "seconds": 0.0,
                                          "performers": set(), "works": set()})
            lane["recordings"] += 1
            lane["seconds"] += rec.duration_seconds or 0.0
            if rec.artist:
                lane["performers"].add(rec.artist.lower())
            if rec.title:
                lane["works"].add(rec.title.lower())
    performers = {r.artist.lower() for r in recs if r.artist}
    return {
        "recordings": len(recs),
        "total_seconds": round(total_seconds, 1),  # physical total: never double-counted
        "distinct_performers": len(performers),
        "lanes": {k: {"recordings": v["recordings"], "seconds": round(v["seconds"], 1),
                      "performers": len(v["performers"]), "works": len(v["works"])}
                  for k, v in sorted(lanes.items())},
    }


# ---------------------------------------------------------------- selection

def get_selection(session) -> dict:
    row = session.get(SiteSetting, SELECTION_KEY)
    if row is None or not row.value:
        return dict(DEFAULT_SELECTION)
    return json.loads(row.value)


def set_selection(session, payload: dict) -> dict:
    merged = dict(DEFAULT_SELECTION)
    for k, v in (payload or {}).items():
        if k not in DEFAULT_SELECTION:
            raise ModelLabError(f"unknown selection key: {k}")
        try:
            v = float(v)
        except (TypeError, ValueError):
            raise ModelLabError(f"{k} must be numeric") from None
        if not 0 <= v <= 100:
            raise ModelLabError(f"{k} must be 0-100")
        merged[k] = v
    total = merged["replay_pct"] + merged["weak_model_pct"] + merged["rare_pct"]
    if abs(total - 100) > 0.01:
        raise ModelLabError("replay+weak_model+rare must sum to 100")
    session.merge(SiteSetting(key=SELECTION_KEY, value=json.dumps(merged)))
    session.commit()
    return merged


# --------------------------------------------------------------- tag registry

def ensure_lanes(session) -> int:
    """Idempotently seed the 24 acquisition lanes."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_ml_lanes_seed", Path(__file__).resolve().parents[1] / "alembic/versions/0040_model_lab_catalog.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    created = 0
    for lane_id, name, group in mod.LANES:
        if session.get(MlLane, lane_id) is None:
            session.add(MlLane(id=lane_id, name=name, group_name=group))
            created += 1
    session.commit()
    return created


def ensure_tag_terms(session) -> int:
    """Idempotently seed the curated vocabulary into the namespaced registry."""
    from .styles_data import CHEATSHEET

    created = 0
    for category, tags in CHEATSHEET.items():
        for tag in tags:
            term_id = f"{category}:{tag}"
            if session.get(MlTagTerm, term_id) is None:
                session.add(MlTagTerm(id=term_id, namespace=category, label=tag.replace("_", " "),
                                      caption_text=tag.replace("_", " ")))
                created += 1
    session.commit()
    return created


def assign_tag(session, rec: MlRecording, term_id: str, provenance: str = "curator",
               status: str = "suggested", basis: str | None = None) -> MlTagAssignment:
    if session.get(MlTagTerm, term_id) is None:
        raise ModelLabError(f"unknown tag term: {term_id}")
    if provenance not in ("evidence", "analysis", "curator"):
        raise ModelLabError(f"unknown provenance: {provenance}")
    assignment = MlTagAssignment(recording_id=rec.id, term_id=term_id, provenance=provenance,
                                 confidence_basis=basis, status=status)
    session.add(assignment)
    session.commit()
    return assignment
