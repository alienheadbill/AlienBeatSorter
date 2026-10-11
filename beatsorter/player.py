"""Preview playback for the beat browser (sounddevice + soundfile).
No GUI code here. Playback never modifies files."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable, Optional, Tuple


def available() -> Tuple[bool, str]:
    try:
        import sounddevice as sd
        sd.query_devices(kind="output")
        return True, ""
    except Exception as e:
        return False, f"No audio output available ({e})."


def _load(path: Path):
    import numpy as np
    import soundfile as sf

    try:
        data, sr = sf.read(str(path), dtype="float32", always_2d=True)
        if len(data) < sr // 2 and path.suffix.lower() == ".wav":
            raise ValueError("header too short")  # maybe a damaged header
        return data, sr
    except Exception:
        if path.suffix.lower() != ".wav":
            raise
        from .analyzer import _read_broken_wav  # recovers damaged WAV headers
        mono, sr = _read_broken_wav(str(path))
        return np.repeat(mono[:, None], 2, axis=1).astype("float32"), sr


class Player:
    def __init__(self):
        self.path: Optional[Path] = None
        self.duration = 0.0
        self._start = 0.0
        self._token = 0
        self._lock = threading.Lock()

    def play(self, path: Path, on_started: Callable[[float], None],
             on_error: Callable[[str], None]) -> None:
        """Start playing path (stops anything already playing). Loading
        happens on a background thread; callbacks run on that thread."""
        self.stop()
        with self._lock:
            self._token += 1
            token = self._token
            self.path = Path(path)

        def work():
            try:
                import sounddevice as sd
                data, sr = _load(Path(path))
                with self._lock:
                    if token != self._token:  # user picked another beat meanwhile
                        return
                    sd.play(data, sr)
                    self.duration = len(data) / sr
                    self._start = time.monotonic()
                on_started(self.duration)
            except Exception as e:
                with self._lock:
                    if token == self._token:
                        self.path = None
                on_error(f"Can't play this file: {e}")

        threading.Thread(target=work, daemon=True).start()

    def stop(self) -> None:
        with self._lock:
            self._token += 1
            was = self.path
            self.path = None
            self.duration = 0.0
        if was is not None:
            try:
                import sounddevice as sd
                sd.stop()
            except Exception:
                pass

    def position(self) -> float:
        if self.path is None or not self.duration:
            return 0.0
        return min(time.monotonic() - self._start, self.duration)

    def is_playing(self) -> bool:
        return self.path is not None and (not self.duration or self.position() < self.duration)
