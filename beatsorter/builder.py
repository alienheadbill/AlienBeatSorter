"""Build the Sorted folder. Originals are only ever READ.

Safety rules enforced here:
* Every file this module creates or deletes must be inside the Sorted
  folder, and never inside the source folder. Anything else raises.
* The Sorted folder can't be the source folder or contain it.
* A non-empty folder is only reused if Beat Sorter made it (marker file).
* On rebuild, only files listed in the previous manifest are removed;
  anything else you put in Sorted is left alone.
* Files are hard links (no extra disk space) or, if links aren't
  possible, copies. Deleting or renaming a link never affects the
  original. Note: EDITING a hard-linked file's audio in place (e.g. a
  destructive save from an audio editor) would change the original too,
  because both names point to the same data.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from .classifier import Decision
from .pipeline import Record
from .scanner import is_within

MARKER = ".beatsorter"
MANIFEST = ".beatsorter_manifest.json"
_BAD_CHARS = '<>:"/\\|?*'


class UnsafePath(Exception):
    pass


class NeedsCopy(Exception):
    """Hard links aren't possible (different drive, or a drive format
    such as exFAT/FAT32). Building would need full copies."""

    def __init__(self, total_bytes: int, reason: str):
        super().__init__(reason)
        self.total_bytes = total_bytes
        self.reason = reason


@dataclass
class PlanItem:
    src: Path
    dest: Path


@dataclass
class BuildResult:
    linked: int = 0
    copied: int = 0
    skipped: int = 0
    removed_old: int = 0
    errors: List[str] = None
    mode: str = ""

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


def _long(p: Path) -> str:
    """Windows long-path form so deep folders beyond 260 chars work."""
    s = str(p.resolve())
    if os.name == "nt" and not s.startswith("\\\\?\\"):
        s = "\\\\?\\" + s if not s.startswith("\\\\") else "\\\\?\\UNC" + s[1:]
    return s


def _clean(name: str) -> str:
    return "".join("_" if c in _BAD_CHARS else c for c in name).strip(" .") or "_"


def check_folders(source: Path, out: Path) -> None:
    """Raise UnsafePath if the output folder choice could touch originals."""
    source, out = source.resolve(), out.resolve()
    if out == source:
        raise UnsafePath("The Sorted folder can't be the same as your beats folder.")
    if is_within(source, out):
        raise UnsafePath("The Sorted folder can't contain your beats folder. "
                         "Pick a new, empty folder.")
    if out.exists():
        if not out.is_dir():
            raise UnsafePath(f"{out} is a file, not a folder.")
        has_stuff = any(out.iterdir())
        if has_stuff and not (out / MARKER).exists():
            raise UnsafePath("That folder already has files that Beat Sorter didn't "
                             "make. Pick an empty folder (or a previous Sorted folder).")


def _guard(dest: Path, out: Path, source: Path) -> None:
    """Every write/delete must be inside Sorted. check_folders() already
    guarantees Sorted is not the source and doesn't contain it."""
    if not is_within(dest, out):
        raise UnsafePath(f"Refusing to touch a file outside the Sorted folder: {dest}")


TAGS_FOLDER = "Tags"


def link_stem(rec: Record, d: Decision, add_tags_to_names: bool) -> str:
    """Name (without extension) for a file's link inside Sorted. With
    add_tags_to_names, BPM/key the original name lacks are appended so
    FL's Browser search finds them: "Nasty [142 Cm]"."""
    stem = rec.path.stem
    if add_tags_to_names and d.category != "One-Shots":
        bits = []
        if d.bpm and rec.tags.bpm is None:
            bits.append(f"{d.bpm:g}")
        if d.key and rec.tags.key is None:
            bits.append(d.key.short)
        if bits:
            stem = f"{stem} [{' '.join(bits)}]"
    return _clean(stem)


def tag_folder(out: Path, tag: str) -> Path:
    return out / TAGS_FOLDER / _clean(tag)


