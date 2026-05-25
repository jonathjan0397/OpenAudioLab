def plan(request: dict) -> dict:
    duration = request.get("duration_seconds", 90)
    return {
        "bpm": 92,
        "key": "D minor",
        "duration_seconds": duration,
        "sections": [
            {"name": "Intro", "duration": 8, "description": "ambient intro"},
            {"name": "Verse 1", "duration": 24, "description": "sparse arrangement"},
            {"name": "Chorus", "duration": 32, "description": "full arrangement"},
            {"name": "Verse 2", "duration": 24, "description": "developed theme"},
            {"name": "Outro", "duration": max(2, duration - 88), "description": "fade out"},
        ],
        "instruments": ["drums", "bass", "guitar", "pads"],
    }
