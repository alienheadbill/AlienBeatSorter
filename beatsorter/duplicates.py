"""Find duplicate beats. Read-only: never deletes or changes files.

Two kinds:
* Identical files: byte-for-byte copies (e.g. the same WAV in two folders).
  Found by size, then a quick sample of the bytes, then a full hash, so a
  big library isn't read end to end.
* Same audio, different file: e.g. a WAV and an MP3 of the same beat, or a
  re-download. Found by comparing a short audio fingerprint, only between
  files whose lengths match within a second and a half.
"""

from __future__ import annotations

import hashlib
import warnings
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np

from .pipeline import Record

SAME_AUDIO_THRESHOLD = 0.97  # fingerprint similarity (1.0 = identical)
LENGTH_TOLERANCE = 1.5  # seconds


@dataclass
class DupGroup:
    kind: str  # "identical" | "same audio"
    members: List[int]  # indexes into the records list, best copy first


def _quick_hash(path: Path, size: int) -> str:
    h = hashlib.sha1(str(size).encode())
    with open(path, "rb") as f:
        h.update(f.read(65536))
        if size > 131072:
            f.seek(-65536, 2)
            h.update(f.read(65536))
    return h.hexdigest()


def _full_hash(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fingerprint(path: str, seconds: float = 60.0) -> Optional[np.ndarray]:
    """Coarse log-mel picture of the first minute (silence trimmed), as a
    normalized vector. Different encodings of the same audio look nearly
    identical; different beats don't."""
    import librosa
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            y, sr = librosa.load(path, sr=11025, mono=True, duration=seconds + 5)
        y, _ = librosa.effects.trim(y, top_db=40)
        y = y[: int(seconds * sr)]
        if y.size < sr:
            return None
        M = librosa.feature.melspectrogram(y=y, sr=sr, n_mels=48, hop_length=2048)
        M = librosa.power_to_db(M, ref=np.max)
        v = M.flatten()
        v = (v - v.mean()) / (v.std() + 1e-9)
        return v / (np.linalg.norm(v) + 1e-9)
    except Exception:
        return None


def _similarity(a: np.ndarray, b: np.ndarray) -> float:
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    x, y = a[:n], b[:n]
    return float(np.dot(x, y) / ((np.linalg.norm(x) * np.linalg.norm(y)) + 1e-9))


def _rank(records: List[Record], idx: List[int]) -> List[int]:
    """Copy to keep first: the one with BPM/key in its name (your labeled
    original), then lossless (WAV/FLAC/AIFF) over MP3/OGG, then the bigger
    file. A WAV converted from an MP3 isn't better quality, so the name
    label comes before the format."""
    lossless = {".wav", ".flac", ".aif", ".aiff"}
    return sorted(idx, key=lambda i: (records[i].tags.empty,
                                      records[i].path.suffix.lower() not in lossless,
                                      -records[i].size, str(records[i].path)))


def find_duplicates(records: List[Record],
                    progress: Optional[Callable[[str, int, int], None]] = None,
                    cancel=lambda: False) -> List[DupGroup]:
    report = progress or (lambda *a: None)
    groups: List[DupGroup] = []
    in_group = set()

    # 1. Identical files: size -> quick hash -> full hash.
    by_size: Dict[int, List[int]] = defaultdict(list)
    for i, r in enumerate(records):
        if r.size > 0:
            by_size[r.size].append(i)
    cands = [ix for ix in by_size.values() if len(ix) > 1]
    for n, ix in enumerate(cands, 1):
        if cancel():
            return groups
        by_quick: Dict[str, List[int]] = defaultdict(list)
        for i in ix:
            try:
                by_quick[_quick_hash(records[i].path, records[i].size)].append(i)
            except OSError:
                pass
        for qx in by_quick.values():
            if len(qx) < 2:
                continue
            by_full: Dict[str, List[int]] = defaultdict(list)
            for i in qx:
                try:
                    by_full[_full_hash(records[i].path)].append(i)
                except OSError:
                    pass
            for fx in by_full.values():
                if len(fx) > 1:
                    groups.append(DupGroup("identical", _rank(records, fx)))
                    in_group.update(fx)
        report("Checking identical files", n, len(cands))

    # 2. Same audio in different files (full-length files only).
    full = [i for i, r in enumerate(records)
            if i not in in_group and r.analysis.get("analyzed")
            and r.analysis.get("duration", 0) >= 10]
    full.sort(key=lambda i: records[i].analysis["duration"])
    pairs = []
    for a_pos, i in enumerate(full):  # only neighbors in length can match
        d_i = records[i].analysis["duration"]
        for j in full[a_pos + 1:]:
            if records[j].analysis["duration"] - d_i > LENGTH_TOLERANCE:
                break
            pairs.append((i, j))
    need = sorted({i for p in pairs for i in p})
    fps: Dict[int, Optional[np.ndarray]] = {}
    for n, i in enumerate(need, 1):
        if cancel():
            return groups
        fps[i] = fingerprint(str(records[i].path))
        report("Comparing audio", n, len(need))

    # Union matching pairs into groups.
    parent = {i: i for i in need}

    def root(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, j in pairs:
        if fps.get(i) is not None and fps.get(j) is not None \
                and _similarity(fps[i], fps[j]) >= SAME_AUDIO_THRESHOLD:
            parent[root(i)] = root(j)
    clusters: Dict[int, List[int]] = defaultdict(list)
    for i in need:
        clusters[root(i)].append(i)
    for ix in clusters.values():
        if len(ix) > 1:
            groups.append(DupGroup("same audio", _rank(records, ix)))
    return groups
