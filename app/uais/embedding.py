"""Voice Identity Analysis embeddings (UAIS).

``mfcc-stats-v1`` is a deterministic log-mel statistics embedder: 26 log-mel
band energies per frame, summarised by mean+std across the recording, plus a
zero-crossing-rate statistic. It is pure Python (runs in the slim API image and
the worker image alike) and is explicitly an *analysis and evaluation*
artifact -- not a generation-conditioning input. Singer-specific embedding
models can be swapped in later behind the same interface; speech
speaker-verification scores are not treated as singing-identity proof.
"""

from __future__ import annotations

import array
import cmath
import math

SAMPLE_RATE = 16000
FRAME = 1024
HOP = 512
N_BANDS = 26
DIM = 2 * N_BANDS + 1


def _fft(values: list[complex]) -> list[complex]:
    n = len(values)
    a = values[:]
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j |= bit
        if i < j:
            a[i], a[j] = a[j], a[i]
    length = 2
    while length <= n:
        step = cmath.exp(-2j * math.pi / length)
        for start in range(0, n, length):
            factor = 1 + 0j
            half = length // 2
            for k in range(half):
                even = a[start + k]
                odd = a[start + k + half] * factor
                a[start + k] = even + odd
                a[start + k + half] = even - odd
                factor *= step
        length <<= 1
    return a


def _mel_edges() -> list[list[tuple[int, float]]]:
    """Triangular mel filterbank edges mapped onto FFT bin indices."""
    def to_mel(hz: float) -> float:
        return 2595.0 * math.log10(1.0 + hz / 700.0)

    def to_hz(mel: float) -> float:
        return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)

    n_bins = FRAME // 2 + 1
    mel_lo, mel_hi = to_mel(0.0), to_mel(SAMPLE_RATE / 2)
    points = [to_hz(mel_lo + (mel_hi - mel_lo) * i / (N_BANDS + 1)) for i in range(N_BANDS + 2)]
    bins = [min(n_bins - 1, int(p / (SAMPLE_RATE / 2) * (n_bins - 1))) for p in points]
    filters: list[list[tuple[int, float]]] = []
    for band in range(N_BANDS):
        lo, mid, hi = bins[band], bins[band + 1], bins[band + 2]
        cells: list[tuple[int, float]] = []
        for b in range(lo, mid):
            w = (b - lo) / max(1, mid - lo)
            if w > 0:
                cells.append((b, w))
        for b in range(mid, hi):
            w = (hi - b) / max(1, hi - mid)
            if w > 0:
                cells.append((b, w))
        filters.append(cells)
    return filters


_FILTERS = _mel_edges()
_WINDOW = [0.5 - 0.5 * math.cos(2 * math.pi * i / (FRAME - 1)) for i in range(FRAME)]


def embed_pcm16(samples: array.array) -> list[float]:
    """Log-mel statistics embedding of mono 16 kHz s16le PCM."""
    if len(samples) < FRAME:
        samples = samples + array.array("h", [0] * (FRAME - len(samples)))
    band_means = [0.0] * N_BANDS
    band_sqmeans = [0.0] * N_BANDS
    zcr_total = 0.0
    frames = 0
    for start in range(0, len(samples) - FRAME + 1, HOP):
        frame = samples[start:start + FRAME]
        windowed = [complex(frame[i] * _WINDOW[i], 0.0) for i in range(FRAME)]
        spectrum = _fft(windowed)
        n_bins = FRAME // 2 + 1
        power = [(spectrum[b].real ** 2 + spectrum[b].imag ** 2) / (FRAME * FRAME) for b in range(n_bins)]
        for band, cells in enumerate(_FILTERS):
            energy = sum(power[b] * w for b, w in cells)
            log_e = math.log(1e-10 + energy)
            band_means[band] += log_e
            band_sqmeans[band] += log_e * log_e
        crossings = sum(
            1 for i in range(1, FRAME) if (frame[i - 1] < 0) != (frame[i] < 0)
        ) / (FRAME - 1)
        zcr_total += crossings
        frames += 1
    frames = max(1, frames)
    means = [band_means[b] / frames for b in range(N_BANDS)]
    stds = []
    for b in range(N_BANDS):
        var = max(0.0, band_sqmeans[b] / frames - means[b] * means[b])
        stds.append(math.sqrt(var))
    vector = means + stds + [zcr_total / frames]
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [round(v / norm, 6) for v in vector]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def centroid(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        return []
    dim = len(vectors[0])
    mean = [sum(v[d] for v in vectors) / len(vectors) for d in range(dim)]
    norm = math.sqrt(sum(v * v for v in mean)) or 1.0
    return [round(v / norm, 6) for v in mean]
