from typing import Optional


class LyricReasoning:
    SUPPORTED_MODES = ["off", "fast", "balanced", "strict", "studio"]
    DEFAULT_MODE = "balanced"
    DEFAULT_MIN_SCORE = 80
    DEFAULT_MAX_REVISIONS = 3

    @staticmethod
    def analyze(
        lyrics: str,
        prompt: str,
        genre: str = "",
        mood: str = "",
        mode: str = "balanced",
    ) -> dict:
        if mode == "off":
            return {
                "passed": True,
                "score": 100,
                "mode": "off",
                "issues": [],
                "recommended_action": "continue",
            }

        lines = lyrics.strip().split("\n")
        non_empty = [l for l in lines if l.strip()]
        section_count = sum(1 for l in lines if l.strip().startswith("["))

        issues = []
        score = 85

        if section_count < 2:
            issues.append("Few section labels detected; consider adding more structure")
            score -= 5

        if len(non_empty) < 8:
            issues.append("Very short lyrics; may not fill the requested duration")
            score -= 10

        has_chorus = any("[chorus]" in l.lower() for l in lines)
        if not has_chorus:
            issues.append("No chorus section detected; songs typically benefit from a strong chorus")
            score -= 5

        avg_line_length = sum(len(l) for l in non_empty) / max(len(non_empty), 1)
        if avg_line_length > 80:
            issues.append("Some lines are very long; consider breaking them for better singability")
            score -= 5

        if score >= LyricReasoning.DEFAULT_MIN_SCORE:
            passed = True
            action = "continue"
        else:
            passed = False
            action = "revise"

        return {
            "passed": passed,
            "score": max(0, min(100, score)),
            "mode": mode,
            "issues": issues,
            "recommended_action": action,
            "metrics": {
                "total_lines": len(non_empty),
                "section_count": section_count,
                "has_chorus": has_chorus,
                "avg_line_length": round(avg_line_length, 1),
            },
        }

    @staticmethod
    def get_mode_config(mode: str) -> dict:
        configs = {
            "off": {"min_score": 0, "max_revisions": 0, "checks": []},
            "fast": {"min_score": 70, "max_revisions": 1, "checks": ["structure", "length"]},
            "balanced": {"min_score": 80, "max_revisions": 3, "checks": ["structure", "length", "chorus", "singability"]},
            "strict": {"min_score": 85, "max_revisions": 5, "checks": ["structure", "length", "chorus", "singability", "originality", "narrative"]},
            "studio": {"min_score": 90, "max_revisions": 7, "checks": ["structure", "length", "chorus", "singability", "originality", "narrative", "phonetics"]},
        }
        return configs.get(mode, configs["balanced"])
