"""Curated style-tag vocabulary (M14c).

Feeds the create widget's suggested tag chips and the published /styles
cheat sheet. Kept deliberately tight: these are prompts ACE-Step responds
to well, researched from Suno/Udio tag conventions and ACE-Step caption
style. LoRA tags and trending track tags are merged in at request time.
"""

CHEATSHEET: dict[str, list[str]] = {
    "Genres": [
        "pop", "indie pop", "rock", "alternative rock", "punk rock", "metal",
        "hip hop", "rap", "trap", "R&B", "soul", "funk", "jazz", "blues",
        "lo-fi", "electronic", "EDM", "house", "techno", "synthwave",
        "ambient", "classical", "orchestral", "folk", "country", "reggae",
        "K-pop", "J-pop", "Afrobeat", "dream pop", "shoegaze", "bossa nova",
    ],
    "Moods": [
        "hopeful", "melancholic", "dreamy", "energetic", "chill", "dark",
        "uplifting", "nostalgic", "romantic", "epic", "moody", "groovy",
        "ethereal", "aggressive", "bittersweet", "euphoric", "somber", "playful",
    ],
    "Eras": [
        "60s", "70s", "80s", "90s", "2000s", "retro", "futuristic", "vintage",
        "Y2K",
    ],
    "Instrumentation": [
        "piano", "acoustic guitar", "electric guitar", "synth", "strings",
        "brass", "808 bass", "drums", "arpeggiator", "choir", "organ",
        "saxophone", "music box", "distorted bass",
    ],
    "Vocals": [
        "male vocals", "female vocals", "duet", "choir vocals",
        "whispered vocals", "falsetto", "raspy vocals", "clean vocals",
        "harmony vocals", "no vocals",
    ],
    "Tempo & Energy": [
        "slow tempo", "mid tempo", "uptempo", "fast tempo", "half-time",
        "four-on-the-floor", "double time", "ballad", "anthemic", "mellow",
    ],
}

ALL_CURATED_TAGS: list[str] = sorted({t for tags in CHEATSHEET.values() for t in tags})
