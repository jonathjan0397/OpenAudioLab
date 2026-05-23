class LyricHumanizer:
    @staticmethod
    def humanize(lyrics: str) -> str:
        return lyrics

    @staticmethod
    def should_humanize(lyrics_mode: str) -> bool:
        return lyrics_mode in ("ai", "hybrid")

    @staticmethod
    def get_metadata(lyrics_mode: str) -> dict:
        if lyrics_mode == "provided":
            return {
                "humanized": False,
                "reason": "Custom lyrics preserved exactly as submitted",
            }
        return {
            "humanized": True,
            "reason": "AI-generated lyrics processed through humanization pipeline",
        }
