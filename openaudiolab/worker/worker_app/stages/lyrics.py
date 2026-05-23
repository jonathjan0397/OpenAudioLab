def generate(request: dict) -> str:
    prompt = request.get("prompt", "")
    genre = request.get("genre", "")
    mood = request.get("mood", "")
    return f"[Verse 1]\nAI generated lyrics for: {prompt}\nGenre: {genre}, Mood: {mood}\n\n[Chorus]\nThis is the hook\n\n[Verse 2]\nContinuing the story\n\n[Outro]\nFading out"


def generate_hybrid(request: dict, provided_lyrics: str) -> str:
    if provided_lyrics:
        return f"{provided_lyrics}\n\n[Additional Verse]\nAI expanded from user idea"
    return generate(request)
