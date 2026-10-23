"""Model Lab M2: incremental importer, identification pipeline, coverage, selection.

Identification is metadata work (fpcalc + AcoustID + MusicBrainz), not model
inference, so it runs in the API process with durable status + provider cache
and is retryable. Every provider result is stored as a claim pending review;
nothing here rewrites lyrics or audio.
"""

from __future__ import annotations

import hashlib
import os
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
        capture_output=True, timeout=25, check=False)
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
        "format": (fmt.get("format_name") or "")[:120] or None,
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


def _scan_row(session, source: MlSource, batch: MlImportBatch, row: dict,
              seen: set[str], counts: dict, *, preview: bool) -> None:
    """One manifest/directory row -> recording classification (shared core)."""
    path = Path(row["path"])
    batch.scanned += 1
    if path.suffix.lower() not in AUDIO_EXTS:
        counts["excluded"] += 1
        return
    if not path.exists():
        counts["excluded"] += 1
        return
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
        return  # unchanged: no rewrite
    if by_path is not None:
        counts["changed"] += 1
        classification = "changed"
        existing = by_path
    elif by_sha is not None:
        counts["duplicate"] += 1
        return  # same content already catalogued at another path
    else:
        counts["new"] += 1
        classification = "new"
        existing = None
        seen.add(sha)
    probe = probe_file(path)
    review_required = bool(probe.get("duration_seconds") and probe["duration_seconds"] < 5)
    if preview:
        return
    if existing is not None:
        existing.classification = classification
        existing.sha256 = sha
        existing.bytes = size
        existing.probe_json = probe or existing.probe_json
        existing.review_required = review_required
        record = existing
    else:
        record = MlRecording(
            source_id=source.id, path=str(path), sha256=sha, bytes=size,
            duration_seconds=probe.get("duration_seconds"),
            sample_rate=probe.get("sample_rate"), channels=probe.get("channels"),
            format=probe.get("format"), probe_json=probe,
            review_required=review_required,
            families_json=row.get("families") or [],
            title=row.get("title"), artist=row.get("artist"),
            genre_raw=row.get("genre"), year=row.get("year"), decade=row.get("decade"),
            classification=classification)
        session.add(record)
    from .library_parse import enrich_recording
    enrich_recording(record, path)
    from .library_parse import quick_decode_ok
    if record.tags_state in ("parsed", "verified") and not quick_decode_ok(path):
        record.tags_state = "invalid"
        record.review_required = True
        prov = dict(record.tags_provenance_json or {})
        prov["decode_failed"] = True
        record.tags_provenance_json = prov
    session.flush()
    for field in ("title", "artist", "genre", "year", "decade"):
        value = row.get(field)
        if value and not _has_locked_claim(session, record.id, field):
            session.add(MlMetadataClaim(
                recording_id=record.id, field=field, value=str(value),
                provenance="supplier", provider=source.name))


def scan_source(session, source: MlSource, *, preview: bool = True,
                seen_shas: set[str] | None = None) -> dict:
    """Incremental scan: new/cached/changed/duplicate/excluded/review counts."""
    batch = MlImportBatch(source_id=source.id, state="running")
    session.add(batch)
    counts = {"new": 0, "cached": 0, "changed": 0, "duplicate": 0, "excluded": 0, "review": 0}
    seen = seen_shas if seen_shas is not None else set(
        session.execute(select(MlRecording.sha256).where(MlRecording.source_id == source.id))
        .scalars().all())
    for row in _manifest_rows(source):
        _scan_row(session, source, batch, row, seen, counts, preview=preview)
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


def _scan_target_rows(session, source: MlSource, *, after: str | None) -> list[dict]:
    """Sorted manifest/dir rows, sliced after the cursor path (resume)."""
    import bisect

    if source.kind == "dir" and source.path:
        root = Path(source.path)
        paths = sorted(str(p) for p in _walk_audio(root))
        rows = [{"path": p} for p in paths]
    else:
        rows = sorted(_manifest_rows(source), key=lambda r: str(r.get("path")))
    if after:
        idx = bisect.bisect_right([str(r["path"]) for r in rows], after)
        rows = rows[idx:]
    return rows


def _walk_audio(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith((".", "$")))
        for name in filenames:
            if Path(name).suffix.lower() in AUDIO_EXTS:
                yield Path(dirpath) / name


