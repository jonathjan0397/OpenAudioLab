"""Stem separation adapter (milestone 4).

Separation is an explicit operation with its own worker capability: separated
stems are never labeled native. The adapter runs the pinned separator as a
subprocess so the heavy PyTorch runtime stays out of the API process.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Protocol

STEM_CATEGORIES = ("drums", "bass", "other", "vocals")


class SeparatorUnavailable(Exception):
    pass


class Separator(Protocol):
    name: str

    def separate(self, wav_body: bytes) -> dict[str, bytes]:
        """Return category -> aligned WAV bytes. Raises SeparatorUnavailable."""


class NullSeparator:
    """Fail-closed default: no separator configured, no silent substitution."""

    name = "none"

    def separate(self, wav_body: bytes) -> dict[str, bytes]:
        raise SeparatorUnavailable("No stem separator is configured on this worker.")


class DemucsSeparator:
    def __init__(
        self,
        python_bin: str,
        model: str = "htdemucs",
        device: str = "cpu",
        timeout_seconds: float = 900.0,
    ) -> None:
        self.python_bin = python_bin
        self.model = model
        self.device = device
        self.timeout_seconds = timeout_seconds
        self.name = f"demucs-{model}"

    def separate(self, wav_body: bytes) -> dict[str, bytes]:
        if not self.python_bin or not Path(self.python_bin).exists():
            raise SeparatorUnavailable(f"Separator runtime not found: {self.python_bin!r}")
        with tempfile.TemporaryDirectory(prefix="oal-sep-") as workdir:
            root = Path(workdir)
            source = root / "source.wav"
            source.write_bytes(wav_body)
            outdir = root / "out"
            proc = subprocess.run(
                [self.python_bin, "-m", "demucs", "-n", self.model,
                 "--device", self.device, "-o", str(outdir), str(source)],
                capture_output=True,
                timeout=self.timeout_seconds,
            )
            if proc.returncode != 0:
                detail = proc.stderr.decode("utf-8", "replace").strip().splitlines()
                raise RuntimeError(f"demucs failed: {detail[-1] if detail else 'no output'}")
            track_dir = outdir / self.model / "source"
            stems: dict[str, bytes] = {}
            for category in STEM_CATEGORIES:
                path = track_dir / f"{category}.wav"
                if not path.is_file():
                    raise RuntimeError(f"demucs produced no {category} stem.")
                stems[category] = path.read_bytes()
            return stems


def separator_revision(separator: Separator) -> str:
    return f"{separator.name}"
