"""Reference-track identification: Chromaprint fingerprint -> AcoustID lookup.

Stdlib + httpx only. The API container ships ``fpcalc`` (libchromaprint-tools);
lookups hit the public AcoustID web service and need a registered client key
(OAL_ACOUSTID_CLIENT_KEY). Tagging is advisory, never a hard dependency of
upload — but failures are reported distinctly from a genuine no-match
(status: ok | no_match | no_key | provider_error), so an outage never looks
like an unknown track.

Contract notes (verified against the documented services, 2026-10-21):
- ``fpcalc -json`` emits the key ``fingerprint`` (not "signature").
- The AcoustID v2 lookup parameter is ``fingerprint=``.
- Recordings carry a credited-artist array (``artists`` with name/joinphrase);
  the singular ``artist`` key is not part of the response contract.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

ACOUSTID_LOOKUP_URL = "https://api.acoustid.org/v2/lookup"
USER_AGENT = "OpenAudioLab/1.0 (+https://openaudiolab.io)"


def fingerprint(path: Path, timeout_seconds: float = 60.0) -> dict[str, Any] | None:
    """Return {"duration": float, "fingerprint": str} or None when fpcalc fails."""
    try:
        completed = subprocess.run(
            ["fpcalc", "-json", str(path)],
            capture_output=True,
            timeout=timeout_seconds,
            check=True,
        )
        data = json.loads(completed.stdout.decode("utf-8"))
        fp = data.get("fingerprint") or data.get("signature")  # legacy key fallback
        duration = float(data.get("duration") or 0.0)
        if not fp or duration <= 0:
            return None
        return {"duration": duration, "fingerprint": fp}
    except (OSError, subprocess.SubprocessError, ValueError, KeyError):
        return None


def credited_artists(recording: dict[str, Any]) -> str:
    """Join the credited-artist array exactly as the response phrases it."""
    artists = recording.get("artists")
    if isinstance(artists, list) and artists:
        parts: list[str] = []
        pending_sep = False
        for i, a in enumerate(artists):
            if not isinstance(a, dict):
                continue
            name = str(a.get("name") or "")
            if not name:
                continue
            if pending_sep:
                parts.append(", ")  # fallback separator when the previous entry had none
            parts.append(name)
            jp = a.get("joinphrase")
            if i < len(artists) - 1:
                if jp:
                    parts.append(str(jp))
                pending_sep = not jp
            else:
                pending_sep = False
        text = "".join(parts)
        if text:
            return text
    return str(recording.get("artist") or "")


def acoustid_lookup(
    fingerprint_str: str,
    duration: float,
    client_key: str,
    timeout_seconds: float = 15.0,
) -> dict[str, Any]:
    """{"status": ok|no_match|no_key|provider_error, "matches": [...], "error"?}.

    Best-first recording matches: [{recording_id, artist, artists, title, score}].
    A provider outage/quota/policy error never degrades to "no match".
    """
    if not client_key:
        return {"status": "no_key", "matches": []}
    if not fingerprint_str:
        return {"status": "provider_error", "matches": [], "error": "missing_fingerprint"}
    import httpx

    try:
        response = httpx.get(
            ACOUSTID_LOOKUP_URL,
            params={"client": client_key, "meta": "recordings", "duration": duration,
                    "fingerprint": fingerprint_str},
            headers={"User-Agent": USER_AGENT},
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        return {"status": "provider_error", "matches": [], "error": type(exc).__name__}
    if body.get("status") == "error":
        return {"status": "provider_error", "matches": [],
                "error": str(body.get("error") or body.get("message") or "acoustid_error")}
    matches: list[dict[str, Any]] = []
    for entry in body.get("results") or []:
        score = float(entry.get("score") or 0.0)
        for recording in (entry.get("recordings") or [])[:3]:
            matches.append(
                {
                    "recording_id": recording.get("id"),
                    "artist": credited_artists(recording),
                    "artists": [a.get("name") for a in (recording.get("artists") or [])
                                if isinstance(a, dict) and a.get("name")],
                    "title": recording.get("title", ""),
                    "score": score,
                }
            )
    matches.sort(key=lambda m: m["score"], reverse=True)
    matches = matches[:5]
    return {"status": "ok" if matches else "no_match", "matches": matches}


def tags_from_matches(matches: list[dict[str, Any]]) -> list[str]:
    """Derive stable identity tags from the best match: artist:<name>, title:<name>.

    These are catalog-identity namespaces, not generation-style tags; public
    suggestion endpoints must keep the identity: prefix namespaces out.
    """
    if not matches:
        return []
    best = matches[0]
    tags = []
    if best.get("artist"):
        tags.append(f"artist:{best['artist']}")
    if best.get("title"):
        tags.append(f"title:{best['title']}")
    return tags
