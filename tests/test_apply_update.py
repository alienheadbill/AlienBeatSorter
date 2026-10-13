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
