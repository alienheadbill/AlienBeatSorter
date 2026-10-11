"""Send tags, BPM ranges and keys into FL Studio's own Browser tags.

FL keeps Browser tags in a text file:
  <FL user data>\\FL Studio\\Settings\\Browser\\Tags
Line 1 lists every tag after "@TagCase=*"; each other line is a quoted
file path followed by that file's tags:
  @TagCase=*,dark,Fm,"needs mix"
  "d:\\beats sorted\\140-149 bpm\\f minor\\byakugon.mp3",dark,Fm,140-149bpm

The format comes from an open-source tool that writes this file
(Sononymefel), not from Image-Line documentation, so this module is
deliberately careful:
* It MERGES: tags you made in FL are kept. Beat Sorter remembers which
  tags it added (fl_sync_state.json) and only ever removes its own.
* It refuses to write while FL Studio is running (FL rewrites the file
  when it exits, which would undo or clobber the sync).
* It backs up FL's file before every write; undo_last() restores it.
* Lines it can't parse are kept exactly as they were.
"""

from __future__ import annotations

import csv
import io
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .config import app_dir

HEADER_PREFIX = "@TagCase=*"
FL_PROCESSES = ("FL64.exe", "FL.exe", "FL Studio.exe", "FL64 (scaled).exe", "FL (scaled).exe")
KEEP_BACKUPS = 5


# ---------------------------------------------------------------- locating
def candidate_user_data_dirs() -> List[Path]:
    """Where FL's user data folder ("Image-Line") usually is."""
    home = Path.home()
    cands = [home / "Documents" / "Image-Line",
             home / "OneDrive" / "Documents" / "Image-Line"]
    for env in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        if os.environ.get(env):
            cands.append(Path(os.environ[env]) / "Documents" / "Image-Line")
    seen, out = set(), []
    for c in cands:
        if str(c).lower() not in seen:
            seen.add(str(c).lower())
            out.append(c)
    return out


def browser_dir(user_data: Optional[str] = None) -> Optional[Path]:
    """FL's Settings\\Browser folder, if it can be found."""
    roots = [Path(user_data)] if user_data else candidate_user_data_dirs()
    for root in roots:
        for d in (root / "FL Studio" / "Settings" / "Browser", root / "Settings" / "Browser"):
            if d.is_dir():
                return d
        settings = root / "FL Studio" / "Settings"
        if settings.is_dir():  # FL installed but no Browser folder yet
            return settings / "Browser"
    return None


def fl_running() -> bool:
    if sys.platform != "win32":
        return False
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True,
                             creationflags=flags, timeout=15).stdout.lower()
        return any(f'"{p.lower()}"' in out for p in FL_PROCESSES)
    except Exception:
        return False


# ---------------------------------------------------------------- tags
def fl_tag(tag: str) -> str:
    """A tag safe for FL's file: no commas, quotes or line breaks; spaces
    become dashes (keeps entry lines unquoted, the safest form)."""
    t = "".join(c for c in tag if c not in ',"\r\n').strip()
    return "-".join(t.split())


def norm_path(p: str) -> str:
    """How paths are compared: case-insensitive, backslashes."""
    return str(p).replace("/", "\\").lower()


# ---------------------------------------------------------------- file
class TagsFile:
    def __init__(self):
        self.header: List[str] = []  # all tags, in order
        self.entries: Dict[str, Tuple[str, List[str]]] = {}  # norm -> (path as written, tags)
        self.order: List[str] = []  # entry order (norm paths)
        self.raw_keep: List[str] = []  # lines we couldn't parse, kept verbatim

    @classmethod
    def load(cls, path: Path) -> "TagsFile":
        tf = cls()
        if not path.exists():
            return tf
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        lines = text.splitlines()
        if lines and lines[0].startswith(HEADER_PREFIX):
            row = next(csv.reader([lines[0][len(HEADER_PREFIX):]]), [])
            tf.header = [t for t in (x.strip() for x in row) if t]
            lines = lines[1:]
        for ln in lines:
            if not ln.strip():
                continue
            # Every real entry starts with a quoted path; anything else is
            # kept exactly as it was.
            if not ln.lstrip().startswith('"'):
                tf.raw_keep.append(ln)
                continue
            try:
                row = next(csv.reader([ln.lstrip()]))
            except Exception:
                row = []
            if not row or not row[0].strip():
                tf.raw_keep.append(ln)
                continue
            p = row[0]
            tags = [t.strip() for t in row[1:] if t.strip()]
            key = norm_path(p)
            if key not in tf.entries:
                tf.order.append(key)
                tf.entries[key] = (p, tags)
            else:  # duplicate line: merge
                tf.entries[key][1].extend(t for t in tags if t not in tf.entries[key][1])
        return tf

    def render(self) -> str:
        def head_tag(t):
            return f'"{t}"' if " " in t else t
        used = []
        for t in self.header:
            if t not in used:
                used.append(t)
        for key in self.order:
            for t in self.entries[key][1]:
                if t not in used:
                    used.append(t)
        out = io.StringIO()
        out.write(HEADER_PREFIX + "".join("," + head_tag(t) for t in used) + "\n")
        for key in self.order:
            p, tags = self.entries[key]
            if tags:
                out.write(f'"{p}"' + "".join("," + t for t in tags) + "\n")
        for ln in self.raw_keep:
            out.write(ln + "\n")
        return out.getvalue()


