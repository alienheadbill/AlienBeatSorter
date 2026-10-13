"""SQLite cache of analysis results, so re-runs only analyze new or
changed files. Keyed by path + size + modified time + analysis version."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional

from .analyzer import ANALYSIS_VERSION


class Cache:
    def __init__(self, db_path: Path):
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS results ("
            " path TEXT PRIMARY KEY, size INTEGER, mtime REAL,"
            " version INTEGER, data TEXT)"
        )
        self.conn.commit()

    def get(self, path: str, size: int, mtime: float,
            any_version: bool = False) -> Optional[Dict[str, Any]]:
        """Saved analysis if the file is unchanged. any_version: also accept
        results from an older version of the analysis."""
        row = self.conn.execute(
            "SELECT size, mtime, version, data FROM results WHERE path=?", (path,)
        ).fetchone()
        if not row:
            return None
        r_size, r_mtime, r_ver, data = row
        if r_size != size or abs(r_mtime - mtime) > 1e-3 or (
                r_ver != ANALYSIS_VERSION and not any_version):
            return None
        return json.loads(data)

    def put(self, path: str, size: int, mtime: float, data: Dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO results VALUES (?,?,?,?,?)",
            (path, size, mtime, ANALYSIS_VERSION, json.dumps(data)),
        )

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()
