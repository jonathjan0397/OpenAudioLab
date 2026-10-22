"""Model Lab M3: vocal segment extraction, identity embeddings, singer grouping.

Embeddings use the existing ``mfcc-stats-v1`` log-mel statistics embedder
(pure Python, no torch). The BYOL singer-identity encoder is a config-gated
challenger: enabling it without a configured encoder fails closed, never a
silent fallback.
"""

from __future__ import annotations

import subprocess
from array import array
from pathlib import Path

from sqlalchemy import select

from .uais import embedding
from .uais.embedding import cosine
from .uais.qc import PCM_SAMPLE_RATE, QcError, decode_pcm16_mono
from .models import MlEmbeddingVector, MlRecording, MlVoiceGroup, MlVoiceSegment

CHALLENGER_MODELS = {"byol-v1"}


class VoiceLabError(ValueError):
    pass


def resolve_identity_model(settings) -> str:
    """Default embedder unless the challenger is explicitly enabled and available."""
    challenger = (getattr(settings, "voice_identity_challenger", "") or "").strip()
    if not challenger:
        return settings.voice_embedding_model
    if challenger not in CHALLENGER_MODELS:
        raise VoiceLabError(f"unknown identity challenger: {challenger}")
    raise VoiceLabError(
        f"challenger {challenger} requires a configured encoder (BYOL not wired in this build)")


def decode_crop(ffmpeg_bin: str, path: Path, start: float, seconds: float) -> array:
    """Decode one crop to mono 16 kHz s16le PCM."""
    try:
        proc = subprocess.run(
            [ffmpeg_bin, "-v", "error", "-ss", f"{start:.3f}", "-i", str(path),
             "-t", f"{seconds:.3f}", "-ac", "1", "-ar", str(PCM_SAMPLE_RATE),
             "-f", "s16le", "-"],
            capture_output=True, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise QcError("QC_DECODE_FAILED", "Crop decoding failed.") from exc
    if proc.returncode != 0 or not proc.stdout:
        raise QcError("QC_CORRUPT", "Crop could not be decoded.")
    samples = array("h")
    samples.frombytes(proc.stdout[: len(proc.stdout) - len(proc.stdout) % 2])
    return samples


def frame_rms(samples: array) -> float:
    if not samples:
        return 0.0
    total = 0
    for s in samples:
        total += s * s
    return (total / len(samples)) ** 0.5 / 32768.0


def scan_recording(session, rec: MlRecording, settings, *, max_segments: int = 6) -> dict:
    """Energy-gated window crops -> identity embeddings -> candidate segments."""
    model = resolve_identity_model(settings)
    path = Path(rec.path)
    duration = rec.duration_seconds or 0.0
    if duration <= 0:
        raise VoiceLabError("recording has no duration; probe first")
    window = settings.voice_scan_window_seconds
    hop = settings.voice_scan_hop_seconds
    starts: list[float] = []
    t = 0.0
    while t + 1.0 <= duration and len(starts) < max_segments * 3:
        starts.append(t)
        t += hop
    segments = []
    for start in starts:
        if len(segments) >= max_segments:
            break
        try:
            samples = decode_crop(settings.ffmpeg_bin, path, start, window)
        except QcError:
            continue
        rms = frame_rms(samples)
        if rms < settings.voice_scan_rms_floor:
            continue  # near-silent window: not a vocal candidate
        vector = embedding.embed_pcm16(samples)
        seg = MlVoiceSegment(recording_id=rec.id, crop_start=start,
                             crop_end=min(start + window, duration),
                             quality_json={"rms": round(rms, 4), "model": model})
        session.add(seg)
        session.flush()
        session.add(MlEmbeddingVector(segment_id=seg.id, model=model, vector_json=vector))
        segments.append(seg)
    session.commit()
    return {"segments": len(segments), "model": model}


def cluster_segments(session, settings, *, model: str | None = None) -> dict:
    """Greedy centroid clustering of candidate/accepted segments into singer groups."""
    model = model or resolve_identity_model(settings)
    vectors = session.execute(
        select(MlEmbeddingVector, MlVoiceSegment)
        .join(MlVoiceSegment, MlVoiceSegment.id == MlEmbeddingVector.segment_id)
        .where(MlEmbeddingVector.model == model,
               MlVoiceSegment.state.in_(("candidate", "accepted")))).all()
    for _, seg in vectors:
        seg.group_id = None
    groups: list[dict] = []  # {centroid, members, sims}
    threshold = settings.voice_cluster_threshold
    for vec_row, seg in vectors:
        vec = vec_row.vector_json
        best, best_sim = None, -1.0
        for g in groups:
            sim = cosine(vec, g["centroid"])
            if sim > best_sim:
                best, best_sim = g, sim
        if best is not None and best_sim >= threshold:
            best["members"].append((seg, vec))
            best["sims"].append(best_sim)
            best["centroid"] = embedding.centroid([m[1] for m in best["members"]])
        else:
            groups.append({"centroid": list(vec), "members": [(seg, vec)], "sims": []})
    # persist
    old = session.execute(select(MlVoiceGroup).where(
        MlVoiceGroup.embedding_model == model,
        MlVoiceGroup.state == "suggested")).scalars().all()
    for g in old:
        session.delete(g)
    created = 0
    for g in groups:
        if len(g["members"]) < 2:
            continue  # singletons are not singer groups yet
        grp = MlVoiceGroup(embedding_model=model, centroid_json=g["centroid"],
                           member_count=len(g["members"]),
                           confidence=round(sum(g["sims"]) / len(g["sims"]), 4) if g["sims"] else None)
        session.add(grp)
        session.flush()
        for seg, _ in g["members"]:
            seg.group_id = grp.id
        created += 1
    session.commit()
    return {"model": model, "segments": len(vectors), "groups": created,
            "threshold": threshold}


def review_group(session, group: MlVoiceGroup, decision: str, reviewer: str,
                 merge_into: str | None = None) -> dict:
    if decision not in ("approve", "reject", "merge"):
        raise VoiceLabError(f"unknown group decision: {decision}")
    if decision == "merge":
        target = session.get(MlVoiceGroup, merge_into) if merge_into else None
        if target is None or target.id == group.id:
            raise VoiceLabError("merge requires an existing different target group")
        group.state = "merged"
        group.merged_into = target.id
        for seg in session.execute(select(MlVoiceSegment).where(
                MlVoiceSegment.group_id == group.id)).scalars():
            seg.group_id = target.id
        members = session.execute(select(MlVoiceSegment).where(
            MlVoiceSegment.group_id == target.id)).scalars().all()
        target.member_count = len(members)
    else:
        group.state = "approved" if decision == "approve" else "rejected"
        for seg in session.execute(select(MlVoiceSegment).where(
                MlVoiceSegment.group_id == group.id)).scalars():
            seg.state = "accepted" if decision == "approve" else "rejected"
    group.reviewed_by = reviewer
    session.commit()
    return {"id": group.id, "state": group.state, "member_count": group.member_count}
