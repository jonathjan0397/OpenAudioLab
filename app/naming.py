"""Friendly track naming: URL slugs + download filenames.

`assets.slug` is a globally-unique, url-safe handle derived from the title so a
shared track has a clean permalink (/track/<slug>). The slug is assigned once at
creation and then left stable (renaming a title does not break old links).
"""

from __future__ import annotations

import re
import urllib.parse

from sqlalchemy import select

from .models import Asset

_MIME_EXT = {
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mpeg": ".mp3",
    "audio/flac": ".flac",
    "audio/ogg": ".ogg",
    "application/zip": ".zip",
}


def slugify(text: str | None) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text[:60]


def filename_ext(mime: str | None, storage_key: str) -> str:
    ext = _MIME_EXT.get((mime or "").lower())
    if ext:
        return ext
    for known in (".wav", ".mp3", ".flac", ".ogg", ".zip", ".json"):
        if storage_key.endswith(known):
            return known
    return ".bin"


def safe_filename(base: str | None, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", (base or "").strip()).strip("-.")
    return cleaned or (fallback or "track")[:16]


def ensure_unique_slug(session, base: str | None, seed_id: str) -> str:
    """Return a globally-unique url slug for this asset.

    Relies on session autoflush so assets added in the same transaction are
    visible to the uniqueness check (prevents intra-request collisions).
    """
    base_slug = slugify(base) or f"track-{(seed_id or '')[:6]}"
    used = set(
        session.execute(select(Asset.slug).where(Asset.slug.like(f"{base_slug}%"))).scalars()
    )
    if base_slug not in used:
        return base_slug
    candidate = f"{base_slug}-{(seed_id or '')[:4]}"
    if candidate not in used:
        return candidate[:80]
    n = 2
    while True:
        candidate = f"{base_slug[:74]}-{n}"
        if candidate not in used:
            return candidate[:80]
        n += 1


def assign_asset_slug(session, asset: Asset) -> str | None:
    if asset.slug:
        return asset.slug
    asset.slug = ensure_unique_slug(session, asset.title, asset.id)
    return asset.slug


def asset_disposition(asset: Asset) -> str:
    name = safe_filename(asset.slug or asset.title, asset.id) + filename_ext(asset.mime, asset.storage_key)
    ascii_name = name.encode("ascii", "ignore").decode() or (asset.id or "track")
    quoted = urllib.parse.quote(name)
    return f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quoted}'
