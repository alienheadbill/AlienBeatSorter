"""BPM / key / tonality detection for one audio file.

analyze_file() is a plain function with no GUI or database dependencies,
so it can run in worker processes and be tested on its own. It returns
raw measurements; decisions (folder, half/double-time correction, "No
Key", review flags) happen later in classifier.py so that changing a
setting never requires re-analyzing your library.
"""

from __future__ import annotations

import os
import struct
import warnings
from typing import Any, Dict, Tuple

import numpy as np

# Bump when the analysis changes so cached results get recomputed.
ANALYSIS_VERSION = 5

SR = 22050
MAX_SECONDS = 90.0  # analyze at most the first 90 seconds of a file
MIN_ANALYZE_SECONDS = 1.0  # shorter files are one-shots: skip analysis
TEMPO_HOP = 128  # ~5.8 ms frames, fine enough for ~0.1 BPM refinement

# Key profiles tuned for electronic/produced music ("edma", Faraldo et al.).
# In testing these beat the classic Krumhansl profiles, mostly by making
# fewer relative major/minor mix-ups.
_MAJOR = np.array([0.1652, 0.0475, 0.0829, 0.0669, 0.0999, 0.0927,
                   0.0529, 0.1316, 0.0522, 0.0744, 0.0694, 0.0643])
_MINOR = np.array([0.1724, 0.0400, 0.0761, 0.1206, 0.0559, 0.0807,
                   0.0400, 0.1325, 0.0814, 0.0537, 0.1010, 0.0805])


def get_duration(path: str) -> float:
    import soundfile as sf
    try:
        return float(sf.info(path).duration)
    except Exception:
        import librosa
        return float(librosa.get_duration(path=path))


def _beat_scores(ac: np.ndarray, fps: float, bpms: np.ndarray) -> np.ndarray:
    """Average onset autocorrelation at 1, 2 and 4 beats for each tempo.
    Looking at several beat multiples is far more precise than one lag."""
    bpms = np.atleast_1d(np.asarray(bpms, dtype=float))
    total = np.zeros_like(bpms)
    count = np.zeros_like(bpms)
    idx = np.arange(len(ac))
    for k in (1, 2, 4):
        lags = k * 60.0 * fps / bpms
        ok = lags < len(ac) - 1
        total[ok] += np.interp(lags[ok], idx, ac)
        count[ok] += 1
    return np.where(count > 0, total / np.maximum(count, 1), 0.0)


def detect_bpm(y: np.ndarray, sr: int) -> Dict[str, float]:
    """Two-step tempo estimate.

    1. A fine grid search finds the tempo *family* (e.g. 70/140/280),
       which it gets right very reliably.
    2. librosa's estimate (which has a prior around 120 BPM) picks the
       octave within that family.
    Half/double-time ambiguity remains possible; the preferred BPM range
    setting folds results into the range you work in.
    """
    import librosa

    hop = TEMPO_HOP
    fps = sr / hop
    oenv = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
    if not np.any(oenv > 0):
        return {"bpm": 0.0, "bpm_conf": 0.0, "pulse": 0.0}

    x = oenv - oenv.mean()
    max_lag = int(4.2 * 60.0 * fps / 50.0)  # 4 beats at 50 BPM
    ac = librosa.autocorrelate(x, max_size=min(max_lag, len(x)))
    if ac[0] <= 0:
        return {"bpm": 0.0, "bpm_conf": 0.0, "pulse": 0.0}
    ac = ac / ac[0]

    grid = np.arange(50.0, 220.0, 0.1)
    family = float(grid[int(np.argmax(_beat_scores(ac, fps, grid)))])

    prior = float(librosa.feature.tempo(onset_envelope=oenv, sr=sr,
                                        hop_length=hop, max_tempo=240)[0])
    octaves = [family * m for m in (0.25, 0.5, 1.0, 2.0, 4.0) if 40 <= family * m <= 240]
    choice = min(octaves, key=lambda b: abs(np.log2(b / prior)))

    fine = np.arange(choice - 1.0, choice + 1.0, 0.02)
    fine_scores = _beat_scores(ac, fps, fine)
    best = float(fine[int(np.argmax(fine_scores))])
    pulse = float(fine_scores.max())

    # Snap to a whole BPM when it fits essentially as well (most beats
    # are made at integer tempos).
    near = float(round(best))
    if abs(near - best) <= 0.35 and _beat_scores(ac, fps, [near])[0] >= pulse * 0.97:
        best = near

    conf = float(np.clip((pulse - 0.10) / 0.40, 0.0, 1.0))
    return {"bpm": round(best, 1), "bpm_conf": round(conf, 3), "pulse": round(pulse, 3)}


# Minor keys get a small head start: in testing on real trap/drill beats
# (almost all minor) this removed several minor-to-major mistakes.
MINOR_BIAS = 0.10


