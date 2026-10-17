from __future__ import annotations

import numpy as np
import pytest
import soundfile as sf

from app.audio_analysis import analyze_paths, suggest_tags


def _write_click_wav(path, sr=22050, seconds=8.0, bpm=120.0, freq=220.0):
    t = np.linspace(0.0, seconds, int(sr * seconds), endpoint=False)
    tone = 0.4 * np.sin(2 * np.pi * freq * t)
    clicks = (t % (60.0 / bpm) < 0.01).astype(float)
    sf.write(path, (tone * (0.3 + clicks)).astype(np.float32), sr)


def test_suggest_tags_formats_summary() -> None:
    tags = suggest_tags({"bpm": 110, "key": "A", "mode": "minor", "energy": "mellow", "genres": ["rock"]})
    assert tags == ["rock", "110 bpm", "a minor", "mellow"]


def test_suggest_tags_empty_summary() -> None:
    assert suggest_tags({}) == []


def test_analyze_paths_detects_tempo_and_key(tmp_path) -> None:
    wav = tmp_path / "track0.wav"
    _write_click_wav(str(wav))
    summary = analyze_paths([str(wav)], with_genres=False)
    assert 100 <= summary["bpm"] <= 140
    assert summary["key"] in {"A", "A#", "B", "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#"}
    assert summary["mode"] in {"major", "minor"}
    assert summary["energy"] in {"mellow", "moderate", "energetic"}
    assert f"{summary['bpm']} bpm" in summary["tags"]


def test_analyze_paths_unreadable_file_degrades_gracefully(tmp_path) -> None:
    summary = analyze_paths([str(tmp_path / "missing.wav")], with_genres=False)
    assert summary["tags"] == []


def test_genre_tags_without_musicnn_returns_empty(tmp_path) -> None:
    pytest.importorskip("librosa")
    wav = tmp_path / "track0.wav"
    _write_click_wav(str(wav))
    try:
        import musicnn  # noqa: F401
        pytest.skip("musicnn installed; empty-list path not exercised")
    except ImportError:
        pass
    from app.audio_analysis import genre_tags

    assert genre_tags(str(wav)) == []
