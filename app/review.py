"""Local review landing zone for trained-bundle A/B listening (batch 6.5).

Runs on the AI server worker only (``OAL_REVIEW_DIR`` points at the training
drive's review folder mounted on this box). The hub never touches media; the
generated ``index.html`` is fully self-contained and opens in any local
browser, mirroring the house A/B review page style.
"""

from __future__ import annotations

import html
import re
import subprocess
from pathlib import Path

_CSS = """
body { font-family: system-ui, sans-serif; margin: 24px; background: #111; color: #eee; }
h1 { margin-bottom: 4px; }
.summary { color: #bbb; margin-bottom: 20px; }
table { border-collapse: collapse; width: 100%; }
th, td { border: 1px solid #333; padding: 10px; vertical-align: top; text-align: left; }
th { width: 240px; background: #1b1b1b; }
audio { width: 260px; }
.p { color: #aaa; font-weight: normal; font-size: 12px; margin-top: 6px; }
.m { color: #8ab4f8; font-size: 12px; margin-top: 4px; }
"""

_REF_SECONDS = 45


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-") or "x"


def review_bundle_dir(review_dir: str | Path | None, bundle_id: str) -> Path | None:
    raw = str(review_dir or "").strip()
    if not raw:
        return None
    out = Path(raw) / bundle_id
    out.mkdir(parents=True, exist_ok=True)
    return out


def write_reference_clips(session, bundle, dest: Path, *, ffmpeg_bin: str = "ffmpeg",
                          limit: int = 2) -> list[dict]:
    """Trim short excerpts of the trained-from tracks into the review folder.

    Picks manifest entries that actually carry lyrics (voice training material),
    copies ~45 s starting at 45 s so a vocal passage lands in the clip. Any
    missing/unreachable source is skipped silently — review must never fail a
    finished training/eval job.
    """
    from .models import MlDataset

    dataset_id = (bundle.bundle_json or {}).get("dataset_id")
    ds = session.get(MlDataset, dataset_id) if dataset_id else None
    refs: list[dict] = []
    if ds is None:
        return refs
    entries = [e for e in (ds.manifest_json or {}).get("entries", []) if e.get("lyrics")]
    for i, entry in enumerate(entries[:limit]):
        src = Path(entry.get("path") or "")
        if not src.is_file():
            continue
        out = dest / f"reference-{i + 1}-{slug(entry.get('caption') or src.stem)}.mp3"
        if out.exists():
            refs.append({"file": out.name, "label": entry.get("caption") or src.stem})
            continue
        try:
            done = subprocess.run(
                [ffmpeg_bin, "-y", "-v", "error", "-ss", str(_REF_SECONDS),
                 "-t", str(_REF_SECONDS), "-i", str(src), "-c:a", "libmp3lame",
                 "-q:a", "4", str(out)], capture_output=True, timeout=120, check=False)
        except (OSError, subprocess.TimeoutExpired):
            done = None
        if done is not None and done.returncode == 0 and out.is_file() and out.stat().st_size > 1000:
            refs.append({"file": out.name, "label": entry.get("caption") or src.stem})
        else:
            out.unlink(missing_ok=True)
    return refs


def build_review_page(dest: Path, *, bundle: dict, samples: list[dict],
                      references: list[dict] | None = None) -> str:
    """(Re)write index.html for one bundle's review folder; returns its path."""
    prompts: dict[str, dict] = {}
    for s in samples:
        row = prompts.setdefault(s.get("prompt") or "p", {"caption": s.get("caption") or ""})
        row[s.get("mode") or "?"] = s
    acceptance = dest / "acceptance-sample.mp3"

    lines: list[str] = []
    lines.append("<!doctype html><html lang='en'><head><meta charset='utf-8'>")
    lines.append("<meta name='viewport' content='width=device-width, initial-scale=1'>")
    lines.append(f"<title>Review — {html.escape(str(bundle.get('name')))} "
                 f"{html.escape(str(bundle.get('version')))}</title>")
    lines.append(f"<style>{_CSS}</style></head><body>")
    lines.append(f"<h1>{html.escape(str(bundle.get('name')))} "
                 f"{html.escape(str(bundle.get('version')))}</h1>")
    meta = (f"kind={html.escape(str(bundle.get('kind')))} · base "
            f"{html.escape(str(bundle.get('base_model')))} · sha "
            f"{html.escape(str(bundle.get('sha256') or '')[:12])} · seed "
            f"{html.escape(str(bundle.get('seed', 42)))} · "
            f"{html.escape(str(bundle.get('duration_seconds', '')))}s clips · "
            "baseline = no adapter, candidate = adapter loaded (same seeds/prompts)")
    lines.append(f"<div class='summary'>{meta}</div>")
    lines.append("<table><tr><th>Prompt</th><th>Baseline</th><th>Candidate</th></tr>")
    if references:
        cells = "".join(
            f"<div class='m'>{html.escape(r['label'])}</div>"
            f"<audio controls preload='none' src='{html.escape(r['file'])}'></audio>"
            for r in references)
        lines.append(f"<tr><th>Training reference<div class='p'>source audio the "
                     f"adapter was trained from</div></th><td colspan='2'>{cells}</td></tr>")
    if acceptance.is_file():
        lines.append("<tr><th>Acceptance sample<div class='p'>post-training gate "
                     "inference stored with the attempt</div></th>"
                     "<td colspan='2'><audio controls preload='none' "
                     "src='acceptance-sample.mp3'></audio></td></tr>")
    for name, row in sorted(prompts.items()):
        cells = []
        for mode in ("baseline", "candidate"):
            s = row.get(mode)
            if s and (dest / str(s.get("file"))).is_file():
                sha = str(s.get("sha256") or "")[:8]
                cells.append(f"<div class='m'>{mode} · {s.get('bytes', 0)} B · sha {sha}</div>"
                             f"<audio controls preload='none' "
                             f"src='{html.escape(str(s['file']))}'></audio>")
            else:
                cells.append("<span class='p'>missing</span>")
        cap = html.escape(str(row.get("caption") or ""))
        lines.append(f"<tr><th>{html.escape(name)}<div class='p'>{cap}</div></th>"
                     f"<td>{cells[0]}</td><td>{cells[1]}</td></tr>")
    lines.append("</table></body></html>")
    page = dest / "index.html"
    page.write_text("\n".join(lines), encoding="utf-8")
    return str(page)
