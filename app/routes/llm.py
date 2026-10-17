"""Task-locked LLM endpoints: lyrics and style prompts (milestone 9)."""

from __future__ import annotations

from typing import Literal

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import Field

from ..deps import owner_from_request
from ..errors import ApiError
from ..llm import LYRICS_SYSTEM, STYLE_SYSTEM, LlmClient
from ..schemas import StrictModel

router = APIRouter(tags=["llm"])


class LyricsRequest(StrictModel):
    prompt: str = Field(default="", max_length=2000)
    mode: Literal["write", "humanize"] = "write"
    lyrics: str = Field(default="", max_length=4000)


class StylePromptRequest(StrictModel):
    description: str = Field(min_length=3, max_length=2000)


def _client(request: Request) -> LlmClient:
    client = getattr(request.app.state, "llm", None)
    if client is None:
        raise ApiError(503, "LLM_DISABLED", "The lyrics assistant is not configured.")
    return client


def _ask(request: Request, system: str, user: str, max_tokens: int) -> str:
    try:
        return _client(request).chat(system, user, max_tokens=max_tokens)
    except httpx.HTTPError as exc:
        raise ApiError(502, "LLM_UNAVAILABLE", "The lyrics assistant is unavailable.", {"detail": str(exc)[:200]})


@router.post("/llm/lyrics")
def llm_lyrics(payload: LyricsRequest, request: Request, owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    if payload.mode == "humanize":
        if not payload.lyrics.strip():
            raise ApiError(422, "LYRICS_REQUIRED", "Provide the lyrics to humanize.")
        user = f"Humanize these lyrics (keep meaning, make them natural and singable):\n{payload.lyrics}"
    else:
        if not payload.prompt.strip():
            raise ApiError(422, "PROMPT_REQUIRED", "Provide a prompt to write lyrics from.")
        user = f"Write song lyrics for: {payload.prompt}"
    text = _ask(request, LYRICS_SYSTEM, user, max_tokens=420)
    return JSONResponse({"text": text, "mode": payload.mode})


@router.post("/llm/style-prompt")
def llm_style_prompt(payload: StylePromptRequest, request: Request, owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    text = _ask(request, STYLE_SYSTEM, payload.description, max_tokens=60)
    return JSONResponse({"style_prompt": text})


class DraftRequest(StrictModel):
    prompt: str = Field(min_length=3, max_length=2000)
    lora_tags: list[str] = Field(default_factory=list, max_length=20)


@router.post("/llm/draft")
def llm_draft(payload: DraftRequest, request: Request, owner_id: str = Depends(owner_from_request)) -> JSONResponse:
    """Easy-mode draft: lyrics + style from a vibe, seeded with LoRA tag vocabulary."""
    import json

    from ..llm import DRAFT_SYSTEM

    vocab = ", ".join(payload.lora_tags[:20]) if payload.lora_tags else ""
    user = f"Vibe or idea: {payload.prompt}"
    if vocab:
        user += f"\nPrefer style tags from this vocabulary when they fit: {vocab}."
    text = _ask(request, DRAFT_SYSTEM, user, max_tokens=460)
    lyrics, style = text.strip(), ""
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        parsed = json.loads(text[start:end])
        lyrics = str(parsed.get("lyrics", "")).strip() or text.strip()
        style = str(parsed.get("style", "")).strip()
    except (ValueError, json.JSONDecodeError):
        pass
    return JSONResponse({"lyrics": lyrics, "style": style})
