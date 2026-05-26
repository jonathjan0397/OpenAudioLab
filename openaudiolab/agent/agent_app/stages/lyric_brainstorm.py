import logging

logger = logging.getLogger("agent.stages.lyric_brainstorm")


def suggest(request: dict, lyrics_content: dict) -> dict:
    lyrics_mode = request.get("lyrics_mode", "ai")
    instrumental = request.get("instrumental", False)

    if instrumental:
        return {"suggestions": [], "note": "Instrumental mode — no lyric suggestions"}

    suggestions = []
    if lyrics_mode == "provided":
        provided = request.get("provided_lyrics", "")
        line_count = len(provided.strip().split("\n")) if provided.strip() else 0
        if line_count > 0:
            suggestions.append({
                "type": "structure_note",
                "message": f"Provided lyrics have {line_count} lines. Consider a standard song structure (verse-chorus-verse-chorus-bridge-chorus).",
            })
    elif lyrics_mode in ("ai", "hybrid"):
        prompt = request.get("prompt", "")
        genre = request.get("genre", "pop")
        suggestions.append({
            "type": "theme_suggestion",
            "message": f"Generate lyrics matching theme: '{prompt}' in {genre} style.",
        })

    result = {
        "suggestions": suggestions,
        "lyrics_mode": lyrics_mode,
    }

    logger.info("Brainstorm suggestions: %d", len(suggestions))
    return result