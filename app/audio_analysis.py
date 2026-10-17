"""Lightweight audio analysis for auto-tagging uploads (DSP + genre model).

DSP (librosa): tempo, key/mode, energy. Genre: optional MusicNN tagger
(musicnn package); skipped when unavailable. All failures degrade to empty
suggestions so training never blocks on analysis.
"""

from __future__ import annotations

from collections import Counter
from statistics import median

KEY_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_KRUMHANSL_MAJOR = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
_KRUMHANSL_MINOR = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]

GENRE_ALIASES = {
    "rock": "rock", "pop": "pop", "jazz": "jazz", "electronic": "electronic",
    "hip hop": "hip hop", "hip-hop": "hip hop", "rap": "hip hop", "blues": "blues",
    "classical": "classical", "metal": "metal", "punk": "punk", "folk": "folk",
    "country": "country", "reggae": "reggae", "funk": "funk", "soul": "soul",
    "r&b": "r&b", "rnb": "r&b", "latin": "latin", "ambient": "ambient",
    "house": "house", "techno": "techno", "trap": "trap", "indie": "indie",
    "acoustic": "acoustic", "dance": "dance", "edm": "edm",
    "opera": "opera", "indian": "indian", "world": "world", "japanese": "japanese",
    "arabic": "arabic", "irish": "irish", "bossa nova": "bossa nova", "samba": "samba",
    "flamenco": "flamenco", "ska": "ska", "disco": "disco", "trance": "trance",
    "new age": "new age", "gospel": "gospel", "dub": "dub", "celtic": "celtic",
}


def _energy_label(rms: float) -> str:
    if rms < 0.06:
        return "mellow"
    if rms < 0.15:
        return "moderate"
    return "energetic"


def analyze_file(path: str, duration_seconds: float = 30.0) -> dict:
    import numpy as np
    import librosa

    y, sr = librosa.load(path, sr=22050, duration=duration_seconds)
    if y.size == 0:
        return {}
    beat = librosa.beat.beat_track(y=y, sr=sr)
    tempo = float(np.asarray(beat[0] if isinstance(beat, tuple) else beat, dtype=float).ravel()[0])
    rms = float(np.mean(librosa.feature.rms(y=y)))
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr).mean(axis=1)
    chroma = chroma / (np.linalg.norm(chroma) + 1e-9)
    key_idx = int(np.argmax(chroma))
    major_score = float(np.dot(np.roll(_KRUMHANSL_MAJOR, key_idx), chroma))
    minor_score = float(np.dot(np.roll(_KRUMHANSL_MINOR, key_idx), chroma))
    mode = "major" if major_score >= minor_score else "minor"
    return {"bpm": round(tempo), "key": KEY_NAMES[key_idx], "mode": mode, "rms": rms}


def genre_tags(path: str, top_k: int = 3) -> list[str]:
    try:
        from musicnn import tagger
    except Exception:
        return []
    try:
        tags = tagger.top_tags(path, topN=top_k * 4, print_tags=False)
    except Exception:
        return []
    out = []
    for tag in tags or []:
        clean = GENRE_ALIASES.get(str(tag).strip().lower())
        if clean and clean not in out:
            out.append(clean)
        if len(out) >= top_k:
            break
    return out


def analyze_paths(paths: list[str], max_files: int = 3, with_genres: bool = True) -> dict:
    """Aggregate DSP + genre analysis over up to max_files excerpts."""
    bpms, keys, modes, rmss, genres = [], [], [], [], []
    for path in paths[:max_files]:
        try:
            analysis = analyze_file(path)
        except Exception:
            analysis = {}
        if analysis:
            bpms.append(analysis["bpm"])
            keys.append(analysis["key"])
            modes.append(analysis["mode"])
            rmss.append(analysis["rms"])
        if with_genres:
            for tag in genre_tags(path):
                if tag not in genres:
                    genres.append(tag)
    if not bpms:
        return {"genres": genres, "tags": list(genres)}
    key = Counter(keys).most_common(1)[0][0]
    mode = Counter(modes).most_common(1)[0][0]
    rms = median(rmss)
    summary = {
        "bpm": int(median(bpms)),
        "key": key,
        "mode": mode,
        "energy": _energy_label(rms),
        "genres": genres,
    }
    summary["tags"] = suggest_tags(summary)
    return summary


def suggest_tags(summary: dict) -> list[str]:
    tags = list(summary.get("genres", []))
    if summary.get("bpm"):
        tags.append(f"{summary['bpm']} bpm")
    if summary.get("key"):
        tags.append(f"{summary['key']} {summary.get('mode', 'major')}".lower())
    if summary.get("energy"):
        tags.append(summary["energy"])
    return tags
