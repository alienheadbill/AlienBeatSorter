import time

import numpy as np
import soundfile as sf

from beatsorter.player import Player


class FakeStream:
    def __init__(self, sr, channels, callback):
        self.sr, self.channels, self.callback = sr, channels, callback
        self.started = self.closed = False

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def close(self):
        self.closed = True

    def pull(self, frames):
        out = np.zeros((frames, self.channels), dtype="float32")
        self.callback(out, frames, None, None)
        return out


def _player(tmp_path, seconds=2.0, sr=1000):
    streams = []

    def factory(sr_, ch, cb):
        s = FakeStream(sr_, ch, cb)
        streams.append(s)
        return s

    f = tmp_path / "beat.wav"
    sf.write(str(f), np.full((int(seconds * sr), 2), 0.5, dtype="float32"), sr)
    p = Player(stream_factory=factory)
    started = []
    p.play(f, on_started=started.append, on_error=lambda m: started.append(m))
    for _ in range(200):
        if started:
            break
        time.sleep(0.01)
    assert started and started[0] == seconds
    p.set_volume(1.0)
    return p, streams[0]


def test_play_pause_resume_stop(tmp_path):
    p, s = _player(tmp_path)
    assert s.started and p.is_playing()
    assert np.allclose(s.pull(500), 0.5)
    assert abs(p.position() - 0.5) < 1e-6
    p.pause()
    assert np.allclose(s.pull(500), 0.0) and abs(p.position() - 0.5) < 1e-6  # holds still
    p.toggle_pause()
    assert np.allclose(s.pull(100), 0.5) and abs(p.position() - 0.6) < 1e-6
    p.stop()
    assert p.path is None and s.closed and not p.is_playing()


def test_seek_volume_end_and_loop(tmp_path):
    p, s = _player(tmp_path)
    p.seek(1.5)
    p.set_volume(0.5)
    out = s.pull(700)  # 500 frames left, then silence
    assert np.allclose(out[:500], 0.25) and np.allclose(out[500:], 0.0)
    assert p.ended and not p.is_playing() and p.path is not None
    p.resume()  # play again from the start after finishing
    assert not p.ended and p.position() == 0.0
    p.loop = True
    p.seek(1.9)
    out = s.pull(300)  # wraps around
    assert np.allclose(out, 0.25) and not p.ended and abs(p.position() - 0.2) < 1e-6
    p.seek(-5)
    assert p.position() == 0.0
    p.seek(99)
    assert abs(p.position() - 2.0) < 1e-6


def test_pause_while_loading_is_kept(tmp_path):
    import numpy as np
    import soundfile as sf
    from beatsorter import player as pm
    f = tmp_path / "slow.wav"
    sf.write(str(f), np.zeros((1000, 2), dtype="float32"), 1000)
    real_load = pm._load
    gate = __import__("threading").Event()
    pm._load = lambda path: (gate.wait(5), real_load(path))[1]
    try:
        p = Player(stream_factory=FakeStream)
        done = []
        p.play(f, on_started=done.append, on_error=done.append)
        assert p.loading() and p.active()
        p.pause()
        assert not p.active()
        gate.set()
        for _ in range(200):
            if done:
                break
            time.sleep(0.01)
        assert p.paused and not p.is_playing()  # still paused once loaded
    finally:
        pm._load = real_load
