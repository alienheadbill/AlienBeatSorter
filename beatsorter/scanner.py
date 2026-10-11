"""Find audio files under a folder. Read-only."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional

AUDIO_EXTS = {".wav", ".mp3", ".flac", ".aif", ".aiff", ".ogg"}


@dataclass
class AudioFile:
    path: Path
    size: int
    mtime: float


def is_within(child: Path, parent: Path) -> bool:
    """True if child is parent or inside it (after resolving)."""
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def scan(source: Path, exclude: Optional[List[Path]] = None,
         cancel=lambda: False) -> Iterator[AudioFile]:
    """Yield audio files under source, skipping excluded folders
    (e.g. the Sorted output folder if it lives inside the source)."""
    excluded = [p.resolve() for p in (exclude or [])]
    for root, dirs, files in os.walk(source):
        if cancel():
            return
        root_p = Path(root)
        # Prune excluded folders so we never re-scan our own output.
        dirs[:] = sorted(
            d for d in dirs
            if not d.startswith(".beatsorter")  # in-progress downloads
            and not any(is_within(root_p / d, ex) for ex in excluded)
        )
        for name in sorted(files):
            if name.startswith("._"):  # macOS resource-fork junk
                continue
            if Path(name).suffix.lower() not in AUDIO_EXTS:
                continue
            p = root_p / name
            try:
                st = p.stat()
            except OSError:
                continue
            yield AudioFile(p, st.st_size, st.st_mtime)
