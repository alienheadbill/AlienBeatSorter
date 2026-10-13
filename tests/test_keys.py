import numpy as np
import pytest

from beatsorter.keys import Key, parse_key_name

SR = 44100


@pytest.mark.parametrize("text,pc,mode", [
    ("C minor", 0, "minor"), ("Eb major", 3, "major"), ("Fm", 5, "minor"),
    ("D# minor", 3, "minor"), ("G#m", 8, "minor"), ("A# major", 10, "major"),
    ("C#min", 1, "minor"), ("bbm", 10, "minor"), ("F♯ minor", 6, "minor"),
])
def test_parse_key_name_spellings(text, pc, mode):
    assert parse_key_name(text) == Key(pc, mode)


def test_parse_key_name_rejects_junk():
    for t in ("", "Hm", "C minor 2", "beat"):
        assert parse_key_name(t) is None


def _chords(roots_thirds, seconds=2.0):
    """Sustained triads with a few harmonics: [(root_midi, minor?), ...]."""
    t = np.arange(int(seconds * SR)) / SR
    out = []
    for root, minor in roots_thirds:
        y = np.zeros_like(t)
        for iv in (0, 3 if minor else 4, 7):
            f = 440 * 2 ** ((root + iv - 69) / 12)
            for h in range(1, 5):
                y += np.sin(2 * np.pi * f * h * t) / h
        out.append(y)
    y = np.concatenate(out)
    return (0.2 * y / np.abs(y).max()).astype(np.float32)


def test_hpcp_finds_c_major_progression():
    from beatsorter import hpcpkey
    y = _chords([(60, False), (65, False), (67, False), (60, False)])  # C F G C
    out = hpcpkey.detect(y)
    assert out["hpcp_edma"] == "C major"
    assert out["hpcp_krumhansl"] == "C major"


def test_ensemble_finds_a_minor_progression():
    from beatsorter.analyzer import detect_key
    y = _chords([(57, True), (62, True), (64, False), (57, True)] * 2)  # Am Dm E Am
    out = detect_key(y)
    assert Key(out["key_pc"], out["key_mode"]) == Key(9, "minor")
    assert 0 <= out["key_conf"] <= 1 and out["key_votes"] in (0, 1, 2, 3)


def test_cnn_probabilities_are_a_distribution():
    from beatsorter import keycnn
    p = keycnn.probs_by_key(_chords([(60, False)], seconds=3))
    assert p.shape == (24,) and abs(p.sum() - 1) < 1e-5


def test_essentia_matches_progression_when_available():
    from beatsorter import essentiakey
    if not essentiakey.available():
        pytest.skip("deno not installed")
    out = essentiakey.detect(_chords([(57, True), (62, True), (64, False), (57, True)] * 2))
    assert out["ess_edma"] == "A minor" and out["ess_krumhansl"] == "A minor"


def test_key_works_without_essentia(monkeypatch):
    from beatsorter import analyzer, essentiakey
    monkeypatch.setattr(essentiakey, "_broken", True)
    out = analyzer.detect_key(_chords([(57, True), (62, True), (64, False), (57, True)] * 2))
    assert Key(out["key_pc"], out["key_mode"]) == Key(9, "minor")
    assert "ess_edma" not in out
