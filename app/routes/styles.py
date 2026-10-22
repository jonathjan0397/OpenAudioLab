"""Style tag endpoints (M14c): suggested chips + published cheat sheet."""

from __future__ import annotations

import random

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from ..models import Asset
from ..styles_data import ALL_CURATED_TAGS, CHEATSHEET

router = APIRouter(tags=["styles"])


@router.get("/styles/cheatsheet")
def styles_cheatsheet(request: Request) -> JSONResponse:
    with request.app.state.db.session() as session:
        lora_tags = _active_lora_tags(session)
    return JSONResponse(
        {
            "categories": [{"name": name, "tags": tags} for name, tags in CHEATSHEET.items()],
            "lora_tags": lora_tags,
        }
    )


@router.get("/styles/suggest")
def styles_suggest(
    request: Request,
    limit: int = Query(default=4, ge=1, le=12),
    seed: int | None = Query(default=None),
) -> JSONResponse:
    """Shuffled tag chips: curated vocabulary + LoRA tags + trending track tags."""
    from ..models import Lora

    rng = random.Random(seed)
    with request.app.state.db.session() as session:
        lora_tags = _active_lora_tags(session)
        trending = _trending_tags(session)
    lora_set = set(lora_tags)
    trending_set = set(trending)
    pool = [
        {"tag": t, "source": "lora" if t in lora_set else "trending" if t in trending_set else "curated"}
        for t in dict.fromkeys(lora_tags + trending + ALL_CURATED_TAGS)
    ]
    rng.shuffle(pool)
    return JSONResponse({"tags": pool[:limit]})


def _active_lora_tags(session) -> list[str]:
    from ..models import Lora

    rows = list(session.execute(
        select(Lora).where(Lora.state == "active", Lora.visibility != "private")
    ).scalars())
    return [t for l in rows for t in (l.tags_json or [])]


# Catalog-identity namespaces (from reference identification) are not
# generation-style controls and must not surface as public style chips.
_IDENTITY_TAG_PREFIXES = ("artist:", "title:")


def _trending_tags(session, limit: int = 12) -> list[str]:
    counts: dict[str, int] = {}
    for (tags,) in session.execute(
        select(Asset.tags_json).where(Asset.deleted_at.is_(None), Asset.tags_json.isnot(None))
    ):
        for t in tags or []:
            if not t or t.startswith(_IDENTITY_TAG_PREFIXES):
                continue
            counts[t] = counts.get(t, 0) + 1
    ranked = sorted(counts, key=lambda t: -counts[t])
    return ranked[:limit]