def detect_key(y: np.ndarray, sr: int) -> Dict[str, Any]:
    """Key from the harmonic part of the audio, ignoring the two lowest
    octaves (below ~130 Hz). 808s often sit on a note other than the key's
    root (a flat 2nd or a tritone in dark trap), and including them made
    detection pick keys a semitone too high."""
    import librosa

    y_h = librosa.effects.harmonic(y, margin=1.0)
    total = float(np.sum(y ** 2)) + 1e-12
    harm_ratio = float(np.sqrt(np.sum(y_h ** 2) / total))

    bpo = 36
    C = np.abs(librosa.cqt(y_h, sr=sr, bins_per_octave=bpo, n_bins=bpo * 7,
                           fmin=librosa.note_to_hz("C1")))
    upper = C[2 * bpo:]  # C3 and up
    chroma = librosa.feature.chroma_cqt(C=upper, sr=sr, norm=None,
                                        bins_per_octave=bpo, n_octaves=5)
    profile = chroma.sum(axis=1)
    empty = {"key_pc": -1, "key_mode": "", "key_r": 0.0, "key_margin": 0.0,
             "key_conf": 0.0, "harm_ratio": round(harm_ratio, 3), "chroma_peak": 0.0}
    if profile.sum() <= 0 or np.allclose(profile, profile[0]):
        return empty
    profile = profile / profile.sum()
    chroma_peak = float(profile.max() / profile.mean())  # 1.0 = flat (noise)

    scores = []
    for mode, tmpl, bias in (("major", _MAJOR, 0.0), ("minor", _MINOR, MINOR_BIAS)):
        for pc in range(12):
            r = float(np.corrcoef(profile, np.roll(tmpl, pc))[0, 1])
            scores.append((r + bias, r, pc, mode))
    scores.sort(reverse=True)
    s1, r1, pc, mode = scores[0]
    margin = s1 - scores[1][0]

    conf = float(np.clip((r1 - 0.40) / 0.40, 0, 1) * np.clip(margin / 0.06, 0, 1))
    return {"key_pc": pc, "key_mode": mode, "key_r": round(r1, 3),
            "key_margin": round(margin, 3), "key_conf": round(conf, 3),
            "harm_ratio": round(harm_ratio, 3), "chroma_peak": round(chroma_peak, 3)}


def _wav_header_broken(path: str, reported_seconds: float) -> bool:
    """True if a WAV's header claims far less audio than the file holds
    (typical of an interrupted export)."""
    if not path.lower().endswith(".wav"):
        return False
    try:
        import soundfile as sf
        info = sf.info(path)
        bytes_per_sec = info.samplerate * info.channels * 2  # at least 16-bit
        size = os.path.getsize(path)
        return size > 1_000_000 and size / bytes_per_sec > max(reported_seconds, 0) * 4 + 2
    except Exception:
        return False


def _read_broken_wav(path: str) -> Tuple[np.ndarray, int]:
    """Read PCM audio from a WAV whose 'data' size field is wrong, by
    taking everything after the data chunk header to the end of the file.
    Read-only: the file itself is never changed."""
    with open(path, "rb") as f:
        head = f.read(1 << 16)
        if head[:4] != b"RIFF" or head[8:12] != b"WAVE":
            raise ValueError("not a RIFF/WAVE file")
        i, fmt, data_off = 12, None, None
        while i + 8 <= len(head):
            cid = head[i:i + 4]
            size = struct.unpack("<I", head[i + 4:i + 8])[0]
            if cid == b"fmt ":
                fmt = struct.unpack("<HHIIHH", head[i + 8:i + 24])
            if cid == b"data":
                data_off = i + 8
                break
            i += 8 + size + (size & 1)
        if fmt is None or data_off is None:
            raise ValueError("WAV header too damaged to read")
        tag, channels, sr, _, block, bits = fmt
        f.seek(data_off)
        raw = f.read()
    if tag == 3 and bits == 32:
        x = np.frombuffer(raw[: len(raw) // 4 * 4], dtype="<f4").astype(np.float32)
    elif bits == 16:
        x = np.frombuffer(raw[: len(raw) // 2 * 2], dtype="<i2").astype(np.float32) / 32768
    elif bits == 24:
        b = np.frombuffer(raw[: len(raw) // 3 * 3], dtype=np.uint8).reshape(-1, 3)
        v = (b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8)
             | (b[:, 2].astype(np.int32) << 16))
        v = np.where(v >= 1 << 23, v - (1 << 24), v)
        x = v.astype(np.float32) / (1 << 23)
    elif bits == 32:
        x = np.frombuffer(raw[: len(raw) // 4 * 4], dtype="<i4").astype(np.float32) / (1 << 31)
    else:
        raise ValueError(f"unsupported WAV format ({bits}-bit)")
    x = x[: len(x) // channels * channels].reshape(-1, channels).mean(axis=1)
    return x, sr


def analyze_file(path: str) -> Dict[str, Any]:
    """Analyze one file. Never raises; errors are returned in 'error'."""
    out: Dict[str, Any] = {"path": path, "error": "", "version": ANALYSIS_VERSION}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return _analyze(path, out)


def _analyze(path: str, out: Dict[str, Any]) -> Dict[str, Any]:
    try:
        import librosa

        dur = get_duration(path)
        broken = _wav_header_broken(path, dur)
        if broken:
            x, native_sr = _read_broken_wav(path)
            dur = len(x) / native_sr
            out["warning"] = ("WAV header is damaged (other apps may see this file as "
                              "empty); re-exporting it is recommended")
        out["duration"] = round(dur, 3)
        if dur < MIN_ANALYZE_SECONDS:
            out.update(bpm=0.0, bpm_conf=0.0, key_pc=-1, key_mode="",
                       key_conf=0.0, harm_ratio=0.0, analyzed=False)
            return out
        if broken:
            x = x[: int(MAX_SECONDS * native_sr)]
            y = librosa.resample(x, orig_sr=native_sr, target_sr=SR)
            sr = SR
        else:
            y, sr = librosa.load(path, sr=SR, mono=True, duration=MAX_SECONDS)
        if y.size == 0 or not np.any(np.abs(y) > 1e-4):
            out.update(bpm=0.0, bpm_conf=0.0, key_pc=-1, key_mode="",
                       key_conf=0.0, harm_ratio=0.0, analyzed=True,
                       error="silent or empty audio")
            return out
        out.update(detect_bpm(y, sr))
        out.update(detect_key(y, sr))
        out["analyzed"] = True
    except Exception as e:  # corrupt file, unsupported codec, etc.
        out["error"] = f"{type(e).__name__}: {e}"[:300]
    return out