def scan_source_resumable(db, source_id: str, batch_id: str, *, chunk_files: int = 500,
                          abort=None, on_progress=None) -> dict:
    """Worker-side import: per-chunk commit + cursor + heartbeat hooks.

    Idempotent: unchanged files classify as `cached`, so a redelivered job
    re-hashes only what the cursor has not passed yet.
    """
    stopped = False
    while True:
        if abort is not None and abort():
            stopped = True
            break
        with db.session() as session:
            source = session.get(MlSource, source_id)
            batch = session.get(MlImportBatch, batch_id)
            if source is None or batch is None:
                raise ModelLabError(f"scan target missing: {source_id}/{batch_id}")
            after = (batch.cursor_json or {}).get("after")
            rows = _scan_target_rows(session, source, after=after)
            if not rows:
                batch.state = "completed"
                batch.finished_at = utcnow()
                session.commit()
                break
            counts = {**{"new": 0, "cached": 0, "changed": 0, "duplicate": 0,
                         "excluded": 0, "review": 0}, **(batch.counts_json or {})}
            seen: set[str] = set()
            for row in rows[:chunk_files]:
                _scan_row(session, source, batch, row, seen, counts, preview=False)
            batch.counts_json = counts
            batch.cursor_json = {"after": str(rows[min(chunk_files, len(rows)) - 1]["path"]),
                                 "scanned": batch.scanned, "at": utcnow().isoformat()}
            session.commit()
        if on_progress is not None:
            on_progress(min(chunk_files, len(rows)), batch.scanned)
    with db.session() as session:
        batch = session.get(MlImportBatch, batch_id)
        return {"counts": dict(batch.counts_json or {}), "scanned": batch.scanned,
                "state": "cancelled" if stopped else batch.state}


def rebuild_dir_index(db, settings, *, root: str | None = None, chunk_dirs: int = 400,
                      abort=None, on_progress=None) -> dict:
    """Index every directory under the library root (streaming readdir walk).

    Serves the browse UI from the DB so the hub never touches TrueNAS files.
    """
    from .models import MlDirIndex

    raw_root = Path(root or settings.truenas_browse_root or "")
    if not raw_root.is_dir():
        raise ModelLabError("BROWSE_NOT_CONFIGURED: library root unavailable on this host")
    browse_root = (settings.truenas_browse_root or "").strip()
    if browse_root:
        norm_root = os.path.normpath(str(raw_root))
        norm_base = os.path.normpath(browse_root)
        if norm_root != norm_base and not norm_root.startswith(norm_base + os.sep):
            raise ModelLabError(f"BROWSE_OUT_OF_ROOT: {root} is outside the configured root")
    indexed = 0
    walker = os.walk(raw_root, topdown=True)
    pending: list[Path] = [raw_root]
    with db.session() as session:
        while pending:
            if abort is not None and abort():
                return {"indexed": indexed, "cancelled": True}
            d = pending.pop(0)
            try:
                entries = list(os.scandir(d))
            except OSError:
                continue
            subdirs = sorted(Path(e.path) for e in entries if e.is_dir(follow_symlinks=False)
                             and not e.name.startswith((".", "$")))
            pending.extend(subdirs)
            files = [{"name": e.name, "bytes": (e.stat(follow_symlinks=False).st_size
                                                if e.is_file(follow_symlinks=False) else None),
                      "is_dir": e.is_dir(follow_symlinks=False)} for e in entries]
            audio = [f for f in files if not f["is_dir"]
                     and Path(f["name"]).suffix.lower() in AUDIO_SUFFIXES]
            names = {f["name"].lower() for f in files}
            row = session.get(MlDirIndex, str(d)) or MlDirIndex(
                path=str(d), parent=str(d.parent), name=d.name)
            row.parent = str(d.parent)
            row.name = d.name
            row.n_audio = len(audio)
            row.n_dirs = len(subdirs)
            row.has_nfo = ("album.nfo" in names or "artist.nfo" in names)
            row.has_lrc = any(n.endswith(".lrc") for n in names)
            row.files_json = [{k: f[k] for k in ("name", "bytes")} for f in audio]
            session.merge(row)
            indexed += 1
            if indexed % chunk_dirs == 0:
                session.commit()
                if on_progress is not None:
                    on_progress(indexed, -1)
        session.commit()
    return {"indexed": indexed, "total_dirs": indexed}


