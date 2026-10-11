import hashlib
from pathlib import Path

import pytest

from beatsorter.builder import MARKER, UnsafePath, build, check_folders, plan, _guard
from beatsorter.classifier import Decision, classify, fold_bpm
from beatsorter.config import Settings
from beatsorter.filename_tags import parse_filename
from beatsorter.pipeline import Record


def make_src(tmp: Path):
    src = tmp / "beats"
    (src / "a").mkdir(parents=True)
    (src / "b").mkdir()
    files = [src / "a" / "beat.wav", src / "b" / "beat.wav", src / "a" / "BEAT.wav"]
    for i, f in enumerate(files):
        f.write_bytes(b"RIFF" + bytes([i]) * 100)
    return src, files


def digest(folder: Path):
    return {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.rglob("*") if p.is_file()}


def test_guards(tmp_path):
    src, _ = make_src(tmp_path)
    with pytest.raises(UnsafePath):
        check_folders(src, src)
    with pytest.raises(UnsafePath):
        check_folders(src, tmp_path)  # contains the source
    other = tmp_path / "other"
    other.mkdir()
    (other / "x.txt").write_text("mine")
    with pytest.raises(UnsafePath):
        check_folders(src, other)  # non-empty, not ours
    with pytest.raises(UnsafePath):
        _guard(src / "a" / "beat.wav", tmp_path / "out", src)


def test_build_never_touches_source(tmp_path):
    src, files = make_src(tmp_path)
    before = digest(src)
    out = tmp_path / "Sorted"
    recs = [Record(f, f.relative_to(src), f.stat().st_size) for f in files]
    decs = [Decision("Sorted", bpm=140, folder=("140 BPM", "A minor")) for _ in recs]
    items = plan(recs, decs, out, add_tags_to_names=False)
    names = sorted(i.dest.name for i in items)
    assert names == ["BEAT (2).wav", "beat (3).wav", "beat.wav"] or len(set(n.lower() for n in names)) == 3
    build(items, src, out)
    build(items, src, out)  # rebuild is repeatable
    # delete everything in Sorted: originals must survive
    for p in out.rglob("*.wav"):
        p.unlink()
    assert digest(src) == before
    assert (out / MARKER).exists()


def test_rebuild_keeps_user_files(tmp_path):
    src, files = make_src(tmp_path)
    out = tmp_path / "Sorted"
    recs = [Record(files[0], files[0].relative_to(src), 1)]
    build(plan(recs, [Decision("Sorted", folder=("140 BPM", "A minor"))], out, False), src, out)
    (out / "notes.txt").write_text("keep me")
    build(plan(recs, [Decision("Sorted", folder=("150 BPM", "A minor"))], out, False), src, out)
    assert (out / "notes.txt").read_text() == "keep me"
    assert not (out / "140 BPM").exists()
    assert (out / "150 BPM" / "A minor" / "beat.wav").exists()


def test_fold():
    assert fold_bpm(70, 70, 180) == 70
    assert fold_bpm(70, 85, 170) == 140
    assert fold_bpm(174, 70, 140) == 87
    assert fold_bpm(0, 70, 180) == 0


def test_filename_wins_and_flags():
    s = Settings()
    rec = Record(Path("x/Beat 140bpm Am.wav"), Path("Beat 140bpm Am.wav"), 1,
                 analysis={"analyzed": True, "duration": 60, "bpm": 100, "bpm_conf": 0.9,
                           "key_pc": 0, "key_mode": "major", "key_conf": 0.9,
                           "harm_ratio": 0.9, "key_r": 0.7},
                 tags=parse_filename("Beat 140bpm Am.wav"))
    d = classify(rec, s)
    assert d.folder == ("140-149 BPM", "A minor")
    assert any("BPM tag" in f for f in d.flags)
    # C major vs A minor is the relative key: not flagged
    assert not any("key tag" in f for f in d.flags)


