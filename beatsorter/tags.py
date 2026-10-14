"""Your own tags for beats ("dark", "drill", "favorite", "sold", ...).

Stored by Beat Sorter in %LOCALAPPDATA%\\BeatSorter\\library.db, keyed by
the file's path. Tags never change the audio files themselves.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Dict, Iterable, List, Set

from .config import app_dir

MAX_LEN = 30

# Colors offered when you make a tag (readable on the dark UI). The first is
# the default for tags made before colors existed; others are picked by name.
TAG_PALETTE = [
    "#8f32c7", "#52be29", "#50ade5", "#ffcf5c", "#ff6b7a", "#ff9f43",
    "#c74fd8", "#2bd4a8", "#e85aa0", "#7a8cff", "#c0ca33", "#9aa0a6",
]
DEFAULT_TAG_COLOR = TAG_PALETTE[0]


def default_color(tag: str) -> str:
    """A stable color for a tag that doesn't have one chosen yet."""
    if not tag:
        return DEFAULT_TAG_COLOR
    h = sum(ord(c) for c in tag.lower())
    return TAG_PALETTE[h % len(TAG_PALETTE)]


def clean_tag(tag: str) -> str:
    """Tags double as folder names in Sorted\\Tags\\, so keep them safe."""
    t = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", tag or "")
    t = re.sub(r"\s+", " ", t).strip(" .")
    return t[:MAX_LEN].strip(" .")


class TagStore:
    def __init__(self, db_path: Path = None):
        self.conn = sqlite3.connect(str(db_path or app_dir() / "library.db"),
                                    check_same_thread=False)
        self.conn.execute("CREATE TABLE IF NOT EXISTS tags ("
                          " path TEXT NOT NULL, tag TEXT NOT NULL,"
                          " PRIMARY KEY (path, tag))")
        # Your BPM/key fixes. They win over file names and detection.
        self.conn.execute("CREATE TABLE IF NOT EXISTS overrides ("
                          " path TEXT PRIMARY KEY, bpm REAL, key TEXT)")
        # A tag's chosen color, and a record that the tag exists even before
        # it's put on any beat (so you can make a tag, then apply it later).
        self.conn.execute("CREATE TABLE IF NOT EXISTS tag_meta ("
                          " tag TEXT PRIMARY KEY, color TEXT)")
        self.conn.commit()

    def all(self) -> Dict[str, Set[str]]:
        out: Dict[str, Set[str]] = {}
        for path, tag in self.conn.execute("SELECT path, tag FROM tags"):
            out.setdefault(path, set()).add(tag)
        return out

    def names(self) -> List[str]:
        """Every tag: ones in use first (most-used first), then tags you've
        made but not applied yet, alphabetically."""
        rows = self.conn.execute(
            "SELECT tag, COUNT(*) c FROM tags GROUP BY tag ORDER BY c DESC, tag COLLATE NOCASE")
        out = [r[0] for r in rows]
        seen = {t.lower() for t in out}
        extra = [r[0] for r in self.conn.execute(
            "SELECT tag FROM tag_meta ORDER BY tag COLLATE NOCASE") if r[0].lower() not in seen]
        return out + extra

    def colors(self) -> Dict[str, str]:
        """tag -> color. Tags with no chosen color get a stable default."""
        chosen = {t: c for t, c in self.conn.execute("SELECT tag, color FROM tag_meta") if c}
        out = {t: chosen.get(t) or default_color(t) for t in self.names()}
        return out

    def set_color(self, tag: str, color: str) -> None:
        tag = self._canonical(clean_tag(tag))
        if tag:
            self.conn.execute("INSERT INTO tag_meta (tag, color) VALUES (?, ?) "
                              "ON CONFLICT(tag) DO UPDATE SET color = excluded.color", (tag, color))
            self.conn.commit()

    def create(self, tag: str, color: str = None) -> str:
        """Register a tag (so it exists and has a color) without putting it on
        any beat. Returns its canonical spelling, or "" if the name is empty."""
        tag = clean_tag(tag)
        if not tag:
            return ""
        tag = self._canonical(tag)
        self.conn.execute("INSERT OR IGNORE INTO tag_meta (tag, color) VALUES (?, ?)",
                          (tag, color or default_color(tag)))
        if color:
            self.conn.execute("UPDATE tag_meta SET color = ? WHERE tag = ?", (color, tag))
        self.conn.commit()
        return tag

    def delete_tag(self, tag: str) -> None:
        """Remove a tag entirely (from every beat and the registry)."""
        self.conn.execute("DELETE FROM tags WHERE tag = ? COLLATE NOCASE", (tag,))
        self.conn.execute("DELETE FROM tag_meta WHERE tag = ? COLLATE NOCASE", (tag,))
        self.conn.commit()

    def _canonical(self, tag: str) -> str:
        """Reuse an existing tag's spelling ("Dark" vs "dark")."""
        for table in ("tags", "tag_meta"):
            row = self.conn.execute(f"SELECT tag FROM {table} WHERE tag = ? COLLATE NOCASE LIMIT 1",
                                    (tag,)).fetchone()
            if row:
                return row[0]
        return tag

    def add(self, paths: Iterable[str], tag: str) -> str:
        tag = clean_tag(tag)
        if not tag:
            return ""
        tag = self._canonical(tag)
        self.conn.executemany("INSERT OR IGNORE INTO tags VALUES (?, ?)",
                              [(str(p), tag) for p in paths])
        self.conn.execute("INSERT OR IGNORE INTO tag_meta (tag, color) VALUES (?, ?)",
                          (tag, default_color(tag)))  # so every tag has a color
        self.conn.commit()
        return tag

    def remove(self, paths: Iterable[str], tag: str) -> None:
        self.conn.executemany("DELETE FROM tags WHERE path = ? AND tag = ?",
                              [(str(p), tag) for p in paths])
        self.conn.commit()

    # ---- BPM/key fixes ----
    def overrides(self) -> Dict[str, dict]:
        out: Dict[str, dict] = {}
        for path, bpm, key in self.conn.execute("SELECT path, bpm, key FROM overrides"):
            o = {}
            if bpm:
                o["bpm"] = float(bpm)
            if key:
                o["key"] = key
            if o:
                out[path] = o
        return out

    def set_override(self, paths: Iterable[str], bpm=None, key=None,
                     clear_bpm: bool = False, clear_key: bool = False) -> None:
        """Set (or clear) your BPM and/or key fix on files. key is a key
        name like "C minor", or "none" for no key."""
        for p in paths:
            row = self.conn.execute("SELECT bpm, key FROM overrides WHERE path = ?",
                                    (str(p),)).fetchone()
            cur_bpm, cur_key = row if row else (None, None)
            new_bpm = None if clear_bpm else (bpm if bpm is not None else cur_bpm)
            new_key = None if clear_key else (key if key is not None else cur_key)
            if new_bpm is None and new_key is None:
                self.conn.execute("DELETE FROM overrides WHERE path = ?", (str(p),))
            else:
                self.conn.execute("INSERT OR REPLACE INTO overrides VALUES (?, ?, ?)",
                                  (str(p), new_bpm, new_key))
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
