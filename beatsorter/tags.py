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
        self.conn.commit()

    def all(self) -> Dict[str, Set[str]]:
        out: Dict[str, Set[str]] = {}
        for path, tag in self.conn.execute("SELECT path, tag FROM tags"):
            out.setdefault(path, set()).add(tag)
        return out

    def names(self) -> List[str]:
        """All tags, most used first."""
        rows = self.conn.execute(
            "SELECT tag, COUNT(*) c FROM tags GROUP BY tag ORDER BY c DESC, tag COLLATE NOCASE")
        return [r[0] for r in rows]

    def _canonical(self, tag: str) -> str:
        """Reuse an existing tag's spelling ("Dark" vs "dark")."""
        row = self.conn.execute("SELECT tag FROM tags WHERE tag = ? COLLATE NOCASE LIMIT 1",
                                (tag,)).fetchone()
        return row[0] if row else tag

    def add(self, paths: Iterable[str], tag: str) -> str:
        tag = clean_tag(tag)
        if not tag:
            return ""
        tag = self._canonical(tag)
        self.conn.executemany("INSERT OR IGNORE INTO tags VALUES (?, ?)",
                              [(str(p), tag) for p in paths])
        self.conn.commit()
        return tag

    def remove(self, paths: Iterable[str], tag: str) -> None:
        self.conn.executemany("DELETE FROM tags WHERE path = ? AND tag = ?",
                              [(str(p), tag) for p in paths])
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
