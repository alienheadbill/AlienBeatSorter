"""End-to-end check of the whole app, driven like a user would.

Builds a small synthetic beat library, opens the real Beat Sorter window
and goes through every feature: scan, build, tags, fixes, the Sorted tab
(My Folders, drag to a folder, renames, layouts), duplicates, FL Studio tag
sync, the player, problem reports, and reopening the app. After each step
it checks the Sorted folder on disk, and at the end that the original
beats were never changed.

Runs automatically on Windows before every release (see RELEASING.md).
Needs a screen; skipped where Tk can't open a window.
"""

import hashlib
import importlib.util
import os
import shutil
import threading
import time
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

HERE = Path(__file__).parent


def _lib_maker():
    spec = importlib.util.spec_from_file_location("mtl", HERE / "make_test_library.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def make_library(root: Path) -> Path:
    m = _lib_maker()
    src = root / "My Beats"
    (src / "Beats").mkdir(parents=True)
    (src / "Loops").mkdir()
    (src / "One Shots").mkdir()
    for bpm, key, mode, name in ((140, "A", "minor", "Midnight 140bpm Am"),
                                 (92, "C", "minor", "boom bap 92 Cm"),
                                 (128, "G", "major", "house idea 128 bpm G major"),
                                 (150, "F#", "minor", "untitled beat 7")):
        sf.write(src / "Beats" / f"{name}.wav", m.make(bpm, key, mode, bars=8), m.SR)
    sf.write(src / "Loops" / "drum loop 90bpm.wav", m.make(90, "C", "minor", bars=4, music=False), m.SR)
    sf.write(src / "One Shots" / "Kick 01.wav", m.kick(int(0.5 * m.SR)).astype(np.float32), m.SR)
    shutil.copy2(src / "Beats" / "boom bap 92 Cm.wav", src / "Beats" / "boom bap 92 Cm copy.wav")
    (src / "Beats" / "notes.txt").write_text("not audio")
    return src


def digest(folder: Path) -> dict:
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.rglob("*") if p.is_file()}


def rels(out: Path) -> set:
    return {str(p.relative_to(out)).replace(os.sep, "/") for p in out.rglob("*")
            if p.is_file() and not p.name.startswith(".beatsorter")}


class FakeCard:
    """Plays audio into nothing, faster than real time (CI has no speakers)."""
    def __init__(self, sr, ch, cb):
        self.ch, self.cb, self.on = ch, cb, False

    def start(self):
        self.on = True

        def run():
            while self.on:
                out = np.zeros((1024, self.ch), "float32")
                self.cb(out, 1024, None, None)
                time.sleep(0.002)
        threading.Thread(target=run, daemon=True).start()

    def stop(self):
        self.on = False

    close = stop


@pytest.fixture
def env(tmp_path, monkeypatch):
    tk = pytest.importorskip("tkinter")
    try:
        probe = new_tk()
        probe.destroy()
    except tk.TclError:
        pytest.skip("no screen available")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    src = make_library(tmp_path)
    out = tmp_path / "My Beats Sorted"
    from beatsorter.config import Settings
    s = Settings(source=str(src), output=str(out), fl_user_data=str(tmp_path / "Image-Line"))
    s.save()
    (tmp_path / "Image-Line" / "FL Studio" / "Settings" / "Browser").mkdir(parents=True)
    return tmp_path, src, out


def new_tk():
    """tk.Tk(), retried: GitHub's Windows machines sometimes fail to read
    Tcl's init files when a test opens several windows in a row."""
    import tkinter as tk
    for attempt in range(6):
        try:
            return tk.Tk()
        except tk.TclError:
            if attempt == 5:
                raise
            time.sleep(1 + attempt)


def open_app(monkeypatch):
    import tkinter as tk
    from beatsorter import gui, theme as T
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: False)
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda *a, **k: None)
    monkeypatch.setattr(gui.messagebox, "showerror", lambda *a, **k: None)
    monkeypatch.setattr(gui.player_mod, "available", lambda: (True, ""))
    from beatsorter import gui_sorted
    asked = []
    monkeypatch.setattr(gui_sorted, "ask_text", lambda *a, **k: asked.append(a) or None)  # "Cancel"
    root = new_tk()
    root.geometry("1200x820")
    app = gui.App(root, T.apply(root))
    app.player._factory = FakeCard
    return root, app


def pump(root, cond, timeout=240.0, what=""):
    end = time.time() + timeout
    while time.time() < end:
        root.update()
        if cond():
            return
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for: {what}")


def wait(root, seconds):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.05)


def idx(app, prefix):
    return next(i for i, r in enumerate(app.records) if r.path.name.startswith(prefix))


