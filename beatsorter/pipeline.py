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
    # Your own fixes from the app: {"bpm": 142.0, "key": "C minor" | "none"}
    override: Dict[str, Any] = field(default_factory=dict)


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
        mtimes = {str(f.path): f.mtime for f in files}
        report("Analyzing", done, total, None)
        if not todo or cancel.is_set():
            _shot_pass(records, cache, mtimes, report, cancel)
            return records

        state = {"done": done}

        def store(rec: Record) -> None:
            if not rec.analysis.get("error") or rec.analysis.get("analyzed"):
                cache.put(str(rec.path), rec.size, mtimes[str(rec.path)], rec.analysis)
            state["done"] += 1
            if state["done"] % 20 == 0:
                cache.commit()
            report("Analyzing", state["done"], total, rec)

        queue = list(todo)
        marker = _warm_marker()
        if not marker.exists() and len(queue) > 1:
            # First scan on this computer (or after an update of the audio
            # libraries): analyze one file alone first, so the libraries'
            # one-time compile happens in a single process. Several workers
            # compiling at once can crash each other.
            _run_pool(queue[:1], 1, store, cancel)
            if not _crashed(queue[0]):
                _mark_warm(marker)
                queue = queue[1:]  # (if it crashed, it's retried below with the rest)
        _run_pool(queue, settings.worker_count(), store, cancel)
        # If a worker crashed anyway, retry those files one at a time; a file
        # that crashes the analyzer by itself is reported as an error.
        failed = [r for r in queue if _crashed(r)]
        for _ in range(len(failed)):
            if not failed or cancel.is_set():
                break
            _run_pool(failed, 1, store, cancel)
            still = [r for r in failed if _crashed(r)]
            if len(still) == len(failed):  # no progress: the first one is the culprit
                still[0].analysis = {"error": "This file crashed the analyzer (it may be damaged)."}
                store(still[0])
                still = still[1:]
            failed = still
        _shot_pass(records, cache, mtimes, report, cancel)
        return records
    finally:
        cache.close()


def _run_pool(recs: List[Record], workers: int, store, cancel: threading.Event) -> None:
    """Analyze recs in worker processes, calling store(rec) for each."""
    if not recs or cancel.is_set():
        return
    from . import procs
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(analyze_file, str(r.path)): r for r in recs}
        procs.watch_pool(pool)  # so closing the app ends the workers right away
        try:
            for fut in as_completed(futures):
                rec = futures[fut]
                try:
                    rec.analysis = fut.result()
                except Exception as e:  # worker crashed
                    rec.analysis = {"error": f"{type(e).__name__}: {e}"}
                if not _crashed(rec):
                    store(rec)
                if cancel.is_set():
                    break
        finally:
            procs.forget_pool(pool)
            if cancel.is_set():
                for f in futures:
                    f.cancel()
                pool.shutdown(wait=True, cancel_futures=True)


def _crashed(rec: Record) -> bool:
    return str(rec.analysis.get("error", "")).startswith("BrokenProcessPool")


def _warm_marker() -> Path:
    """Marks that the audio libraries' one-time compile has been done for
    these library versions (see analyze_library)."""
    import os
    from importlib.metadata import version
    from .analyzer import ANALYSIS_VERSION
    try:
        tag = f"{version('librosa')}-{version('numba')}"
    except Exception:
        tag = "unknown"
    base = Path(os.environ.get("NUMBA_CACHE_DIR") or app_dir() / "numba_cache")
    return base / f"ready-{ANALYSIS_VERSION}-{tag}.txt"


def _mark_warm(marker: Path) -> None:
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("ok", encoding="utf-8")
    except OSError:
        pass


SHOT_MAX_SECONDS = 5.0  # files shorter than this get one-shot sound measurements


def _shot_pass(records: List[Record], cache: Cache, mtimes: Dict[str, float],
               report: ProgressFn, cancel: threading.Event) -> None:
    """Measure short files once (for kick/snare/hat/808 sorting) and cache
    the result with the file's analysis. Cheap: a few ms per file."""
    from .oneshots import sound_features

    need = [r for r in records
            if r.analysis and "shot" not in r.analysis
            and not (r.analysis.get("error") and not r.analysis.get("analyzed"))
            and 0 < r.analysis.get("duration", 0) < SHOT_MAX_SECONDS]
    for n, r in enumerate(need, 1):
        if cancel.is_set():
            break
        try:
            r.analysis["shot"] = sound_features(str(r.path))
        except Exception:
            r.analysis["shot"] = {}
        cache.put(str(r.path), r.size, mtimes[str(r.path)], r.analysis)
        if n % 50 == 0 or n == len(need):
            cache.commit()
            report("Measuring one-shots", n, len(need), None)


def load_cached(source: Path, exclude: Optional[List[Path]] = None) -> "tuple[List[Record], int]":
    """Your library as of the last scan, straight from saved results (no
    analysis, so it's quick). Returns (records, n_new): files that are new
    or changed since then aren't included, only counted, so the app can
    analyze just those. After an update that changed detection, the older
    results are shown meanwhile and counted in n_new (they'll be redone)."""
    from .analyzer import ANALYSIS_VERSION
    files = list(scan(source, exclude=exclude))
    records: List[Record] = []
    new = 0
    cache = Cache(app_dir() / "cache.db")
    try:
        for f in files:
            cached = cache.get(str(f.path), f.size, f.mtime, any_version=True)
            if cached is None or cached.get("version") != ANALYSIS_VERSION:
                new += 1
            if cached is None:
                continue
            records.append(Record(f.path, f.path.relative_to(source), f.size,
                                  analysis=cached, tags=parse_filename(f.path.name)))
    finally:
        cache.close()
    return records, new
