"""Preview playback for the beat browser (sounddevice + soundfile).
No GUI code here. Playback never modifies files.

The whole file is loaded into memory and fed to the sound card from a
callback, so pause, resume, seeking, looping and volume are instant.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Optional, Tuple

import numpy as np


def available() -> Tuple[bool, str]:
    try:
        import sounddevice as sd
        sd.query_devices(kind="output")
        return True, ""
    except Exception as e:
        return False, f"No audio output available ({e})."


def _load(path: Path):
    import soundfile as sf

    try:
        data, sr = sf.read(str(path), dtype="float32", always_2d=True)
        if len(data) < sr // 2 and path.suffix.lower() == ".wav":
            raise ValueError("header too short")  # maybe a damaged header
    except Exception:
        if path.suffix.lower() != ".wav":
            raise
        from .analyzer import _read_broken_wav  # recovers damaged WAV headers
        mono, sr = _read_broken_wav(str(path))
        data = mono[:, None].astype("float32")
    if data.shape[1] > 2:  # surround: fold down to stereo
        data = np.stack([data[:, 0::2].mean(axis=1), data[:, 1::2].mean(axis=1)], axis=1)
    return np.ascontiguousarray(data, dtype="float32"), int(sr)


def _open_stream(sr: int, channels: int, callback):
    import sounddevice as sd
    return sd.OutputStream(samplerate=sr, channels=channels, dtype="float32",
                           callback=callback)


class Player:
    """One beat at a time. All methods are safe to call from the GUI thread."""

    def __init__(self, stream_factory=_open_stream):
        self.path: Optional[Path] = None  # loaded (playing or paused) file
        self.duration = 0.0
        self.paused = False
        self.loop = False
        self.volume = 0.9
        self.ended = False  # reached the end (and not looping)
        self._data: Optional[np.ndarray] = None
        self._sr = 44100
        self._pos = 0  # next frame to play
        self._stream = None
        self._token = 0
        self._lock = threading.Lock()
        self._factory = stream_factory

    # ---- sound card callback (runs on the audio thread) ----
    def _fill(self, out: np.ndarray, frames: int) -> None:
        data = self._data
        if data is None or self.paused or self.ended:
            out.fill(0)
            return
        n = 0
        while n < frames:
            take = min(frames - n, len(data) - self._pos)
            if take > 0:
                out[n:n + take] = data[self._pos:self._pos + take] * self.volume
                self._pos += take
                n += take
            if self._pos >= len(data):
                if self.loop and len(data):
                    self._pos = 0
                else:
                    out[n:].fill(0)
                    self.ended = True
                    return

    def _callback(self, outdata, frames, time_info, status):
        self._fill(outdata, frames)

    # ---- controls ----
    def play(self, path: Path, on_started: Callable[[float], None],
             on_error: Callable[[str], None]) -> None:
        """Load and play path from the start (replacing whatever was loaded).
        Loading happens on a background thread; callbacks run there."""
        self.stop()
        with self._lock:
            self._token += 1
            token = self._token
            self.path = Path(path)

        def work():
            try:
                data, sr = _load(Path(path))
                with self._lock:
                    if token != self._token:  # another beat was picked meanwhile
                        return
                    self._data, self._sr, self._pos = data, sr, 0
                    self.duration = len(data) / sr
                    self.ended = False  # (a pause pressed while loading is kept)
                    self._stream = self._factory(sr, data.shape[1], self._callback)
                    self._stream.start()
                on_started(self.duration)
            except Exception as e:
                with self._lock:
                    if token == self._token:
                        self._close()
                        self.path = None
                on_error(f"Can't play this file: {e}")

        threading.Thread(target=work, daemon=True).start()

    def pause(self) -> None:
        if self.path is not None:
            self.paused = True

    def resume(self) -> None:
        if self.path is None:
            return
        if self.ended:  # finished: play again from the start
            self._pos = 0
            self.ended = False
        self.paused = False

    def toggle_pause(self) -> None:
        if self.paused or self.ended:
            self.resume()
        else:
            self.pause()

    def seek(self, seconds: float) -> None:
        if self._data is None:
            return
        frame = int(max(0.0, min(seconds, self.duration)) * self._sr)
        self._pos = min(frame, len(self._data))
        if self._pos < len(self._data):
            self.ended = False

    def set_volume(self, v: float) -> None:
        self.volume = float(max(0.0, min(v, 1.0)))

    def _close(self) -> None:
        s, self._stream = self._stream, None
        if s is not None:
            try:
                s.stop()
                s.close()
            except Exception:
                pass
        self._data = None
        self._pos = 0

    def stop(self) -> None:
        with self._lock:
            self._token += 1
            self._close()
            self.path = None
            self.duration = 0.0
            self.paused = self.ended = False

    # ---- state ----
    def position(self) -> float:
        if self._data is None or not self._sr:
            return 0.0
        return min(self._pos / self._sr, self.duration)

    def loading(self) -> bool:
        return self.path is not None and self._data is None

    def active(self) -> bool:
        """Playing, or about to (loading and not paused): show a Pause button."""
        return self.is_playing() or (self.loading() and not self.paused)

    def is_playing(self) -> bool:
        """Sound is coming out (not paused, not finished, not loading)."""
        return self._data is not None and not self.paused and not self.ended
