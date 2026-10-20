"""Task-locked LLM endpoints: lyrics and style prompts (milestone 9)."""

from __future__ import annotations

from typing import Literal

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import Field

from ..deps import owner_from_request
from ..errors import ApiError
from ..llm import LYRICS_SYSTEM, STYLE_SYSTEM, TITLE_SYSTEM, LlmClient
from ..models import SiteSetting
from ..schemas import StrictModel

router = APIRouter(tags=["llm"])


class LyricsRequest(StrictModel):
    prompt: str = Field(default="", max_length=2000)
    mode: Literal["write", "humanize"] = "write"
    lyrics: str = Field(default="", max_length=4000)


class StylePromptRequest(StrictModel):
    description: str = Field(min_length=3, max_length=2000)


def _llm_base_url(request: Request) -> str:
    try:
        with request.app.state.db.session() as session:
            row = session.get(SiteSetting, "llm_base_url")
        if row is not None and row.value:
            return row.value
    except Exception:
        pass
    return request.app.state.settings.llm_base_url


def _client(request: Request) -> LlmClient:
    base_url = _llm_base_url(request)
    if base_url:
        settings = request.app.state.settings
        return LlmClient(base_url, settings.llm_timeout_seconds, settings.llm_model)
    client = getattr(request.app.state, "llm", None)
    if client is None:
        raise ApiError(503, "LLM_DISABLED", "The lyrics assistant is not configured.")
    return client


def _ask(request: Request, system: str, user: str, max_tokens: int, thinking: bool = False) -> str:
    try:
        return _client(request).chat(system, user, max_tokens=max_tokens, thinking=thinking)
    except httpx.HTTPError as exc:
        from ..errorlog import record_error

        record_error(
            request.app.state.db,
            component="llm",
            error_code="LLM_UNAVAILABLE",
            message=str(exc)[:400],
            exc=exc,
            route="POST /llm",
            http_status=502,
        )
        raise ApiError(502, "LLM_UNAVAILABLE", "The lyrics assistant is unavailable.", {"detail": str(exc)[:200]})


@router.post("/llm/lyrics")
def llm_lyrics(payload: LyricsRequest, request: Request, owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    settings = request.app.state.settings
    if payload.mode == "humanize":
        if not payload.lyrics.strip():
            raise ApiError(422, "LYRICS_REQUIRED", "Provide the lyrics to humanize.")
        user = f"Humanize these lyrics (keep meaning, make them natural and singable):\n{payload.lyrics}"
        thinking = settings.llm_thinking_lyrics_humanize
    else:
        if not payload.prompt.strip():
            raise ApiError(422, "PROMPT_REQUIRED", "Provide a prompt to write lyrics from.")
        user = f"Write song lyrics for: {payload.prompt}"
        thinking = settings.llm_thinking_lyrics_write
    text = _ask(request, LYRICS_SYSTEM, user, max_tokens=1800 if thinking else 420, thinking=thinking)
    return JSONResponse({"text": text, "mode": payload.mode})


@router.post("/llm/style-prompt")
def llm_style_prompt(payload: StylePromptRequest, request: Request, owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    settings = request.app.state.settings
    text = _ask(
        request,
        STYLE_SYSTEM,
        payload.description,
        max_tokens=120 if settings.llm_thinking_style else 60,
        thinking=settings.llm_thinking_style,
    )
    return JSONResponse({"style_prompt": text})


class TitleRequest(StrictModel):
    prompt: str = Field(default="", max_length=2000)
    lyrics: str = Field(default="", max_length=4000)


@router.post("/llm/title")
def llm_title(payload: TitleRequest, request: Request, owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    if not payload.prompt.strip() and not payload.lyrics.strip():
        raise ApiError(422, "TITLE_INPUT_REQUIRED", "Provide a prompt or lyric excerpt.")
    settings = request.app.state.settings
    user = f"Prompt: {payload.prompt.strip()}\nLyrics excerpt: {payload.lyrics.strip()[:1200]}"
    text = _ask(
        request,
        TITLE_SYSTEM,
        user,
        max_tokens=80 if settings.llm_thinking_title else 40,
        thinking=settings.llm_thinking_title,
    )
    return JSONResponse({"title": text.strip().strip('"')[:200]})


class DraftRequest(StrictModel):
    prompt: str = Field(min_length=3, max_length=2000)
    lora_tags: list[str] = Field(default_factory=list, max_length=20)
    duration_seconds: int | None = Field(default=None, ge=10, le=600)
    instrumental: bool = False


@router.post("/llm/draft")
def llm_draft(payload: DraftRequest, request: Request, owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    """Easy-mode draft: lyrics + style from a vibe, seeded with the engine tag vocabulary."""
    import json

    from sqlalchemy import select

    from ..llm import DRAFT_SYSTEM
    from ..models import Lora
    from ..styles_data import ALL_CURATED_TAGS

    with request.app.state.db.session() as session:
        lora_tags = [
            t
            for l in session.execute(select(Lora).where(Lora.state == "active")).scalars()
            for t in (l.tags_json or [])
        ]
    vocab = ", ".join(dict.fromkeys([*payload.lora_tags[:20], *lora_tags, *ALL_CURATED_TAGS]))
    user = f"Vibe or idea: {payload.prompt}"
    if payload.duration_seconds:
        user += f"\nTarget length: about {payload.duration_seconds} seconds."
    if payload.instrumental:
        user += " Instrumental (no lead vocals)."
    user += f"\nAvailable style tags (prefer these): {vocab}."
    thinking = request.app.state.settings.llm_thinking_draft
    text = _ask(request, DRAFT_SYSTEM, user, max_tokens=2600 if thinking else 700, thinking=thinking)
    lyrics, style, mood, title = text.strip(), "", "", ""
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        parsed = json.loads(text[start:end])
        lyrics = str(parsed.get("lyrics", "")).strip() or text.strip()
        style = str(parsed.get("style", "")).strip()
        mood = str(parsed.get("mood", "")).strip().lower()
        title = str(parsed.get("title", "")).strip()[:200]
    except (ValueError, json.JSONDecodeError):
        pass
    return JSONResponse({"lyrics": lyrics, "style": style, "mood": mood, "title": title})
