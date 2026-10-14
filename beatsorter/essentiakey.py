"""Essentia's own key detector, run through deno.

Essentia (Music Technology Group, Universitat Pompeu Fabra) has no Python
install for Windows, so Beat Sorter uses its official WebAssembly build
(essentia.js, in assets/essentia) and runs it with deno, the JavaScript
runtime that's already installed for the YouTube downloader. Results are
identical to Python Essentia's KeyExtractor (checked on the user's beats).

One deno process is kept open per worker process and fed one file at a
time. If deno or Essentia isn't available, detect() returns {} and the
other detectors carry on without it.

License: Essentia is AGPL-3.0 (assets/essentia/LICENSE-AGPL-3.0.txt).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Dict, Optional

import numpy as np

SCRIPT = Path(__file__).parent / "assets" / "essentia" / "essentia_key.mjs"
TIMEOUT = 60.0  # seconds per file; very long files take ~1-2 s

_proc: Optional[subprocess.Popen] = None
_lock = threading.Lock()
_broken = False  # stop retrying after a startup failure in this process


def _deno() -> Optional[str]:
    try:
        import deno  # pip package that ships the deno binary
        return deno.find_deno_bin()
    except Exception:
        return shutil.which("deno")


def _readline(p: subprocess.Popen, timeout: float) -> Optional[str]:
    """Read one stdout line, or None on timeout/exit."""
    box = []
    t = threading.Thread(target=lambda: box.append(p.stdout.readline()), daemon=True)
    t.start()
    t.join(timeout)
    if not box or not box[0]:
        return None
    return box[0]


def _start() -> Optional[subprocess.Popen]:
    global _broken
    exe = _deno()
    if not exe or not SCRIPT.exists():
        _broken = True
        return None
    env = dict(os.environ, DENO_NO_UPDATE_CHECK="1", NO_COLOR="1")
    try:
        p = subprocess.Popen(
            [exe, "run", "-q", "--no-config", "--no-lock", "--allow-read", str(SCRIPT)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", env=env,
            # work from the temp folder, never from inside the app (Windows
            # can't update a folder a running program is working in)
            cwd=tempfile.gettempdir(),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError:
        _broken = True
        return None
    from . import procs
    procs.tie_to_app(p.pid)  # Windows: ends with the app, even after a crash
    line = _readline(p, TIMEOUT)
    if not line or '"ready"' not in line:
        p.kill()
        _broken = True
        return None
    return p


def _stop() -> None:
    global _proc
    if _proc is not None:
        try:
            _proc.kill()
        except Exception:
            pass
    _proc = None


def available() -> bool:
    return not _broken and SCRIPT.exists() and _deno() is not None


def detect(y44: np.ndarray) -> Dict[str, object]:
    """Essentia's key with the "edma" and "krumhansl" profiles.
    y44: mono audio at 44.1 kHz. Returns {} if Essentia can't run."""
    global _proc
    if _broken:
        return {}
    fd, tmp = tempfile.mkstemp(suffix=".f32", prefix="beatsorter_")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(np.ascontiguousarray(y44, dtype="<f4").tobytes())
        with _lock:
            for attempt in range(2):  # restart once if the process died
                if _proc is None or _proc.poll() is not None:
                    _proc = _start()
                    if _proc is None:
                        return {}
                try:
                    _proc.stdin.write(tmp + "\n")
                    _proc.stdin.flush()
                except OSError:
                    _stop()
                    continue
                line = _readline(_proc, TIMEOUT)
                if line is None:
                    _stop()
                    continue
                res = json.loads(line)
                if "error" in res:
                    return {}
                return {"ess_edma": res["edma"], "ess_edma_s": round(res["edma_strength"], 3),
                        "ess_krumhansl": res["krumhansl"],
                        "ess_krumhansl_s": round(res["krumhansl_strength"], 3)}
            return {}
    except Exception:
        return {}
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