def test_low_confidence_goes_to_review():
    s = Settings()
    rec = Record(Path("x/untitled.wav"), Path("untitled.wav"), 1,
                 analysis={"analyzed": True, "duration": 60, "bpm": 92, "bpm_conf": 0.1,
                           "key_pc": 9, "key_mode": "minor", "key_conf": 0.9,
                           "harm_ratio": 0.9, "key_r": 0.7})
    d = classify(rec, s)
    assert d.folder == ("_Review", "090-099 BPM", "A minor")


def test_add_items_appends_without_touching_rest(tmp_path):
    from beatsorter.builder import add_items, PlanItem, MANIFEST
    import json
    src, files = make_src(tmp_path)
    out = tmp_path / "Sorted"
    recs = [Record(files[0], files[0].relative_to(src), 1)]
    build(plan(recs, [Decision("Sorted", folder=("140 BPM", "A minor"))], out, False), src, out)
    new = src / "YouTube Downloads" / "Night Drive [140 C#m].wav"
    new.parent.mkdir()
    new.write_bytes(b"RIFFnew")
    before = digest(src)
    res = add_items([PlanItem(new, out / "140 BPM" / "C# minor" / new.name)], src, out)
    assert res.linked + res.copied == 1
    assert (out / "140 BPM" / "A minor" / "beat.wav").exists()  # old entry kept
    assert (out / "140 BPM" / "C# minor" / new.name).exists()
    files_in_manifest = json.loads((out / MANIFEST).read_text())["files"]
    assert len(files_in_manifest) == 2
    assert digest(src) == before
    with pytest.raises(UnsafePath):
        add_items([PlanItem(new, src / "evil.wav")], src, out)


def test_bpm_range_folders():
    from beatsorter.classifier import bpm_folder
    assert bpm_folder(140) == "140-149 BPM"
    assert bpm_folder(149.4) == "140-149 BPM"
    assert bpm_folder(149.6) == "150-159 BPM"
    assert bpm_folder(88) == "080-089 BPM"
    assert sorted([bpm_folder(b) for b in (174, 88, 142)]) == ["080-089 BPM", "140-149 BPM", "170-179 BPM"]


def test_tag_folders_build_and_untag(tmp_path):
    from beatsorter.builder import add_items, PlanItem, remove_tag_links, tag_folder
    src, files = make_src(tmp_path)
    before = digest(src)
    out = tmp_path / "Sorted"
    recs = [Record(f, f.relative_to(src), 1) for f in files[:2]]
    decs = [Decision("Sorted", bpm=142, folder=("140-149 BPM", "C minor")) for _ in recs]
    tags = {str(files[0]): {"dark", "favorite"}}
    items = plan(recs, decs, out, True, tags=tags)
    build(items, src, out)
    assert (tag_folder(out, "dark") / "beat [142].wav").exists()
    assert (tag_folder(out, "favorite") / "beat [142].wav").exists()
    # live tag on the second file, then untag it
    add_items([PlanItem(files[1], tag_folder(out, "dark") / "beat [142].wav")], src, out)
    assert len(list(tag_folder(out, "dark").iterdir())) == 2
    assert remove_tag_links(files[1], "dark", src, out) == 1
    assert (tag_folder(out, "dark") / "beat [142].wav").exists()  # first file's link stays
    assert remove_tag_links(files[0], "favorite", src, out) == 1
    assert not tag_folder(out, "favorite").exists()  # empty tag folder removed
    assert digest(src) == before


def test_tag_store(tmp_path):
    from beatsorter.tags import TagStore, clean_tag
    ts = TagStore(tmp_path / "lib.db")
    assert ts.add(["/a.wav", "/b.wav"], "Dark ") == "Dark"
    assert ts.add(["/c.wav"], "dark") == "Dark"  # reuses existing spelling
    assert ts.add(["/a.wav"], 'fav/<orites>?') == "favorites"
    assert ts.names()[0] == "Dark"
    ts.remove(["/a.wav"], "Dark")
    assert ts.all()["/a.wav"] == {"favorites"}
    assert clean_tag("   ") == ""
