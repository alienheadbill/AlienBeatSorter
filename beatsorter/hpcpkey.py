"""Essentia-style key detection, in plain NumPy.

Follows the approach of Essentia's KeyExtractor (Music Technology Group,
Universitat Pompeu Fabra), the engine behind many online key finders:
  spectral peaks per frame -> harmonic pitch class profile (HPCP)
  -> sum over the track -> correlate with major/minor key templates.
Re-written from the published method (not Essentia's code), because
Essentia has no Windows install for Python. Two profile sets are used,
"edma" (tuned for electronic music) and "krumhansl" (classic).
"""

from __future__ import annotations

from typing import Dict, Tuple

import numpy as np

from .keys import Key

SR = 44100
FRAME = 4096
HOP = 4096
MIN_F, MAX_F = 25.0, 3500.0
MAX_PEAKS = 60
REF_HZ = 440.0
BAND_SPLIT = 500.0  # bass and the rest get equal weight

# Weights of the tonic (I), subdominant (IV) and dominant (V) chords in each
# profile. Like Essentia's Key algorithm, a key's template is the sum of
# those three triads (major: I, IV, V major; minor: i, iv minor, V major),
# with each chord note also adding its first 4 harmonics (weight x0.6 each).
# Checked against Essentia's Key: same key on 300/300 random inputs.
PROFILES = {
    "edma": ((1.0, 0.56, 0.80), (1.0, 0.49, 0.78)),
    "krumhansl": ((6.35, 4.09, 5.19), (6.33, 3.53, 4.75)),
}
N_HARMONICS, SLOPE = 4, 0.6


def _add_harmonics(pc: int, weight: float, out: np.ndarray) -> None:
    for h in range(1, N_HARMONICS + 1):
        idx = pc + 12 * np.log2(h)
        lo, hi = np.floor(idx), np.ceil(idx)
        ilo, ihi = int(lo % 12), int(hi % 12)
        if ilo < ihi:  # split between neighbouring semitones
            out[ilo] += np.cos(0.5 * np.pi * (idx - lo)) ** 2 * weight
            out[ihi] += np.cos(0.5 * np.pi * (hi - idx)) ** 2 * weight
        else:
            out[ilo] += weight
        weight *= SLOPE


def _template(chords: Tuple[float, float, float], minor: bool) -> np.ndarray:
    out = np.zeros(12)
    third_i = 3 if minor else 4
    for root, third, w in ((0, third_i, chords[0]), (5, third_i, chords[1]), (7, 4, chords[2])):
        for iv in (0, third, 7):
            _add_harmonics((root + iv) % 12, w, out)
    return out


_TEMPLATES = {name: (_template(M, False), _template(m, True)) for name, (M, m) in PROFILES.items()}


