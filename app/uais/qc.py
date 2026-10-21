"""Upload quality control for training recordings (UAIS).

Runs in the API process with ffmpeg/ffprobe only (no torch/numpy in the base
API image). Decodes to mono 16 kHz PCM and measures clipping, silence and
overall energy; the original upload bytes are always preserved untouched.
"""

from __future__ import annotations

import array
import json
import math
import subprocess
import tempfile
from pathlib import Path

PCM_SAMPLE_RATE = 16000
_CLIP_LEVEL = 32767 * 0.995
_WINDOW = int(PCM_SAMPLE_RATE * 0.05)  # 50 ms


class QcError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def ffprobe_audio(ffprobe_bin: str, path: Path) -> dict:
    try:
        out = subprocess.run(
            [ffprobe_bin, "-v", "error", "-show_entries",
             "format=duration:stream=sample_rate,channels,codec_name",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise QcError("QC_PROBE_FAILED", "Audio probing failed.") from exc
    if out.returncode != 0:
        raise QcError("QC_CORRUPT", "Audio could not be probed (corrupt or unsupported).")
    data = json.loads(out.stdout or "{}")
    stream = next((s for s in data.get("streams", []) if s.get("sample_rate")), {})
    duration = float(data.get("format", {}).get("duration") or 0.0)
    return {
        "duration_seconds": round(duration, 3),
        "sample_rate": int(stream.get("sample_rate") or 0) or None,
        "channels": int(stream.get("channels") or 0) or None,
        "codec": stream.get("codec_name"),
    }


def decode_pcm16_mono(ffmpeg_bin: str, path: Path, max_seconds: int) -> array.array:
    """Decode to signed 16-bit mono PCM at 16 kHz; raises QcError on failure."""
    try:
        proc = subprocess.run(
            [ffmpeg_bin, "-v", "error", "-i", str(path), "-t", str(max_seconds),
             "-ac", "1", "-ar", str(PCM_SAMPLE_RATE), "-f", "s16le", "-"],
            capture_output=True, timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise QcError("QC_DECODE_FAILED", "Audio decoding failed.") from exc
    if proc.returncode != 0 or not proc.stdout:
        raise QcError("QC_CORRUPT", "Audio could not be decoded (corrupt or silent container).")
    samples = array.array("h")
    samples.frombytes(proc.stdout[: len(proc.stdout) - len(proc.stdout) % 2])
    return samples


def inspect_bytes(body: bytes, ffmpeg_bin: str, ffprobe_bin: str,
                  max_seconds: int, min_seconds: float = 1.0) -> dict:
    """Full QC pass over one upload. Returns a qc_json dict with a verdict."""
    with tempfile.TemporaryDirectory(prefix="oal-qc-") as tmp:
        path = Path(tmp) / "input"
        path.write_bytes(body)
        probe = ffprobe_audio(ffprobe_bin, path)
        samples = decode_pcm16_mono(ffmpeg_bin, path, max_seconds)

    duration = len(samples) / PCM_SAMPLE_RATE
    if duration < min_seconds:
        return {"verdict": "rejected", "reasons": [f"shorter than {min_seconds:g}s after decode"],
                "probe": probe, "checks": {"decoded_duration_seconds": round(duration, 3)}}

    peak = 0
    total_energy = 0.0
    clipped = 0
    windows = 0
    silent_windows = 0
    for start in range(0, len(samples) - _WINDOW + 1, _WINDOW):
        window = samples[start:start + _WINDOW]
        energy = sum(s * s for s in window) / len(window)
        total_energy += energy
        windows += 1
        if math.sqrt(energy) < 1.0:  # near-silence threshold (16-bit LSB scale)
            silent_windows += 1
    for s in samples[::7]:  # strided peak/clipping scan keeps pure-Python cost bounded
        a = abs(s)
        if a > peak:
            peak = a
        if a >= _CLIP_LEVEL:
            clipped += 1
    rms = math.sqrt(total_energy / max(1, windows))
    clipping_ratio = clipped / max(1, len(samples[::7]))
    silence_ratio = silent_windows / max(1, windows)

    reasons: list[str] = []
    verdict = "usable"
    if clipping_ratio > 0.02:
        reasons.append(f"clipping detected ({clipping_ratio:.1%} of scanned samples at peak)")
        verdict = "flagged"
    if silence_ratio > 0.6:
        reasons.append(f"mostly silent ({silence_ratio:.0%} of windows below noise floor)")
        verdict = "flagged" if verdict == "usable" else verdict
    if rms < 8.0:
        reasons.append("overall level is very low")
        verdict = "flagged" if verdict == "usable" else verdict
    if duration > max_seconds - 0.5:
        reasons.append("longer than the configured maximum; truncated for analysis")
    return {
        "verdict": verdict,
        "reasons": reasons,
        "probe": probe,
        "checks": {
            "decoded_duration_seconds": round(duration, 3),
            "clipping_ratio": round(clipping_ratio, 5),
            "silence_ratio": round(silence_ratio, 4),
            "rms": round(rms, 2),
            "peak": peak,
        },
    }