def plan(records: List[Record], decisions: List[Decision], out: Path,
         add_tags_to_names: bool, tags: Optional[Dict[str, set]] = None) -> List[PlanItem]:
    """Where every file goes in Sorted: its BPM/key folder, plus one link
    in Tags/<tag>/ for each of your tags on it."""
    items: List[PlanItem] = []
    used: set = set()
    tags = tags or {}

    def add(src: Path, folder: Path, stem: str, ext: str):
        dest = folder / (stem + ext)
        n = 2
        while str(dest).lower() in used:  # Windows names are case-insensitive
            dest = folder / f"{stem} ({n}){ext}"
            n += 1
        used.add(str(dest).lower())
        items.append(PlanItem(src, dest))

    for rec, d in zip(records, decisions):
        stem, ext = link_stem(rec, d, add_tags_to_names), rec.path.suffix
        if d.folder:
            add(rec.path, out.joinpath(*[_clean(p) for p in d.folder]), stem, ext)
        if d.category in ("Error", "Not analyzed"):
            continue
        for t in sorted(tags.get(str(rec.path), ())):
            add(rec.path, tag_folder(out, t), stem, ext)
    return items


def _same_device(a: Path, b: Path) -> bool:
    try:
        return os.stat(a).st_dev == os.stat(b).st_dev
    except OSError:
        return False


def _links_work(src: Path, out: Path) -> Tuple[bool, str]:
    if not _same_device(src, out):
        return False, "The Sorted folder is on a different drive than your beats."
    probe = out / ".beatsorter_linktest"
    try:
        if probe.exists():
            probe.unlink()
        os.link(_long(src), _long(probe))
        probe.unlink()
        return True, ""
    except OSError as e:
        return False, f"This drive doesn't support hard links ({e.strerror or e})."


def _remove_previous(out: Path, source: Path) -> int:
    mf = out / MANIFEST
    if not mf.exists():
        return 0
    try:
        entries = json.loads(mf.read_text(encoding="utf-8")).get("files", [])
    except Exception:
        entries = []
    removed = 0
    for rel in entries:
        p = out / rel
        _guard(p, out, source)
        try:
            if p.is_file():
                os.unlink(_long(p))
                removed += 1
        except OSError:
            pass
    # Remove now-empty folders (deepest first), never the Sorted root.
    for root, dirs, files in sorted(os.walk(out), key=lambda t: -len(t[0])):
        rp = Path(root)
        if rp.resolve() == out.resolve():
            continue
        _guard(rp, out, source)
        try:
            if not any(rp.iterdir()):
                rp.rmdir()
        except OSError:
            pass
    return removed


def build(items: List[PlanItem], source: Path, out: Path, allow_copy: bool = False,
          progress: Optional[Callable[[int, int], None]] = None) -> BuildResult:
    source, out = source.resolve(), out.resolve()
    check_folders(source, out)
    out.mkdir(parents=True, exist_ok=True)
    (out / MARKER).write_text("Made by Beat Sorter. Safe to delete this whole folder;\n"
                              "your original files are elsewhere and untouched.\n",
                              encoding="utf-8")

    res = BuildResult()
    if not items:
        res.removed_old = _remove_previous(out, source)
        return res

    can_link, why = _links_work(items[0].src, out)
    if not can_link and not allow_copy:
        total = sum(i.src.stat().st_size for i in items if i.src.exists())
        raise NeedsCopy(total, why)
    res.mode = "hard links" if can_link else "copies"

    res.removed_old = _remove_previous(out, source)

    made: List[str] = []
    for n, it in enumerate(items, 1):
        try:
            _guard(it.dest, out, source)
            it.dest.parent.mkdir(parents=True, exist_ok=True)
            if it.dest.exists():
                res.skipped += 1
                continue
            if can_link:
                try:
                    os.link(_long(it.src), _long(it.dest))
                    res.linked += 1
                except OSError:
                    if not allow_copy:
                        raise
                    shutil.copy2(_long(it.src), _long(it.dest))
                    res.copied += 1
            else:
                shutil.copy2(_long(it.src), _long(it.dest))
                res.copied += 1
            made.append(str(it.dest.relative_to(out)))
        except UnsafePath:
            raise
        except Exception as e:
            res.errors.append(f"{it.src.name}: {e}")
        if progress and (n % 25 == 0 or n == len(items)):
            progress(n, len(items))

    (out / MANIFEST).write_text(json.dumps({"source": str(source), "files": made},
                                           indent=0), encoding="utf-8")
    return res


