"""External metadata clients for gpu1 enrichment (Batch 3).

Only ever called from worker operations on the AI server — never from the API
process. Results land as *suggested* claims plus provenance; admin review
promotes them. Politeness intervals come from settings; MusicBrainz requires a
descriptive User-Agent, lrclib is keyless.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "OpenAudioLab/1.0 (self-hosted music catalog enrichment)"


class ExternalError(RuntimeError):
    pass


def get_json(url: str, *, params: dict | None = None, timeout: float = 25.0) -> tuple[int, dict | None]:
    """Return (status, parsed-or-None). Non-2xx -> (code, None); network -> raise."""
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode() or "null")
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except Exception as exc:  # URLError, timeout, JSON
        raise ExternalError(f"{type(exc).__name__}: {exc}") from exc


class RateLimiter:
    def __init__(self, min_interval_seconds: float) -> None:
        self.min_interval = max(0.0, min_interval_seconds)
        self._last = 0.0

    def wait(self) -> None:
        delta = time.monotonic() - self._last
        if delta < self.min_interval:
            time.sleep(self.min_interval - delta)
        self._last = time.monotonic()


def _norm(text: str | None) -> str:
    return re.sub(r"[\W_]+", " ", str(text or "").lower()).strip()


def _feat_stripped(text: str | None) -> str:
    return _norm(re.sub(r"[\(\[&+-]?\s*(feat|ft)\..*$", "", str(text or ""), flags=re.I))


def musicbrainz_score(candidate: dict, artist: str, title: str,
                      duration: float | None) -> float:
    """Cheap deterministic match score, max ~9. Threshold for accept: 6."""
    rec_title = candidate.get("title") or ""
    score = 0.0
    nt, rt = _norm(title), _norm(rec_title)
    if nt == rt:
        score += 4
    elif _feat_stripped(title) and _feat_stripped(title) == _feat_stripped(rec_title):
        score += 3.5
    elif nt and (nt in rt or rt in nt):
        score += 2
    credits = candidate.get("credit") or candidate.get("artist-credit") or []
    mb_artist = "".join(c.get("name", "") if isinstance(c, dict) else str(c) for c in credits) \
        if credits else (candidate.get("artist") or "")
    na = _norm(artist)
    if na and na in _norm(mb_artist):
        score += 3
    elif na and _norm(mb_artist) and _norm(mb_artist) in na:
        score += 2
    length = candidate.get("length")
    if duration and length:
        if abs(length / 1000.0 - duration) <= 3.0:
            score += 2
        elif abs(length / 1000.0 - duration) <= 12.0:
            score += 1
    return score


def musicbrainz_lookup(artist: str, title: str, duration: float | None = None, *,
                       limiter: RateLimiter | None = None, fetcher=get_json,
                       want_genre: bool = True) -> dict:
    """Search MusicBrainz recordings; returns matched candidate (mbid, artist,
    title, genre hint) or {"matched": False, ...}."""
    if limiter:
        limiter.wait()
    query = f'artist:"{artist}" AND recording:"{title}"'
    status, data = fetcher("https://musicbrainz.org/ws/2/recording/",
                           params={"query": query, "fmt": "json", "limit": 8})
    if status != 200 or not data:
        if status == 503:
            raise ExternalError("musicbrainz rate-limited (503)")
        return {"matched": False, "reason": f"http-{status}"}
    best, best_score = None, 0.0
    for rec in (data.get("recordings") or []):
        s = musicbrainz_score(rec, artist, title, duration)
        if s > best_score:
            best, best_score = rec, s
    if not best or best_score < 6:
        return {"matched": False, "reason": "score", "top_score": best_score}
    credits = best.get("credit") or []
    artist_name = "".join(c.get("name", "") if isinstance(c, dict) else str(c) for c in credits) \
        or artist
    genre = _genre_from_tags(best.get("tags"))
    release = (best.get("releases") or [{}])[0]
    year = _year_from(release.get("date"))
    if want_genre and not genre:
        genre, extra_year = release_group_genre(artist, release.get("title"),
                                                fetcher=fetcher, limiter=limiter)
        year = year or extra_year
    return {"matched": True, "mbid": best.get("id"), "artist": artist_name,
            "title": best.get("title"), "genre": genre, "score": best_score,
            "release": release.get("title"), "release_mbid": release.get("id"),
            "year": year, "source": "musicbrainz"}


def _genre_from_tags(tags):
    scored = [(t.get("name") or "", t.get("count") or 0) for t in tags or []]
    return max((g for g in scored if g[1] > 0), default=("", 0))[0] or None


def release_group_genre(artist: str, album: str | None = None, *,
                        limiter: RateLimiter | None = None, fetcher=get_json) -> tuple:
    """Artist(+album) release-group search; genre = top-weighted tag. One call."""
    q = f'artist:"{artist}" AND primarytype:"album"'
    if album:
        q += f' AND "{album}"'
    try:
        if limiter:
            limiter.wait()
        status, data = fetcher("https://musicbrainz.org/ws/2/release-group/",
                               params={"query": q, "fmt": "json", "limit": 5})
        if status != 200 or not data:
            return None, None
        tallies: dict[str, int] = {}
        first_year = None
        for rg in data.get("release-groups") or []:
            if first_year is None:
                first_year = _year_from(rg.get("first-release-date"))
            for tag in rg.get("tags") or []:
                name = (tag.get("name") or "").strip().lower()
                if name:
                    tallies[name] = tallies.get(name, 0) + int(tag.get("count") or 1)
        if not tallies:
            return None, first_year
        return max(tallies, key=tallies.get), first_year
    except ExternalError:
        return None, None


def _year_from(date_str: str | None) -> int | None:
    m = re.search(r"(1[89]\d{2}|20\d{2})", str(date_str or ""))
    return int(m.group(1)) if m else None


def lrclib_lookup(artist: str, title: str, duration: float | None = None,
                  mbid: str | None = None, *,
                  limiter: RateLimiter | None = None, fetcher=get_json) -> dict:
    """lrclib.net exact get, then search fallback. Plain lyrics verbatim."""
    params = {"artist_name": artist, "track_name": title}
    if mbid:
        params["mb_id"] = mbid
    if duration:
        params["duration"] = int(duration)
    if limiter:
        limiter.wait()
    status, data = fetcher("https://lrclib.net/api/get", params=params)
    if status == 200 and isinstance(data, dict):
        if not (data.get("plainLyrics") or "").strip():
            return {"found": False, "reason": "no-plain-lyrics", "id": data.get("id")}
        best = data
    else:
        best = None
    if best is None:
        if limiter:
            limiter.wait()
        status2, listed = fetcher("https://lrclib.net/api/search",
                                  params={"q": f"{artist} {title}"})
        entries = listed if isinstance(listed, list) else []
        candidates = [e for e in entries if _norm(e.get("trackName", "")) == _norm(title)
                      or _feat_stripped(e.get("trackName", "")) == _feat_stripped(title)]
        candidates.sort(key=lambda e: abs((e.get("duration") or 0) - (duration or 0)))
        best = candidates[0] if candidates else None
        if best is None and status2 != 200:
            raise ExternalError(f"lrclib http-{status2}")
    if not best:
        return {"found": False, "reason": "no-match"}
    plain = best.get("plainLyrics") or ""
    if not plain.strip():
        return {"found": False, "reason": "no-plain-lyrics", "id": best.get("id")}
    return {"found": True, "lyrics": plain, "synced": bool(best.get("syncedLyrics")),
            "id": best.get("id"), "artist": best.get("artistName"),
            "title": best.get("trackName"), "source": "lrclib"}


