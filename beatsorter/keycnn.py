"""Neural-network key detection, in plain NumPy.

This runs the key-recognition network from the madmom research library
(Korzeniowski & Widmer, "Genre-Agnostic Key Classification with
Convolutional Neural Networks", ISMIR 2018). madmom doesn't install on
Windows, so its trained weights were exported to assets/key_cnn.npz and
the network is re-created here. Checked to give the same answers as
madmom on the user's beats.

Model license: the trained weights are from madmom's models, released
under CC BY-NC-SA 4.0 (non-commercial use only). Fine for a personal tool;
remove this module before ever selling or commercially distributing
Beat Sorter.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from .keys import Key

_MODEL = Path(__file__).parent / "assets" / "key_cnn.npz"
_NET: Optional[Dict[str, np.ndarray]] = None

SR = 44100
FRAME = 8192
FPS = 5

# Output order of the network: A major .. G# major, then A minor .. G# minor
# (madmom's key_prediction_to_label ordering).
_ROOTS_FROM_A = [9, 10, 11, 0, 1, 2, 3, 4, 5, 6, 7, 8]


def _net() -> Dict[str, np.ndarray]:
    global _NET
    if _NET is None:
        with np.load(_MODEL, allow_pickle=False) as z:
            _NET = {k: z[k] for k in z.files}
    return _NET


def spectrogram(y: np.ndarray) -> np.ndarray:
    """Log-frequency spectrogram the network expects. y: mono float32 at
    44.1 kHz. Frames are centered (8192 samples, 5 per second)."""
    net = _net()
    hop = SR / FPS
    n = max(1, int(np.ceil(len(y) / hop)))
    pad = np.concatenate([np.zeros(FRAME // 2, np.float32), y.astype(np.float32),
                          np.zeros(FRAME, np.float32)])
    starts = np.round(np.arange(n) * hop).astype(np.int64)
    frames = np.stack([pad[s:s + FRAME] for s in starts])
    mag = np.abs(np.fft.rfft(frames * net["window"], axis=1))[:, :FRAME // 2]
    return np.log10(mag @ net["filterbank"] + 1).astype(np.float32)


def _conv(x: np.ndarray, w: np.ndarray, b: np.ndarray) -> np.ndarray:
    """'valid' convolution. x: (T, F, Cin); w: (Cin, Cout, kh, kw)."""
    kh, kw = w.shape[2], w.shape[3]
    win = sliding_window_view(x, (kh, kw), axis=(0, 1))  # (T', F', Cin, kh, kw)
    flipped = w[:, :, ::-1, ::-1]  # true convolution, like madmom
    return np.einsum("tfckl,cokl->tfo", win, flipped, optimize=True) + b


def _forward(spec: np.ndarray) -> np.ndarray:
    net = _net()
    x = spec[:, :, None].astype(np.float32)
    for step in net["plan"]:
        kind, _, arg = str(step).partition(":")
        if kind == "pad":
            p = int(arg)
            x = np.pad(x, ((p, p), (p, p), (0, 0)))
        elif kind == "conv":
            x = _conv(x, net[f"conv{arg}_w"], net[f"conv{arg}_b"])
        elif kind == "bn":
            v = x * net[f"bn{arg}_scale"] + net[f"bn{arg}_shift"]
            x = np.where(v > 0, v, np.expm1(np.minimum(v, 0)))  # ELU
        elif kind == "pool":
            t, f = (x.shape[0] // 2) * 2, (x.shape[1] // 2) * 2
            x = x[:t, :f].reshape(t // 2, 2, f // 2, 2, -1).max(axis=(1, 3))
        elif kind == "avg":
            x = x.mean(axis=(0, 1))
    e = np.exp(x - x.max())
    return e / e.sum()


def key_probabilities(y: np.ndarray) -> np.ndarray:
    """24 probabilities: index 0-11 major (A..G#), 12-23 minor (A..G#)."""
    if y.size < FRAME:
        y = np.pad(y, (0, FRAME - y.size))
    return _forward(spectrogram(y))


def index_to_key(i: int) -> Key:
    return Key(_ROOTS_FROM_A[i % 12], "major" if i < 12 else "minor")


def probs_by_key(y: np.ndarray) -> np.ndarray:
    """Same 24 probabilities reordered to index pc (C=0) for major and
    12 + pc for minor (the order hpcpkey uses)."""
    p = key_probabilities(y)
    out = np.zeros(24)
    for i in range(24):
        k = index_to_key(i)
        out[k.pc + (12 if k.mode == "minor" else 0)] = p[i]
    return out


def detect(y: np.ndarray) -> Dict[str, object]:
    """Best key and its probability. y: mono at 44.1 kHz."""
    p = key_probabilities(y)
    i = int(np.argmax(p))
    k = index_to_key(i)
    return {"cnn_key": k.name, "cnn_prob": round(float(p[i]), 3)}