def add_items(items: List[PlanItem], source: Path, out: Path) -> BuildResult:
    """Add new files to an existing Sorted folder without rebuilding it
    (used for downloads). Hard links when possible, otherwise copies (one
    new file at a time, so no big space surprise). Same safety rules as
    build(): nothing outside the Sorted folder is ever touched."""
    source, out = source.resolve(), out.resolve()
    check_folders(source, out)
    out.mkdir(parents=True, exist_ok=True)
    if not (out / MARKER).exists():
        (out / MARKER).write_text("Made by Beat Sorter. Safe to delete this whole folder;\n"
                                  "your original files are elsewhere and untouched.\n",
                                  encoding="utf-8")
    mf = out / MANIFEST
    try:
        manifest = json.loads(mf.read_text(encoding="utf-8"))
    except Exception:
        manifest = {"source": str(source), "files": []}
    res = BuildResult(mode="hard links")
    for it in items:
        try:
            _guard(it.dest, out, source)
            it.dest.parent.mkdir(parents=True, exist_ok=True)
            dest = it.dest
            n = 2
            while dest.exists():
                dest = it.dest.with_name(f"{it.dest.stem} ({n}){it.dest.suffix}")
                n += 1
            _guard(dest, out, source)
            try:
                os.link(_long(it.src), _long(dest))
                res.linked += 1
            except OSError:
                shutil.copy2(_long(it.src), _long(dest))
                res.copied += 1
                res.mode = "copies"
            it.dest = dest
            manifest.setdefault("files", []).append(str(dest.relative_to(out)))
        except UnsafePath:
            raise
        except Exception as e:
            res.errors.append(f"{it.src.name}: {e}")
    mf.write_text(json.dumps(manifest, indent=0), encoding="utf-8")
    return res


def remove_tag_links(src: Path, tag: str, source: Path, out: Path) -> int:
    """Remove the link(s) to src from Sorted/Tags/<tag>/ (after untagging).
    Only files Beat Sorter listed in its manifest are removed, and only
    inside the Sorted folder. Returns how many were removed."""
    source, out = source.resolve(), out.resolve()
    check_folders(source, out)
    folder = tag_folder(out, tag)
    if not folder.is_dir():
        return 0
    mf = out / MANIFEST
    try:
        manifest = json.loads(mf.read_text(encoding="utf-8"))
    except Exception:
        return 0
    listed = set(manifest.get("files", []))
    removed = 0
    for f in list(folder.iterdir()):
        rel = str(f.relative_to(out))
        if rel not in listed or not f.is_file():
            continue
        try:
            is_link = os.stat(f).st_nlink > 1  # a hard link to some original
            same = os.path.samefile(f, src) if is_link else False
        except OSError:
            is_link, same = False, False
        if not is_link:  # a copy (no shared identity): match by name
            same = f.stem == src.stem or f.stem.startswith(src.stem + " [")
        if same:
            _guard(f, out, source)
            os.unlink(_long(f))
            listed.discard(rel)
            removed += 1
    manifest["files"] = [x for x in manifest.get("files", []) if x in listed]
    mf.write_text(json.dumps(manifest, indent=0), encoding="utf-8")
    try:
        if not any(folder.iterdir()):
            folder.rmdir()
        tags_root = out / TAGS_FOLDER
        if tags_root.is_dir() and not any(tags_root.iterdir()):
            tags_root.rmdir()
    except OSError:
        pass
    return removed
