import re
from typing import Optional


COMMON_SECTION_LABELS = {
    "intro", "verse", "pre-chorus", "prechorus", "chorus",
    "bridge", "outro", "interlude", "hook", "refrain",
    "breakdown", "drop", "build", "post-chorus", "postchorus",
}


class LyricStructureValidator:
    @staticmethod
    def validate(lyrics: str) -> dict:
        lines = lyrics.strip().split("\n")
        sections = []
        current_section = None
        issues = []
        has_section_labels = False

        for line in lines:
            line = line.strip()
            match = re.match(r"\[(.+?)\]", line)
            if match:
                label = match.group(1).lower().strip()
                has_section_labels = True
                if current_section:
                    sections.append(current_section)
                current_section = {"label": match.group(1), "lines": []}
            elif line and current_section:
                current_section["lines"].append(line)
            elif line and not current_section:
                if not any(re.match(r"\[", l.strip()) for l in lines[:5]):
                    issues.append("No section labels found in first 5 lines")

        if current_section:
            sections.append(current_section)

        if not has_section_labels:
            issues.append("No section labels like [Verse], [Chorus] found")

        if not sections:
            issues.append("No sections detected")

        for section in sections:
            if len(section["lines"]) == 0:
                issues.append(f"Section [{section['label']}] is empty")
            if len(section["lines"]) > 20:
                issues.append(f"Section [{section['label']}] has too many lines ({len(section['lines'])})")

        total_lines = sum(len(s["lines"]) for s in sections)
        if total_lines == 0:
            issues.append("No lyric lines found")
        elif total_lines < 4:
            issues.append("Very few lyric lines (less than 4)")

        return {
            "valid": len(issues) == 0,
            "section_count": len(sections),
            "total_lines": total_lines,
            "sections": sections,
            "issues": issues,
            "has_section_labels": has_section_labels,
        }

    @staticmethod
    def validate_provided_lyrics(lyrics: str) -> dict:
        result = LyricStructureValidator.validate(lyrics)
        result["mutated"] = False
        result["preserved_exact"] = True
        return result
