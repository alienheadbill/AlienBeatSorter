import os

import pytest

from beatsorter import apply_update as au


def _tree(root, files):
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


def _read(root):
    return {str(p.relative_to(root)).replace(os.sep, "/"): p.read_text()
            for p in root.rglob("*") if p.is_file()}


@pytest.fixture
def no_wait(monkeypatch):
    monkeypatch.setattr(au.time, "sleep", lambda s: None)


def test_waits_for_locked_folder_then_replaces(tmp_path, monkeypatch, no_wait):
    app, new = tmp_path / "app", tmp_path / "new"
    _tree(app, {"beatsorter/gui.py": "old", "beatsorter/assets/x.js": "old"})
    _tree(new, {"beatsorter/gui.py": "new", "beatsorter/player.py": "new"})
    real_rename, fails = os.rename, [3]

    def locked_rename(a, b):  # Windows: "in use by another process" a few times
        if fails[0] > 0:
            fails[0] -= 1
            raise PermissionError("in use")
        return real_rename(a, b)

    monkeypatch.setattr(au.os, "rename", locked_rename)
    au.replace_dir(new / "beatsorter", app / "beatsorter")
    assert _read(app) == {"beatsorter/gui.py": "new", "beatsorter/player.py": "new"}
    assert not list(app.glob("beatsorter.old-*"))


def test_never_leaves_half_deleted_folder(tmp_path, monkeypatch, no_wait):
    app, new = tmp_path / "app", tmp_path / "new"
    _tree(app, {"beatsorter/gui.py": "old", "beatsorter/assets/x.js": "old"})
    _tree(new, {"beatsorter/gui.py": "new"})
    monkeypatch.setattr(au.os, "rename", lambda a, b: (_ for _ in ()).throw(PermissionError("in use")))
    with pytest.raises(PermissionError):
        au.replace_dir(new / "beatsorter", app / "beatsorter")
    assert _read(app) == {"beatsorter/gui.py": "old", "beatsorter/assets/x.js": "old"}


def test_failed_copy_puts_old_folder_back(tmp_path, monkeypatch, no_wait):
    app, new = tmp_path / "app", tmp_path / "new"
    _tree(app, {"beatsorter/gui.py": "old"})
    _tree(new, {"beatsorter/gui.py": "new"})

    def broken_copy(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(au.shutil, "copytree", broken_copy)
    with pytest.raises(OSError):
        au.replace_dir(new / "beatsorter", app / "beatsorter")
    assert _read(app) == {"beatsorter/gui.py": "old"}


def test_full_update_and_leftover_cleanup(tmp_path, no_wait, monkeypatch):
    app, new = tmp_path / "app", tmp_path / "new"
    _tree(app, {"beatsorter/version.py": '__version__ = "1.0"', "Beat Sorter.bat": "old",
                "requirements.txt": "x", "beatsorter.old-123/junk.py": "junk"})
    _tree(new, {"beatsorter/version.py": '__version__ = "2.0"', "Beat Sorter.bat": "new",
                "requirements.txt": "x"})
    monkeypatch.setattr(au, "relaunch", lambda app: None)
    log = tmp_path / "update.log"
    assert au.main(["x", str(app), str(new), "0", str(log)]) == 0
    assert au.version_of(app) == "2.0" and (app / "Beat Sorter.bat").read_text() == "new"
    assert (app / "_backup" / "1.0" / "beatsorter" / "version.py").exists()
    assert not (app / "beatsorter.old-123").exists()
    assert "complete" in log.read_text()


class FakeProc:
    def __init__(self, on_start=None):
        self.alive = True
        if on_start:
            on_start()

    def poll(self):
        return None if self.alive else 0

    def kill(self):
        self.alive = False


def _two_versions(tmp_path):
    app, new = tmp_path / "app", tmp_path / "new"
    _tree(app, {"beatsorter/version.py": '__version__ = "1.0"', "requirements.txt": "x"})
    _tree(new, {"beatsorter/version.py": '__version__ = "2.0"', "requirements.txt": "x"})
    return app, new


def test_new_version_that_opens_is_kept(tmp_path, monkeypatch, no_wait):
    app, new = _two_versions(tmp_path)
    log = tmp_path / "update.log"
    monkeypatch.setattr(au, "relaunch", lambda a: FakeProc(
        lambda: (tmp_path / "started.txt").write_text(au.version_of(a))))
    au.main(["x", str(app), str(new), "0", str(log)])
    assert au.version_of(app) == "2.0"
    assert (tmp_path / "update_result.txt").read_text().startswith("ok")


def test_new_version_that_wont_open_is_rolled_back(tmp_path, monkeypatch, no_wait):
    app, new = _two_versions(tmp_path)
    log = tmp_path / "update.log"
    launched = []

    def relaunch(a):
        launched.append(au.version_of(a))
        p = FakeProc()
        if len(launched) == 1:
            p.alive = False  # the new version crashes on start
        return p

    monkeypatch.setattr(au, "relaunch", relaunch)
    au.main(["x", str(app), str(new), "0", str(log)])
    assert launched == ["2.0", "1.0"]  # tried the new one, then started the old one
    assert au.version_of(app) == "1.0"
    res = (tmp_path / "update_result.txt").read_text()
    assert res.startswith("failed") and "didn't open" in res


def test_update_while_essentia_helper_is_running(tmp_path, monkeypatch):
    """This morning's bug: on Windows the running key helper held the app
    folder, so an update couldn't replace it. The helper must never hold
    the app's own folder, so swapping the folder works while it runs."""
    import shutil
    import numpy as np
    from beatsorter import essentiakey
    real_pkg = __import__("pathlib").Path(essentiakey.__file__).parent
    app = tmp_path / "app"
    shutil.copytree(real_pkg, app / "beatsorter",
                    ignore=shutil.ignore_patterns("__pycache__"))
    monkeypatch.setattr(essentiakey, "SCRIPT", app / "beatsorter" / "assets" / "essentia" / "essentia_key.mjs")
    monkeypatch.setattr(essentiakey, "_proc", None)
    monkeypatch.setattr(essentiakey, "_broken", False)
    if not essentiakey.available():
        pytest.skip("deno not installed")
    t = np.arange(44100 * 3) / 44100
    out = essentiakey.detect((0.2 * np.sin(2 * np.pi * 220 * t)).astype("float32"))
    assert out, "helper should be running"
    try:
        new = tmp_path / "new"
        shutil.copytree(app / "beatsorter", new / "beatsorter")
        monkeypatch.setattr(au.time, "sleep", lambda s: None)
        au.replace_dir(new / "beatsorter", app / "beatsorter")  # must not hit "in use"
    finally:
        essentiakey._stop()
