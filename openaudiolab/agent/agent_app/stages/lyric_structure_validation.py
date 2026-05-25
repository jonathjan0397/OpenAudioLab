import re


def validate(lyrics: str) -> dict:
    lines = lyrics.strip().split("\n") if lyrics else []
    sections = []
    current_section = None

    for line in lines:
        match = re.match(r"\[(.+?)\]", line.strip())
        if match:
            if current_section:
                sections.append(current_section)
            current_section = {"label": match.group(1), "lines": []}
        elif line.strip() and current_section:
            current_section["lines"].append(line.strip())

    if current_section:
        sections.append(current_section)

    return {
        "valid": len(sections) > 0,
        "section_count": len(sections),
        "total_lines": sum(len(s["lines"]) for s in sections),
        "sections": sections,
    }
