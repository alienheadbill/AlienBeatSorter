"""Your own folders ("My Folders"): nested, renamable, in your order.

Stored in library.db next to tags and fixes. A folder holds references to
beats (by path); a beat can be in any number of folders. Nothing here
touches audio files: the Sorted folder gets links to match.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .config import app_dir

_BAD = '<>:"/\\|?*'


def clean_name(name: str) -> str:
    """A folder name Windows accepts."""
    name = "".join("-" if c in _BAD or ord(c) < 32 else c for c in name).strip().strip(".")
    return name[:80]


class FolderStore:
    def __init__(self, db_path: Path = None):
        self.conn = sqlite3.connect(str(db_path or app_dir() / "library.db"),
                                    check_same_thread=False)
        self.conn.execute("CREATE TABLE IF NOT EXISTS folders ("
                          " id INTEGER PRIMARY KEY, parent INTEGER, name TEXT NOT NULL,"
                          " pos INTEGER NOT NULL DEFAULT 0)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS folder_items ("
                          " folder INTEGER NOT NULL, path TEXT NOT NULL,"
                          " pos INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (folder, path))")
        self.conn.commit()

    # ---- folders ----
    def children(self, parent: Optional[int] = None) -> List[Tuple[int, str]]:
        """(id, name) in your order."""
        q = ("SELECT id, name FROM folders WHERE parent IS ? ORDER BY pos, id")
        return list(self.conn.execute(q, (parent,)))

    def get(self, fid: int) -> Optional[Tuple[Optional[int], str]]:
        row = self.conn.execute("SELECT parent, name FROM folders WHERE id = ?", (fid,)).fetchone()
        return (row[0], row[1]) if row else None

    def _unique(self, name: str, parent: Optional[int], skip: Optional[int] = None) -> str:
        taken = {n.lower() for i, n in self.children(parent) if i != skip}
        base, n, out = name, 2, name
        while out.lower() in taken:
            out = f"{base} {n}"
            n += 1
        return out

    def create(self, name: str, parent: Optional[int] = None) -> int:
        name = clean_name(name) or "New folder"
        name = self._unique(name, parent)
        pos = len(self.children(parent))
        cur = self.conn.execute("INSERT INTO folders (parent, name, pos) VALUES (?, ?, ?)",
                                (parent, name, pos))
        self.conn.commit()
        return int(cur.lastrowid)

    def rename(self, fid: int, name: str) -> str:
        info = self.get(fid)
        name = clean_name(name)
        if not info or not name:
            return info[1] if info else ""
        name = self._unique(name, info[0], skip=fid)
        self.conn.execute("UPDATE folders SET name = ? WHERE id = ?", (name, fid))
        self.conn.commit()
        return name

    def descendants(self, fid: int) -> List[int]:
        out, todo = [], [fid]
        while todo:
            f = todo.pop()
            out.append(f)
            todo += [i for i, _ in self.children(f)]
        return out

    def delete(self, fid: int) -> None:
        """Delete a folder and its subfolders (beats stay in your library)."""
        ids = self.descendants(fid)
        self.conn.executemany("DELETE FROM folder_items WHERE folder = ?", [(i,) for i in ids])
        self.conn.executemany("DELETE FROM folders WHERE id = ?", [(i,) for i in ids])
        self.conn.commit()

    def move(self, fid: int, new_parent: Optional[int], index: Optional[int] = None) -> bool:
        """Put a folder inside another (None = top level) at a position.
        Refuses to put a folder inside itself."""
        if new_parent is not None and new_parent in self.descendants(fid):
            return False
        info = self.get(fid)
        if not info:
            return False
        siblings = [i for i, _ in self.children(new_parent) if i != fid]
        index = len(siblings) if index is None else max(0, min(index, len(siblings)))
        siblings.insert(index, fid)
        name = self._unique(info[1], new_parent, skip=fid)
        self.conn.execute("UPDATE folders SET parent = ?, name = ? WHERE id = ?",
                          (new_parent, name, fid))
        self.conn.executemany("UPDATE folders SET pos = ? WHERE id = ?",
                              [(n, i) for n, i in enumerate(siblings)])
        if info[0] != new_parent:  # close the gap left behind
            old = [i for i, _ in self.children(info[0])]
            self.conn.executemany("UPDATE folders SET pos = ? WHERE id = ?",
                                  [(n, i) for n, i in enumerate(old)])
        self.conn.commit()
        return True

    def shift(self, fid: int, delta: int) -> None:
        """Move a folder up (-1) or down (+1) among its siblings."""
        info = self.get(fid)
        if not info:
            return
        ids = [i for i, _ in self.children(info[0])]
        self.move(fid, info[0], ids.index(fid) + delta)

    def path(self, fid: int, numbered: bool = False) -> Tuple[str, ...]:
        """Folder names from the top down, e.g. ("Album", "Side A").
        numbered: prefix each with its position ("01 Album") so file
        browsers (FL Studio) show your order."""
        parts: List[str] = []
        f: Optional[int] = fid
        while f is not None:
            info = self.get(f)
            if not info:
                break
            parent, name = info
            if numbered:
                ids = [i for i, _ in self.children(parent)]
                name = f"{ids.index(f) + 1:02d} {name}"
            parts.append(name)
            f = parent
        return tuple(reversed(parts))

    # ---- beats in folders ----
    def add_items(self, fid: int, paths: Iterable[str]) -> int:
        start = self.conn.execute("SELECT COALESCE(MAX(pos), -1) + 1 FROM folder_items "
                                  "WHERE folder = ?", (fid,)).fetchone()[0]
        rows = [(fid, str(p), start + n) for n, p in enumerate(paths)]
        before = self.conn.total_changes
        self.conn.executemany("INSERT OR IGNORE INTO folder_items VALUES (?, ?, ?)", rows)
        self.conn.commit()
        return self.conn.total_changes - before

    def remove_items(self, fid: int, paths: Iterable[str]) -> None:
        self.conn.executemany("DELETE FROM folder_items WHERE folder = ? AND path = ?",
                              [(fid, str(p)) for p in paths])
        self.conn.commit()

    def items(self, fid: int, recursive: bool = False) -> List[str]:
        ids = self.descendants(fid) if recursive else [fid]
        out: List[str] = []
        seen = set()
        for i in ids:
            for (p,) in self.conn.execute("SELECT path FROM folder_items WHERE folder = ? "
                                          "ORDER BY pos", (i,)):
                if p not in seen:
                    seen.add(p)
                    out.append(p)
        return out

    def count(self, fid: int) -> int:
        return len(self.items(fid, recursive=True))

    def memberships(self, numbered: bool = False) -> Dict[str, List[Tuple[str, ...]]]:
        """path -> folder paths it's in (for building the Sorted folder)."""
        paths = {}
        out: Dict[str, List[Tuple[str, ...]]] = {}
        for fid, p in self.conn.execute("SELECT folder, path FROM folder_items ORDER BY folder, pos"):
            if fid not in paths:
                paths[fid] = self.path(fid, numbered)
            out.setdefault(p, []).append(paths[fid])
        return out
