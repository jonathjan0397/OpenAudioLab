"""SEO surface: robots.txt + generated sitemap.xml (public, no auth)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import select

from ..models import ArtistProfile, Asset

router = APIRouter(tags=["seo"])

ROBOTS = """User-agent: *
Allow: /
Disallow: /lab
Disallow: /studio
Disallow: /admin
"""


@router.get("/robots.txt", include_in_schema=False)
def robots() -> PlainTextResponse:
    return PlainTextResponse(ROBOTS, media_type="text/plain")


@router.get("/sitemap.xml", include_in_schema=False)
def sitemap(request: Request) -> Response:
    with request.app.state.db.session() as session:
        artists = list(
            session.execute(
                select(ArtistProfile).where(
                    ArtistProfile.sharing_policy == "public",
                    ArtistProfile.deleted_at.is_(None),
                    ArtistProfile.slug.is_not(None),
                )
            ).scalars()
        )
        tracks = list(
            session.execute(
                select(Asset)
                .where(Asset.shared.is_(True), Asset.deleted_at.is_(None), Asset.mime.like("audio/%"))
                .limit(500)
            ).scalars()
        )
    urls = ["/", "/artists"]
    urls += [f"/artists/{a.slug}" for a in artists]
    urls += [f"/tracks/{t.id}" for t in tracks]
    body = "".join(f"<url><loc>{u}</loc></url>" for u in urls)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{body}</urlset>"
    )
    return Response(content=xml, media_type="application/xml")
