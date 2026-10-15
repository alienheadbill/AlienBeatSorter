"""Core vs Full editions.

Core ships without yt-dlp, imageio-ffmpeg or deno. These tests make sure
Core still launches and does the whole analysis job, and that the optional
features report themselves as unavailable instead of crashing.
"""

import ast
import importlib.util
from pathlib import Path

import numpy as np
import pytest

PKG = Path(__file__).resolve().parent.parent / "beatsorter"
OPTIONAL = {"yt_dlp", "imageio_ffmpeg", "deno"}


def _module_level_imports(path: Path):
    """Names imported at module scope (not inside a function/class)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in tree.body:  # only direct children = module scope
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def test_optional_deps_are_never_imported_at_startup():
    """Core (which lacks these) must be able to import every module, so the
    optional deps may only be imported lazily, inside functions."""
    offenders = {}
    for py in PKG.rglob("*.py"):
        bad = _module_level_imports(py) & OPTIONAL
        if bad:
            offenders[py.name] = bad
    assert not offenders, f"optional deps imported at module scope: {offenders}"


def test_core_still_detects_bpm_and_key(monkeypatch):
    """With Essentia unavailable (as in Core), BPM and key detection still
    work — key comes from the neural net + the NumPy HPCP voters."""
    from beatsorter import analyzer, essentiakey
    monkeypatch.setattr(essentiakey, "_broken", True)  # as if deno absent
    t = np.arange(44100 * 4) / 44100
    y = 0.2 * (np.sin(2 * np.pi * 220 * t) + np.sin(2 * np.pi * 261.63 * t)
               + np.sin(2 * np.pi * 329.63 * t))  # A minor-ish
    out = analyzer.detect_key(y.astype("float32"))
    assert out["key_pc"] >= 0 and out["key_mode"] in ("major", "minor")
    assert "ess_edma" not in out  # no Essentia vote in Core
    bpm = analyzer.detect_bpm(y.astype("float32"), 44100)
    assert bpm["bpm"] > 0


def test_youtube_download_reports_unavailable_without_crashing(monkeypatch):
    """In Core, yt-dlp/ffmpeg are absent; the downloader must say so."""
    from beatsorter import downloader
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec",
                        lambda n, *a, **k: None if n == "yt_dlp" else real(n, *a, **k))
    ok, why = downloader.available()
    assert ok is False and why and "setup" in why.lower()


def test_player_imports_without_optional_deps():
    from beatsorter import player  # noqa: F401 — playback is a Core feature
    assert hasattr(player, "Player")


def test_bundle_build_keeps_files_librosa_needs_at_runtime():
    """The Windows build slims site-packages. librosa loads its submodules
    via lazy_loader, which reads librosa/__init__.pyi at import time, so the
    build must never delete *.pyi (that broke `import librosa` in the first
    1.12.0 build). It may drop sklearn, which librosa never imports eagerly."""
    import re
    script = (PKG.parent / "packaging" / "build_windows.ps1").read_text(encoding="utf-8")
    code = "\n".join(l for l in script.splitlines() if not l.lstrip().startswith("#"))
    for m in re.finditer(r"-Include\s+([^|\n]+)", code):
        assert ".pyi" not in m.group(1), f"build deletes stub files: {m.group(0)}"
    stub = Path(importlib.util.find_spec("librosa").origin).with_suffix(".pyi")
    assert stub.exists(), "librosa needs __init__.pyi (lazy_loader)"