# ---------------------------------------------------------------- sync
def _state_path() -> Path:
    return app_dir() / "fl_sync_state.json"


def _load_state() -> Dict[str, List[str]]:
    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _backup(tags_path: Path) -> Optional[Path]:
    if not tags_path.exists():
        return None
    bdir = app_dir() / "fl_tags_backups"
    bdir.mkdir(exist_ok=True)
    dest = bdir / f"Tags-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(tags_path, dest)
    olds = sorted(bdir.glob("Tags-*"), reverse=True)
    for p in olds[KEEP_BACKUPS:]:
        try:
            p.unlink()
        except OSError:
            pass
    (bdir / "last_target.txt").write_text(str(tags_path), encoding="utf-8")
    return dest


def plan_sync(tags_path: Path, desired: Dict[str, Set[str]]) -> Tuple[TagsFile, Dict[str, List[str]], dict]:
    """Work out the merged file without writing anything.
    desired: {file path: set of tags Beat Sorter wants on it}. Files that
    Beat Sorter tagged before but aren't in desired lose only our tags."""
    tf = TagsFile.load(tags_path)
    state = _load_state()  # norm path -> tags WE added last time
    new_state: Dict[str, List[str]] = {}
    stats = {"files": 0, "added": 0, "removed": 0, "kept_user_tags": 0}

    want = {norm_path(p): (p, sorted({fl_tag(t) for t in tags if fl_tag(t)})) for p, tags in desired.items()}
    for key in set(state) | set(want):
        ours_before = set(state.get(key, []))
        p, wanted = want.get(key, (None, []))
        if key in tf.entries:
            written, current = tf.entries[key]
        else:
            written, current = (norm_path(p) if p else key), []
        user_tags = [t for t in current if t not in ours_before]  # not ours: never touched
        stats["kept_user_tags"] += len(user_tags)
        added_by_us = [t for t in wanted if t not in user_tags]
        stats["removed"] += len([t for t in ours_before if t not in wanted and t not in user_tags])
        stats["added"] += len([t for t in added_by_us if t not in ours_before])
        final = user_tags + added_by_us
        if key not in tf.entries:
            if not final:
                continue
            tf.order.append(key)
        tf.entries[key] = (written, final)
        if added_by_us:
            new_state[key] = added_by_us
        if wanted:
            stats["files"] += 1
    return tf, new_state, stats


def sync(tags_path: Path, desired: Dict[str, Set[str]]) -> dict:
    """Merge Beat Sorter's tags into FL's Tags file. Raises RuntimeError if
    FL Studio is running."""
    if fl_running():
        raise RuntimeError("FL Studio is open. Close it first: FL rewrites its tag file "
                           "when it exits, which would undo the sync.")
    tf, new_state, stats = plan_sync(tags_path, desired)
    tags_path.parent.mkdir(parents=True, exist_ok=True)
    stats["backup"] = str(_backup(tags_path) or "")
    tmp = tags_path.with_name(tags_path.name + ".beatsorter-tmp")
    tmp.write_text(tf.render(), encoding="utf-8", newline="\r\n" if os.name == "nt" else "\n")
    os.replace(tmp, tags_path)  # atomic: never leaves a half-written file
    _state_path().write_text(json.dumps(new_state), encoding="utf-8")
    return stats


def undo_last() -> Optional[str]:
    """Restore FL's Tags file from the newest backup. Returns its path."""
    if fl_running():
        raise RuntimeError("FL Studio is open. Close it first.")
    bdir = app_dir() / "fl_tags_backups"
    backups = sorted(bdir.glob("Tags-*"), reverse=True) if bdir.is_dir() else []
    target = bdir / "last_target.txt"
    if not backups or not target.exists():
        return None
    dest = Path(target.read_text(encoding="utf-8").strip())
    shutil.copy2(backups[0], dest)
    backups[0].unlink()
    try:
        _state_path().unlink()  # restored file has none of the newer tags
    except OSError:
        pass
    return str(dest)


def desired_tags(records, decisions, tag_map: Dict[str, set], sorted_paths: Dict[str, str],
                 include_bpm=True, include_key=True, include_types=True,
                 include_mine=True) -> Dict[str, Set[str]]:
    """What Beat Sorter wants FL to know about each file. Tags go on the
    path FL's Browser shows: the Sorted-folder link if there is one,
    otherwise the original file."""
    from .classifier import BPM_BUCKET
    out: Dict[str, Set[str]] = {}
    for r, d in zip(records, decisions):
        if d.category in ("Error", "Not analyzed"):
            continue
        tags: Set[str] = set()
        if include_bpm and d.bpm:
            lo = int(round(d.bpm)) // BPM_BUCKET * BPM_BUCKET
            tags.add(f"{lo}-{lo + BPM_BUCKET - 1}bpm")
        if include_key and d.key:
            tags.add(d.key.short)
        if include_types and getattr(d, "shot_type", ""):
            tags.add(d.shot_type)
        if include_mine:
            tags |= set(tag_map.get(str(r.path), ()))
        if tags:
            out[sorted_paths.get(str(r.path), str(r.path))] = tags
    return out
