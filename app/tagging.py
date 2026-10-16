"""Reference-track identification: Chromaprint fingerprint -> AcoustID lookup.

Stdlib + httpx only. The API container ships ``fpcalc`` (libchromaprint-tools);
lookups hit the public AcoustID web service and need a registered client key
(OAL_ACOUSTID_CLIENT_KEY). All failures degrade to empty results - tagging is
advisory, never a hard dependency of upload.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

ACOUSTID_LOOKUP_URL = "https://api.acoustid.org/v2/lookup"


def fingerprint(path: Path, timeout_seconds: float = 60.0) -> dict[str, Any] | None:
    """Return {"duration": float, "signature": str} or None when fpcalc fails."""
    try:
        completed = subprocess.run(
            ["fpcalc", "-json", str(path)],
            capture_output=True,
            timeout=timeout_seconds,
            check=True,
        )
        data = json.loads(completed.stdout.decode("utf-8"))
        signature = data.get("signature")
        duration = float(data.get("duration") or 0.0)
        if not signature or duration <= 0:
            return None
        return {"duration": duration, "signature": signature}
    except (OSError, subprocess.SubprocessError, ValueError, KeyError):
        return None


def acoustid_lookup(
    signature: str,
    duration: float,
    client_key: str,
    timeout_seconds: float = 15.0,
) -> list[dict[str, Any]]:
    """Best-first recording matches: [{recording_id, artist, title, score}]."""
    if not client_key:
        return []
    import httpx

    try:
        response = httpx.get(
            ACOUSTID_LOOKUP_URL,
            params={"client": client_key, "meta": "recordings", "duration": duration, "signature": signature},
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError):
        return []
    matches: list[dict[str, Any]] = []
    for entry in body.get("results") or []:
        score = float(entry.get("score") or 0.0)
        for recording in (entry.get("recordings") or [])[:3]:
            matches.append(
                {
                    "recording_id": recording.get("id"),
                    "artist": recording.get("artist", ""),
                    "title": recording.get("title", ""),
                    "score": score,
                }
            )
    matches.sort(key=lambda m: m["score"], reverse=True)
    return matches[:5]


def tags_from_matches(matches: list[dict[str, Any]]) -> list[str]:
    """Derive stable tags from the best match: artist:<name>, title:<name>."""
    if not matches:
        return []
    best = matches[0]
    tags = []
    if best.get("artist"):
        tags.append(f"artist:{best['artist']}")
    if best.get("title"):
        tags.append(f"title:{best['title']}")
    return tags
