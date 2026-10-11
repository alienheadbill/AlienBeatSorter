"""What kind of one-shot is this? Kick, snare, hi-hat, 808...

Two ways, in order:
1. The name: the file name, then its folder names ("Kicks/Hard Kick 3.wav").
   Sample packs almost always name sounds, so this is reliable.
2. The sound, when the name gives nothing away: a rough guess from a few
   simple measurements (how bassy, how noisy, how long it rings). Guesses
   are marked as guesses in the app.
"""

from __future__ import annotations

import re
import warnings
from pathlib import PurePath
from typing import Dict, Optional, Tuple

import numpy as np

TYPES = ["Kicks", "808s", "Snares", "Claps", "Hi-Hats", "Cymbals", "Percussion",
         "Toms", "Vox", "FX", "Bass", "Melodic", "Other"]

# Word patterns per type. Checked in order; the first match wins, so more
# specific types come first ("808 kick" -> Kicks, plain "808" -> 808s).
_NAME_RULES = [
    ("Hi-Hats", r"hi[- ]?hats?|hh|hats?|open ?hat|closed ?hat|oh|ch|hihat"),
    ("Kicks", r"kicks?|kik|bd|bass ?drum"),  # before 808s: "808 kick" is a kick
    ("808s", r"808s?|sub ?bass"),
    ("Snares", r"snares?|snr|sd|rim ?shot"),
    ("Claps", r"claps?|clp|snaps?|finger ?snap"),
    ("Cymbals", r"crash(es)?|rides?|cymbals?|splash"),
    ("Toms", r"toms?"),
    ("Percussion", r"percs?|percussion|shakers?|tamb(ourine)?|congas?|bongos?|cowbells?|"
                   r"rims?|woodblock|guiro|cabasa|triangle|clave"),
    ("Vox", r"vox|vocals?|chants?|adlibs?|ad-libs?|shouts?|voice"),
    ("FX", r"fx|sfx|risers?|impacts?|sweeps?|whoosh|noise|transition|downlifter|uplifter|"
           r"reverse|rev|glitch|stab"),
    ("Bass", r"bass|reese"),
    ("Melodic", r"keys|piano|synth|pluck|pad|lead|bell|guitar|chord|string|flute|brass"),
]
_COMPILED = [(t, re.compile(rf"(?<![a-z0-9])(?:{pat})(?![a-z])", re.I)) for t, pat in _NAME_RULES]


def type_from_name(path) -> Optional[str]:
    """Type from the file name, then from its folder names (nearest first)."""
    p = PurePath(path)
    candidates = [p.stem] + [part for part in reversed(p.parent.parts)][:3]
    for text in candidates:
        text = text.replace("_", " ").replace("-", " ")
        for typ, rx in _COMPILED:
            if rx.search(text):
                return typ
    return None


def sound_features(path: str, max_seconds: float = 3.0) -> Dict[str, float]:
    """A few cheap measurements of a short sound."""
    import librosa

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        y, sr = librosa.load(path, sr=22050, mono=True, duration=max_seconds)
    if y.size < 256 or not np.any(np.abs(y) > 1e-4):
        return {}
    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=256)) ** 2
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
    total = S.sum() + 1e-12
    low = S[freqs < 150].sum() / total  # share of energy below 150 Hz
    high = S[freqs > 5000].sum() / total  # share above 5 kHz
    centroid = float((freqs[:, None] * S).sum() / total)
    flat = float(np.mean(librosa.feature.spectral_flatness(S=np.sqrt(S))))
    env = librosa.feature.rms(y=y, hop_length=256)[0]
    peak = int(np.argmax(env))
    above = np.where(env[peak:] > env[peak] * 0.1)[0]
    ring = (above[-1] if len(above) else 0) * 256 / sr  # seconds until -20 dB
    return {"low": float(low), "high": float(high), "centroid": centroid,
            "flatness": flat, "ring": float(ring), "length": len(y) / sr}


def type_from_sound(f: Dict[str, float]) -> Optional[str]:
    """Rough guess from sound_features(). None if nothing fits well."""
    if not f:
        return None
    low, high, cen, flat, ring = f["low"], f["high"], f["centroid"], f["flatness"], f["ring"]
    if low > 0.55 and ring > 0.45:
        return "808s"  # mostly sub, rings out
    if low > 0.45 and ring <= 0.45:
        return "Kicks"  # mostly sub, short thump
    if high > 0.55 and flat > 0.08 and ring < 0.35:
        return "Hi-Hats"  # very bright and noisy, short
    if high > 0.55 and flat > 0.08 and ring >= 0.35:
        return "Cymbals"  # very bright and noisy, rings out
    if flat > 0.12 and 800 < cen < 5000 and ring < 0.5:
        return "Snares"  # noisy mid-range crack (claps sound similar)
    return None


def classify_shot(path: str, features: Optional[Dict[str, float]] = None) -> Tuple[str, str]:
    """(type, how) where how is "name", "sound" or ""."""
    t = type_from_name(path)
    if t:
        return t, "name"
    t = type_from_sound(features or {})
    if t:
        return t, "sound"
    return "Other", ""
