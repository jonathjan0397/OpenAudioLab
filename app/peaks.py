"""Waveform peak extraction (stdlib only; runs inside the worker).

Produces a compact JSON document the frontend can render without decoding
audio: fixed-count buckets of normalized peak amplitudes (0..1).
"""

from __future__ import annotations

import array
import io
import json
import math
import wave


def compute_peaks(wav_body: bytes, buckets: int = 200) -> dict:
    with wave.open(io.BytesIO(wav_body), "rb") as wav:
        channels = wav.getnchannels()
        rate = wav.getframerate()
        width = wav.getsampwidth()
        frames = wav.readframes(wav.getnframes())
    if width != 2:
        raise ValueError(f"unsupported sample width {width}")
    samples = array.array("h")
    samples.frombytes(frames)
    if channels > 1:
        samples = samples[::channels]
    total = len(samples)
    if total == 0:
        return {"buckets": 0, "rate": rate, "peaks": []}
    size = max(1, total // buckets)
    peaks: list[float] = []
    for i in range(0, total, size):
        chunk = samples[i : i + size]
        peak = 0
        for value in chunk:
            value = -value if value < 0 else value
            if value > peak:
                peak = value
        peaks.append(round(peak / 32768.0, 4))
    return {
        "buckets": len(peaks),
        "rate": rate,
        "duration_seconds": round(total / rate, 3) if rate else 0.0,
        "peaks": peaks,
    }


def peaks_json(wav_body: bytes, buckets: int = 200) -> bytes:
    return json.dumps(compute_peaks(wav_body, buckets)).encode("utf-8")
