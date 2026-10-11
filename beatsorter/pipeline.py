"""Scan + analyze a library using several worker processes, with caching,
progress callbacks and cancel support. No GUI code here."""

from __future__ import annotations

import threading
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .analyzer import analyze_file
from .cache import Cache
from .config import Settings, app_dir
from .filename_tags import FilenameTags, parse_filename
from .scanner import scan


@dataclass
class Record:
    path: Path
    rel: Path  # path relative to the source folder
    size: int
    analysis: Dict[str, Any] = field(default_factory=dict)
    tags: FilenameTags = field(default_factory=FilenameTags)


ProgressFn = Callable[[str, int, int, Optional[Record]], None]
# progress(stage, done, total, record_just_finished)


def analyze_library(settings: Settings, source: Path,
                    exclude: Optional[List[Path]] = None,
                    progress: Optional[ProgressFn] = None,
                    cancel: Optional[threading.Event] = None) -> List[Record]:
    cancel = cancel or threading.Event()
    report = progress or (lambda *a: None)

    report("Scanning files...", 0, 0, None)
    files = list(scan(source, exclude=exclude, cancel=cancel.is_set))
    records: List[Record] = []
    todo: List[Record] = []
    cache = Cache(app_dir() / "cache.db")
    try:
        for f in files:
            rec = Record(f.path, f.path.relative_to(source), f.size,
                         tags=parse_filename(f.path.name))
            cached = cache.get(str(f.path), f.size, f.mtime)
            if cached is not None:
                rec.analysis = cached
            else:
                todo.append(rec)
            records.append(rec)

        total = len(records)
        done = total - len(todo)
        report("Analyzing", done, total, None)
        if not todo or cancel.is_set():
            return records

        mtimes = {str(f.path): f.mtime for f in files}
        with ProcessPoolExecutor(max_workers=settings.worker_count()) as pool:
            futures = {pool.submit(analyze_file, str(r.path)): r for r in todo}
            try:
                for fut in as_completed(futures):
                    rec = futures[fut]
                    try:
                        rec.analysis = fut.result()
                    except Exception as e:  # worker crashed
                        rec.analysis = {"error": f"{type(e).__name__}: {e}"}
                    if not rec.analysis.get("error") or rec.analysis.get("analyzed"):
                        cache.put(str(rec.path), rec.size, mtimes[str(rec.path)], rec.analysis)
                    done += 1
                    if done % 20 == 0:
                        cache.commit()
                    report("Analyzing", done, total, rec)
                    if cancel.is_set():
                        break
            finally:
                if cancel.is_set():
                    for f in futures:
                        f.cancel()
                    pool.shutdown(wait=True, cancel_futures=True)
        return records
    finally:
        cache.close()