def browse_from_index(session, settings, path: str | None) -> dict:
    """DB-catalog browse (children dirs + audio files of one directory)."""
    from .models import MlDirIndex

    raw_root = (settings.truenas_browse_root or "").strip()
    root = Path(raw_root) if raw_root else None
    target = str(Path(path).resolve()) if path else str(root)
    if root is not None and str(target) != str(root) and not str(target).startswith(str(root) + os.sep):
        raise ModelLabError("BROWSE_OUT_OF_ROOT: path escapes the browse root")
    row = session.get(MlDirIndex, target)
    if row is None:
        raise ModelLabError("BROWSE_NOT_INDEXED: folder is not in the worker catalog; "
                            "run a dir-index refresh first")
    kids = session.execute(select(MlDirIndex).where(MlDirIndex.parent == target)
                           .order_by(MlDirIndex.name)).scalars().all()
    entries = [{"name": k.name, "path": k.path, "is_dir": True, "bytes": None,
                "mtime": k.updated_at.isoformat() if k.updated_at else None,
                "n_audio": k.n_audio} for k in kids]
    entries += [{"name": f["name"], "path": str(Path(target) / f["name"]), "is_dir": False,
                 "bytes": f.get("bytes"), "mtime": None} for f in row.files_json]
    return {"path": target, "root": str(root) if root else target,
            "parent": None if target == str(root) else str(Path(target).parent),
            "entries": entries, "source": "dir_index"}


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

    Leads with taxonomy style phrases (the generation-prompt vocabulary),
    then the recording's own evidence (artist/title/genre/decade); falls back
    to the filename stem. Never invents: joins only fields on the record.
    """
    parts: list[str] = []
    from .style_tags import caption_for
    style = caption_for(rec)
    if style:
        parts.append(style)
    artist = (getattr(rec, "artist", None) or "").strip()
    title = (getattr(rec, "title", None) or "").strip()
    if artist and title:
        parts.append(f"{artist} - {title}")
    elif artist:
        parts.append(artist)
    elif title:
        parts.append(title)
    from .library_parse import clean_genre
    from .library_parse import clean_genre
    genre = clean_genre(getattr(rec, "genre_raw", None))
    if genre and not style:
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
    """Admin-selected TrueNAS files -> manifest source + immediate scan.

    Kept for small/local (already-mounted) scans; the admin routes now use
    create_scan_job so the hub never reads library files itself.
    """
    (source, _), = create_scan_job(session, settings, source_name=source_name, paths=paths,
                                    make_batch=False)
    result = scan_source(session, source, preview=False)
    return source, result


def create_scan_job(session, settings, *, source_name: str, paths: list[str] | None = None,
                    roots: list[str] | None = None, make_batch: bool = True):
    """Register a manifest or directory source + queued import batch (no file I/O).

    All path checks are pure string containment — the hub has no library mount;
    the gpu1 worker validates and reads files during the scan job.
    """
    import re

    raw_root = (settings.truenas_browse_root or "").strip()
    if not raw_root:
        raise ModelLabError("BROWSE_NOT_CONFIGURED: OAL_TRUENAS_BROWSE_ROOT is not set")
    root = os.path.normpath(raw_root)
    if not source_name or not source_name.strip():
        raise ModelLabError("source_name is required")

    def guarded(raw: str) -> str:
        p = os.path.normpath(str(raw))
        if p != root and not p.startswith(root + os.sep):
            raise ModelLabError(f"BROWSE_OUT_OF_ROOT: {raw}")
        return p

    kind = "manifest" if paths else "dir"
    targets = [guarded(x) for x in (paths if paths else roots or [])]
    if not targets:
        raise ModelLabError("no files or directories selected")

    specs: list[tuple[MlSource, MlImportBatch]] = []
    if kind == "manifest":
        if session.execute(select(MlSource).where(MlSource.name == source_name)
                           ).scalar_one_or_none() is not None:
            raise ModelLabError(f"source already exists: {source_name}")
        slug = re.sub(r"[^a-z0-9]+", "-", source_name.lower()).strip("-") or "source"
        manifest_dir = Path(settings.storage_dir) / "ml-manifests"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest = manifest_dir / f"{slug}-{utcnow().strftime('%Y%m%d%H%M%S')}.jsonl"
        manifest.write_text("".join(json.dumps({"path": p}) + "\n" for p in targets),
                            encoding="utf-8")
        specs.append((MlSource(id=new_uuid(), name=source_name, kind="manifest",
                               path=str(manifest), status="approved",
                               agreement_json={"selection": {"state": "approved",
                                                             "evidence": "admin-selection"}}),
                      MlImportBatch(state="queued") if make_batch else None))
    else:
        for i, target in enumerate(targets):
            name = source_name if len(targets) == 1 else f"{source_name}-{i + 1}"
            if session.execute(select(MlSource).where(MlSource.name == name)
                               ).scalar_one_or_none() is not None:
                raise ModelLabError(f"source already exists: {name}")
            specs.append((MlSource(id=new_uuid(), name=name, kind="dir", path=target,
                                   status="approved",
                                   agreement_json={"selection": {"state": "approved",
                                                                 "evidence": "admin-selection"}}),
                          MlImportBatch(state="queued") if make_batch else None))
    with session.no_autoflush:
        for source, batch in specs:
            if batch is not None:
                batch.source_id = source.id
            session.add(source)
            if batch is not None:
                session.add(batch)
    session.commit()
    return specs


def enqueue_scan_job(session, settings, source: MlSource, batch: MlImportBatch,
                    *, operation: str = "model_lab.scan"):
    """Job + outbox row for a queued import batch (same pattern as identify)."""
    import hashlib as _hl
    import json as _json

    from .models import Job
    from .orchestration import enqueue

    request_json = {"source_id": source.id, "batch_id": batch.id, "chunk_files": 500}
    job = Job(id=new_uuid(), owner_id="model-lab", operation=operation,
              model_id=settings.train_queue_model_id, model_revision="model-lab",
              status="queued", request_json=request_json,
              request_hash=_hl.sha256(_json.dumps(request_json, sort_keys=True).encode()).hexdigest(),
              idempotency_key=f"ml-scan-{batch.id}")
    session.add(job)
    batch.cursor_json = {"job_id": job.id}
    enqueue(session, job, settings)
    session.commit()
    return job


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