def test_whole_app(env, monkeypatch):
    tmp, src, out = env
    originals = digest(src)
    root, app = open_app(monkeypatch)
    try:
        # ---- scan ----
        app._analyze()
        pump(root, lambda: app.records and not app.busy, what="scan")
        names = sorted(r.path.name for r in app.records)
        assert len(names) == 7 and "notes.txt" not in names
        cat = {r.path.name: d for r, d in zip(app.records, app.decisions)}
        assert cat["Kick 01.wav"].category == "One-Shots" and cat["Kick 01.wav"].shot_type == "Kicks"
        assert cat["drum loop 90bpm.wav"].no_key
        assert cat["Midnight 140bpm Am.wav"].bpm == 140 and cat["Midnight 140bpm Am.wav"].key.short == "Am"
        assert cat["untitled beat 7.wav"].key is not None  # detected

        # ---- build ----
        app._build(confirmed=True)
        pump(root, lambda: (out / ".beatsorter").exists() and not app.busy, what="build")
        files = rels(out)
        assert "140-149 BPM/A minor/Midnight 140bpm Am.wav" in files
        assert any(f.startswith("One-Shots/Kicks/") for f in files)
        assert any(f.startswith("090-099 BPM/No Key/drum loop") for f in files)

        # ---- tags (Library tab) ----
        app._show_tab("library")
        app.tree.selection_set(str(idx(app, "Midnight")))
        app._apply_tag("dark")
        assert "Tags/dark/Midnight 140bpm Am.wav" in rels(out)
        app._apply_untag("dark")
        assert "Tags/dark/Midnight 140bpm Am.wav" not in rels(out)

        # ---- fix BPM/key: Sorted folder follows by itself ----
        app.tree.selection_set(str(idx(app, "house idea")))
        app._apply_fix(key="A minor")
        pump(root, lambda: "120-129 BPM/A minor/house idea 128 bpm G major.wav" in rels(out),
             timeout=20, what="fix moves the link")

        # ---- Sorted tab: My Folders, drag to folder, rename, layout ----
        app._show_tab("sorted")
        st = app.sorted_tab
        fid = app.folders.create("Album ideas")
        st.drop_beats([idx(app, "Midnight"), idx(app, "boom bap 92 Cm.")], f"my:{fid}")
        pump(root, lambda: "My Folders/Album ideas/Midnight 140bpm Am.wav" in rels(out),
             timeout=20, what="My Folders link")
        st.drop_beats([idx(app, "boom bap 92 Cm.")], "auto:140-149 BPM\x1fC minor")  # 92 can't fold: asks
        st.drop_beats([idx(app, "Midnight")], "auto:070-079 BPM\x1fA minor")  # 140 -> 70 (half time)
        pump(root, lambda: "070-079 BPM/A minor/Midnight 140bpm Am.wav" in rels(out),
             timeout=20, what="drag to a half-time folder")
        app.s.folder_names["070-079 BPM"] = "Slow"
        st._changed("rename")
        pump(root, lambda: "Slow/A minor/Midnight 140bpm Am.wav" in rels(out), timeout=20,
             what="rename an automatic folder")
        st.layout_var.set("Key → BPM")
        st._set_layout()
        pump(root, lambda: "A minor/Slow/Midnight 140bpm Am.wav" in rels(out), timeout=20,
             what="switch layout")
        app.folders.delete(fid)
        st._changed("deleted")
        pump(root, lambda: not any(f.startswith("My Folders/") for f in rels(out)), timeout=20,
             what="delete My Folder")

        # ---- duplicates ----
        from beatsorter.duplicates import find_duplicates
        groups = find_duplicates(app.records)
        assert any({app.records[i].path.name for i in g.members} >=
                   {"boom bap 92 Cm.wav", "boom bap 92 Cm copy.wav"} for g in groups)

        # ---- FL Studio tag sync (merge, keeps FL's own tags) ----
        from beatsorter import fltags
        tags_file = tmp / "Image-Line" / "FL Studio" / "Settings" / "Browser" / "Tags"
        tags_file.write_text('@TagCase=*,mine\n"C:\\other\\beat.wav",mine\n', encoding="utf-8")
        stats = fltags.sync(tags_file, app._fl_desired())
        text = tags_file.read_text(encoding="utf-8")
        assert stats["files"] >= 5 and '"C:\\other\\beat.wav",mine' in text and "Am" in text

        # ---- player ----
        st.node = "all"
        st.refresh()
        first = st.list.get_children()[0]
        st.list.selection_set(first)
        app._toggle_play(force_play=True)
        pump(root, lambda: app.player.is_playing(), timeout=30, what="playback starts")
        app._transport_play()
        assert app.player.paused and app.transport.play_btn.cget("text") == "▶"
        app._transport_play()
        assert app.player.is_playing()
        app._play_neighbor(1)
        pump(root, lambda: app.player.is_playing(), timeout=30, what="next beat")
        app._stop_play()
        assert app.player.path is None

        # ---- problem report ----
        w = app._report("problem", "Traceback: test error")
        root.update()
        from beatsorter import feedback
        title, body = feedback.compose("problem", "Build crashed", feedback.diagnostics(7, "boom"))
        assert title.startswith("[Bug] Build crashed") and "Beat Sorter" in body
        assert feedback.github_url(title, body).startswith("https://github.com/")
        assert feedback.email_url(title, body).startswith("mailto:")
        assert str(Path.home()) not in body  # personal folder names hidden
        w.destroy()

        # ---- started marker for the updater ----
        wait(root, 1.5)
        from beatsorter.config import app_dir
        from beatsorter.version import __version__
        assert (app_dir() / "started.txt").read_text() == __version__
    finally:
        app.player.stop()
        root.destroy()

    # ---- reopen: library shows up without scanning ----
    root, app = open_app(monkeypatch)
    try:
        pump(root, lambda: len(app.records) == 7, timeout=30, what="load on reopen")
        assert not app.busy  # nothing new: no analysis
        assert app.s.layout == "key_bpm" and app.s.folder_names.get("070-079 BPM") == "Slow"
    finally:
        root.destroy()

    assert digest(src) == originals  # original beats never changed
