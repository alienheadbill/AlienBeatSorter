import hashlib
import os
from pathlib import Path

import pytest

from beatsorter import organizer as org
from beatsorter.builder import MANIFEST, build, plan, sync
from beatsorter.classifier import Decision
from beatsorter.folders import FolderStore, clean_name
from beatsorter.keys import Key
from beatsorter.pipeline import Record


# ---------- layouts / drop logic ----------

def test_layouts():
    fm = Key(5, "minor")
    assert org.arrange("140-149 BPM", "F minor", fm, "bpm_key") == ("140-149 BPM", "F minor")
    assert org.arrange("140-149 BPM", "F minor", fm, "key_bpm") == ("F minor", "140-149 BPM")
    assert org.arrange("140-149 BPM", "F minor", fm, "camelot_bpm") == ("04A - F minor", "140-149 BPM")
    assert org.arrange("140-149 BPM", "No Key", None, "camelot_bpm") == ("No Key", "140-149 BPM")
    assert org.arrange("140-149 BPM", "F minor", fm, "flat") == (org.ALL_BEATS,)


def test_drop_fixes():
    fm = Key(5, "minor")
    # 72 BPM beat dropped on 140-149: doubled; key changes to C minor
    assert org.fix_for_drop(("140-149 BPM", "C minor"), 72, fm) == {"bpm": 144, "key": "C minor"}
    # already fits: nothing changes
    assert org.fix_for_drop(("140-149 BPM", "F minor"), 144, fm) == {}
    # can't be halved/doubled into range: ask
    assert org.fix_for_drop(("100-109 BPM",), 144, fm) == {"ask_bpm": (100, 109)}
    assert org.fix_for_drop(("No Key",), 144, fm) == {"key": "none"}
    assert org.fix_for_drop(("08A - A minor", "140-149 BPM"), 144, fm) == {"key": "A minor"}
    assert org.is_drop_target(("140-149 BPM", "F minor"))
    assert not org.is_drop_target(("One-Shots", "Kicks"))
    assert not org.is_drop_target((org.ALL_BEATS,))


# ---------- my folders ----------

def test_folder_store(tmp_path):
    fs = FolderStore(tmp_path / "lib.db")
    album = fs.create("Album")
    side = fs.create("Side A", album)
    ideas = fs.create("Ideas")
    assert fs.create("album") != album and fs.get(fs.children()[-1][0])[1] == "album 2"
    assert [n for _, n in fs.children()] == ["Album", "Ideas", "album 2"]
    fs.shift(ideas, -1)
    assert [n for _, n in fs.children()][:2] == ["Ideas", "Album"]
    assert fs.path(side) == ("Album", "Side A")
    assert fs.path(side, numbered=True) == ("02 Album", "01 Side A")
    assert not fs.move(album, side)  # can't go inside itself
    fs.add_items(side, ["/b/one.wav", "/b/two.wav"])
    fs.add_items(side, ["/b/one.wav"])  # no duplicates
    assert fs.items(album, recursive=True) == ["/b/one.wav", "/b/two.wav"]
    assert fs.memberships()["/b/one.wav"] == [("Album", "Side A")]
    assert fs.rename(side, 'Side: "B"') == "Side- -B-"
    fs.delete(album)
    assert fs.items(side) == [] and fs.get(side) is None
    assert clean_name("  a/b  ") == "a-b"


# ---------- building with names, folders, and live sync ----------

def _setup(tmp_path):
    src = tmp_path / "beats"
    src.mkdir()
    files = []
    for n in ("one", "two"):
        f = src / f"{n}.wav"
        f.write_bytes(b"RIFF" + n.encode() * 50)
        files.append(f)
    recs = [Record(f, f.relative_to(src), f.stat().st_size) for f in files]
    return src, recs


def _digest(folder: Path):
    return {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.rglob("*") if p.is_file()}


def test_plan_renames_and_my_folders(tmp_path):
    src, recs = _setup(tmp_path)
    out = tmp_path / "Sorted"
    decs = [Decision("Sorted", folder=("140-149 BPM", "F minor")) for _ in recs]
    items = plan(recs, decs, out, False, names={"140-149 BPM": "Fast"},
                 folders={str(recs[0].path): [("Album", "Side A")]})
    rels = sorted(str(i.dest.relative_to(out)).replace(os.sep, "/") for i in items)
    assert rels == ["Fast/F minor/one.wav", "Fast/F minor/two.wav", "My Folders/Album/Side A/one.wav"]


def test_sync_changes_only_what_differs(tmp_path):
    src, recs = _setup(tmp_path)
    before = _digest(src)
    out = tmp_path / "Sorted"
    decs = [Decision("Sorted", folder=("140-149 BPM", "F minor")) for _ in recs]
    build(plan(recs, decs, out, False), src, out)
    mine = out / "140-149 BPM" / "my notes.txt"
    mine.write_text("keep me")

    # move "two" to another key, add "one" to a folder
    decs[1] = Decision("Sorted", folder=("140-149 BPM", "C minor"))
    res = sync(plan(recs, decs, out, False, folders={str(recs[0].path): [("Ideas",)]}), src, out)
    assert res.removed_old == 1 and res.linked == 2 and not res.errors
    assert (out / "140-149 BPM" / "C minor" / "two.wav").exists()
    assert not (out / "140-149 BPM" / "F minor" / "two.wav").exists()
    assert (out / "My Folders" / "Ideas" / "one.wav").exists()
    assert mine.read_text() == "keep me"  # your own files stay
    # running again changes nothing
    res = sync(plan(recs, decs, out, False, folders={str(recs[0].path): [("Ideas",)]}), src, out)
    assert (res.removed_old, res.linked, res.copied) == (0, 0, 0)
    # removing the folder membership removes the link and the empty folder
    sync(plan(recs, decs, out, False), src, out)
    assert not (out / "My Folders").exists()
    assert _digest(src) == before  # originals untouched throughout
    assert MANIFEST in os.listdir(out)


def test_sync_refuses_outside_sorted(tmp_path):
    from beatsorter.builder import PlanItem, UnsafePath
    src, recs = _setup(tmp_path)
    out = tmp_path / "Sorted"
    with pytest.raises(UnsafePath):
        sync([PlanItem(recs[0].path, tmp_path / "elsewhere" / "x.wav")], src, out)


def test_load_cached(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    from beatsorter.analyzer import ANALYSIS_VERSION
    from beatsorter.cache import Cache
    from beatsorter.config import app_dir
    from beatsorter.pipeline import load_cached
    src, recs = _setup(tmp_path)
    c = Cache(app_dir() / "cache.db")
    st = recs[0].path.stat()
    c.put(str(recs[0].path), st.st_size, st.st_mtime, {"version": ANALYSIS_VERSION, "bpm": 140})
    st = recs[1].path.stat()
    c.put(str(recs[1].path), st.st_size, st.st_mtime, {"version": ANALYSIS_VERSION - 1, "bpm": 70})
    c.commit()
    c.close()
    (src / "new.wav").write_bytes(b"RIFF" + b"n" * 50)
    got, new = load_cached(src)
    assert sorted(r.path.name for r in got) == ["one.wav", "two.wav"]  # older result shown too
    assert new == 2  # "two" (older analysis) + "new"
