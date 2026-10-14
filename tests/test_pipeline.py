"""Scanning: worker crashes must not ruin a whole scan."""
from pathlib import Path

import numpy as np
import soundfile as sf

from beatsorter.config import Settings
from beatsorter.pipeline import analyze_library


def _lib(root: Path, n=5) -> Path:
    src = root / "beats"
    src.mkdir()
    t = np.arange(44100 * 3) / 44100
    for i in range(n):
        y = (0.3 * np.sin(2 * np.pi * (220 + 30 * i) * t)).astype("float32")
        sf.write(src / f"beat {i}.wav", y, 44100)
    return src


def test_a_crashing_file_does_not_break_the_scan(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("BEATSORTER_TEST_CRASH", "beat 2.wav")
    src = _lib(tmp_path)
    recs = analyze_library(Settings(workers=3), src)
    errors = {r.path.name: r.analysis.get("error") for r in recs if r.analysis.get("error")}
    assert list(errors) == ["beat 2.wav"] and "crashed the analyzer" in errors["beat 2.wav"]
    assert sum(1 for r in recs if r.analysis.get("analyzed")) == 4


def test_first_scan_warms_up_once(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    from beatsorter.pipeline import _warm_marker
    src = _lib(tmp_path, n=3)
    recs = analyze_library(Settings(workers=2), src)
    assert all(r.analysis.get("analyzed") for r in recs)
    assert _warm_marker().exists()
