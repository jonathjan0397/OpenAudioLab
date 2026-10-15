"""FFmpeg-backed audio processing helpers (milestone 4).

Containers use reviewed FFmpeg builds; commercial permission and
distribution/linking obligations are tracked separately from encoder
availability (docs/OUTPUT_SPEC.md).
"""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import wave
import zipfile
from dataclasses import dataclass


class AudioToolError(Exception):
    pass


@dataclass(frozen=True)
class AudioProbe:
    codec: str
    sample_rate: int | None
    channels: int | None
    duration_seconds: float | None
    bit_rate: int | None
    sample_count: int | None = None


def tool_version(binary: str) -> str:
    try:
        out = subprocess.run(
            [binary, "-version"], capture_output=True, text=True, timeout=10, check=True
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise AudioToolError(f"{binary} is not available.") from exc
    first = out.splitlines()[0] if out else ""
    return first.split("version")[-1].split()[0] if "version" in first else first


def probe_wav(body: bytes) -> AudioProbe | None:
    """Validate a PCM WAV with the stdlib reader. None when not WAV."""
    try:
        with wave.open(io.BytesIO(body), "rb") as reader:
            frames = reader.getnframes()
            rate = reader.getframerate()
            return AudioProbe(
                codec=f"pcm_s{reader.getsampwidth() * 8}le",
                sample_rate=rate,
                channels=reader.getnchannels(),
                duration_seconds=frames / rate if rate else None,
                bit_rate=rate * reader.getnchannels() * reader.getsampwidth() * 8,
                sample_count=frames,
            )
    except (wave.Error, EOFError):
        return None


def probe_with_ffprobe(ffprobe_bin: str, body: bytes) -> AudioProbe:
    try:
        proc = subprocess.run(
            [ffprobe_bin, "-v", "error", "-print_format", "json",
             "-show_streams", "-show_format", "-i", "pipe:0"],
            input=body,
            capture_output=True,
            timeout=60,
        )
    except OSError as exc:
        raise AudioToolError(f"{ffprobe_bin} is not available.") from exc
    if proc.returncode != 0:
        raise AudioToolError("ffprobe could not decode the audio.")
    data = json.loads(proc.stdout.decode("utf-8", "replace") or "{}")
    streams = [s for s in data.get("streams", []) if s.get("codec_type") == "audio"]
    if not streams:
        raise AudioToolError("No audio stream found.")
    stream = streams[0]
    fmt = data.get("format", {})
    duration = stream.get("duration") or fmt.get("duration")
    return AudioProbe(
        codec=stream.get("codec_name", "unknown"),
        sample_rate=int(stream["sample_rate"]) if stream.get("sample_rate", "").isdigit() else None,
        channels=stream.get("channels"),
        duration_seconds=float(duration) if duration else None,
        bit_rate=int(fmt["bit_rate"]) if fmt.get("bit_rate", "").isdigit() else None,
    )


def probe_audio(body: bytes, ffprobe_bin: str) -> AudioProbe:
    wav = probe_wav(body)
    if wav is not None:
        return wav
    return probe_with_ffprobe(ffprobe_bin, body)


def encode_mp3(ffmpeg_bin: str, wav_body: bytes, bitrate_kbps: int) -> bytes:
    return _ffmpeg_transcode(ffmpeg_bin, wav_body, ["-codec:a", "libmp3lame", "-b:a", f"{bitrate_kbps}k"], "mp3")


def encode_wav(ffmpeg_bin: str, body: bytes) -> bytes:
    return _ffmpeg_transcode(ffmpeg_bin, body, ["-codec:a", "pcm_s16le"], "wav")


def _ffmpeg_transcode(ffmpeg_bin: str, body: bytes, codec_args: list[str], muxer: str) -> bytes:
    try:
        proc = subprocess.run(
            [ffmpeg_bin, "-v", "error", "-i", "pipe:0", *codec_args, "-f", muxer, "pipe:1"],
            input=body,
            capture_output=True,
            timeout=300,
        )
    except OSError as exc:
        raise AudioToolError(f"{ffmpeg_bin} is not available.") from exc
    if proc.returncode != 0:
        raise AudioToolError(f"{muxer} encoding failed.")
    return proc.stdout


def build_stems_zip(stems: dict[str, bytes], manifest: dict) -> bytes:
    """Safe server-generated names only; no arbitrary client paths."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for category, body in stems.items():
            archive.writestr(f"stems/{category}.wav", body)
        archive.writestr("manifest.json", json.dumps(manifest, indent=2))
    return buffer.getvalue()