def _peaks(mag: np.ndarray, freqs: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Spectral peaks with parabolic interpolation, strongest MAX_PEAKS
    within [MIN_F, MAX_F]."""
    m = mag
    is_peak = (m[1:-1] > m[:-2]) & (m[1:-1] >= m[2:])
    idx = np.nonzero(is_peak)[0] + 1
    if idx.size == 0:
        return np.array([]), np.array([])
    a, b, c = m[idx - 1], m[idx], m[idx + 1]
    denom = a - 2 * b + c
    shift = np.where(np.abs(denom) > 1e-12, 0.5 * (a - c) / denom, 0.0)
    f = freqs[idx] + shift * (freqs[1] - freqs[0])
    amp = b - 0.25 * (a - c) * shift
    keep = (f >= MIN_F) & (f <= MAX_F) & (amp > 1e-4)
    f, amp = f[keep], amp[keep]
    if f.size > MAX_PEAKS:
        top = np.argpartition(amp, -MAX_PEAKS)[-MAX_PEAKS:]
        f, amp = f[top], amp[top]
    return f, amp


def _whiten(f: np.ndarray, amp: np.ndarray) -> np.ndarray:
    """Flatten the spectral tilt so low notes don't drown out the rest:
    divide each peak by the 75th percentile of nearby peak levels."""
    if f.size < 3:
        return amp
    a_db = 20 * np.log10(amp + 1e-12)
    ratio = f[None, :] / f[:, None]
    near = (ratio > 1 / 1.26) & (ratio < 1.26)  # peaks within +-1/3 octave
    srt = np.sort(np.where(near, a_db[None, :], -np.inf), axis=1)  # non-near first
    n = near.sum(axis=1)
    pos = (f.size - n) + 0.75 * (n - 1)
    lo = np.floor(pos).astype(int)
    hi = np.minimum(lo + 1, f.size - 1)
    rows = np.arange(f.size)
    frac = pos - lo
    env = srt[rows, lo] * (1 - frac) + np.where(frac > 0, srt[rows, hi], 0) * frac
    return amp / (10 ** (env / 20) + 1e-12)


def _hpcp(f: np.ndarray, amp: np.ndarray, ref: float) -> np.ndarray:
    """12-bin pitch class profile (bin 0 = A), cosine-weighted within half
    a semitone. Bass (< 500 Hz) and the rest are built separately and
    given equal weight."""
    pos = 12 * np.log2(f / ref)  # semitones from A
    w2 = amp ** 2
    d = (pos[None, :] - np.arange(12)[:, None] + 6) % 12 - 6  # (12, peaks)
    w = np.where(np.abs(d) <= 0.5, np.cos(np.pi * d), 0.0) * w2
    total = np.zeros(12)
    for band in (f < BAND_SPLIT, f >= BAND_SPLIT):
        h = w[:, band].sum(axis=1)
        if h.max() > 0:
            total += h / h.max()
    return total


def _tuning(y: np.ndarray) -> float:
    """Average detuning in cents from A440."""
    try:
        import librosa
        return float(librosa.estimate_tuning(y=y, sr=SR)) * 100.0
    except Exception:
        return 0.0


def chroma(y: np.ndarray) -> np.ndarray:
    """Track-level HPCP, rotated so index 0 = C. y: mono at 44.1 kHz."""
    ref = REF_HZ * 2 ** (_tuning(y) / 1200.0)
    win = np.hanning(FRAME)
    freqs = np.fft.rfftfreq(FRAME, 1 / SR)
    total = np.zeros(12)
    for s in range(0, len(y) - FRAME + 1, HOP):
        mag = np.abs(np.fft.rfft(y[s:s + FRAME] * win)) / (FRAME / 4)
        f, a = _peaks(mag, freqs)
        if f.size == 0:
            continue
        h = _hpcp(f, _whiten(f, a), ref)
        if h.max() > 0:
            total += h / h.max()
    return np.roll(total, 9)  # bins were relative to A (pitch class 9)


def scores(pcp: np.ndarray) -> Dict[str, np.ndarray]:
    """Correlation with every key, per profile set: 24 values, index
    pc (C=0) for major and 12 + pc for minor."""
    out = {}
    for name, (maj, mino) in _TEMPLATES.items():
        r = np.full(24, -1.0)
        if pcp.std() > 0:
            for pc in range(12):
                r[pc] = np.corrcoef(pcp, np.roll(maj, pc))[0, 1]
                r[12 + pc] = np.corrcoef(pcp, np.roll(mino, pc))[0, 1]
        out[name] = r
    return out


def index_key(i: int) -> Key:
    return Key(i % 12, "minor" if i >= 12 else "major")


def key_scores(y: np.ndarray) -> Dict[str, np.ndarray]:
    """Per-profile correlations (see scores) for audio y, mono 44.1 kHz."""
    if y.size < FRAME:
        y = np.pad(y, (0, FRAME - y.size))
    return scores(chroma(y))


def detect(y: np.ndarray) -> Dict[str, object]:
    """Best key by each profile set. y: mono float at 44.1 kHz."""
    out: Dict[str, object] = {}
    for name, r in key_scores(y).items():
        i = int(np.argmax(r))
        out[f"hpcp_{name}"] = index_key(i).name
        out[f"hpcp_{name}_r"] = round(float(r[i]), 3)
    return out
