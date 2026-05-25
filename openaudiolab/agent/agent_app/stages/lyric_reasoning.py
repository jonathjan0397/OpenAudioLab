def analyze(lyrics: str, request: dict) -> dict:
    lines = lyrics.strip().split("\n") if lyrics else []
    score = 85
    issues = []

    has_chorus = any("[chorus]" in l.lower() for l in lines)
    if not has_chorus:
        issues.append("No chorus detected")
        score -= 5

    if len(lines) < 8:
        issues.append("Short lyrics")
        score -= 5

    return {
        "passed": score >= 80,
        "score": max(0, min(100, score)),
        "mode": request.get("lyric_reasoning_mode", "balanced"),
        "issues": issues,
        "recommended_action": "continue" if score >= 80 else "revise",
    }
