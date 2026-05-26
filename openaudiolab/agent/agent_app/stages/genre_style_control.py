import logging

logger = logging.getLogger("agent.stages.genre_style_control")


def resolve(request: dict) -> dict:
    genre = request.get("genre", "pop")
    mood = request.get("mood", "energetic")
    quality = request.get("quality", "draft")
    vocal_mode = request.get("vocal_mode", "male")

    params = {
        "genre": genre,
        "mood": mood,
        "quality": quality,
        "vocal_mode": vocal_mode,
        "tempo_bpm": _suggest_tempo(genre),
        "key_signature": _suggest_key(genre),
        "time_signature": "4/4",
    }

    logger.info("Resolved genre/style: %s / %s", genre, mood)
    return params


def _suggest_tempo(genre: str) -> int:
    tempos = {
        "pop": 120, "rock": 130, "hip_hop": 95, "rap": 95,
        "electronic": 128, "edm": 128, "house": 126, "techno": 130,
        "jazz": 110, "blues": 80, "country": 100, "folk": 100,
        "classical": 90, "rnb": 85, "soul": 85, "metal": 150,
        "punk": 170, "reggae": 80, "latin": 120, "ambient": 70,
        "lo_fi": 85, "drill": 140, "trap": 140,
    }
    return tempos.get(genre.lower(), 120)


def _suggest_key(genre: str) -> str:
    keys = {
        "pop": "C major", "rock": "E minor", "hip_hop": "C# minor",
        "electronic": "F minor", "jazz": "Bb major", "blues": "E major",
        "country": "G major", "classical": "C minor", "ambient": "D major",
    }
    return keys.get(genre.lower(), "C major")