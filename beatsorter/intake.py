"""Download one beat and sort it: the whole "paste a link" flow, no GUI.

download -> read BPM/key from title/description -> analyze audio ->
classify -> link into the Sorted folder (if one is set up).
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .analyzer import analyze_file
from .builder import PlanItem, UnsafePath, add_items, check_folders
from .cache import Cache
from .classifier import Decision, classify
from .config import Settings, app_dir
from .downloader import already_downloaded, download
from .filename_tags import FilenameTags, parse_filename
from .pipeline import Record

DOWNLOAD_FOLDER = "YouTube Downloads"


@dataclass
class IntakeResult:
    title: str
    record: Record
    decision: Decision
    sorted_to: Optional[Path] = None  # where the link in Sorted went
    note: str = ""  # e.g. why it wasn't added to Sorted


def download_folder(settings: Settings) -> Path:
    return Path(settings.source) / DOWNLOAD_FOLDER


def make_record(path: Path, source: Path, text_tags: FilenameTags) -> Record:
    """Analyze a file and build its Record. Tags read from the video text
    win over tags parsed from the (cleaned-up) file name."""
    analysis = analyze_file(str(path))
    st = path.stat()
    cache = Cache(app_dir() / "cache.db")
    try:
        cache.put(str(path), st.st_size, st.st_mtime, analysis)
    finally:
        cache.close()
    name_tags = parse_filename(path.name)
    tags = FilenameTags(bpm=text_tags.bpm if text_tags.bpm is not None else name_tags.bpm,
                        key=text_tags.key if text_tags.key is not None else name_tags.key)
    try:
        rel = path.relative_to(source)
    except ValueError:
        rel = Path(path.name)
    return Record(path, rel, st.st_size, analysis=analysis, tags=tags)


def sort_into_library(rec: Record, d: Decision, settings: Settings) -> tuple:
    """Link one file into the Sorted folder. Returns (dest or None, note)."""
    if not settings.output:
        return None, "No Sorted folder chosen yet; it will be sorted on your next build."
    if not d.folder:
        return None, f"Not sorted ({d.category.lower()})."
    out = Path(settings.output)
    try:
        check_folders(Path(settings.source), out)
    except UnsafePath as e:
        return None, str(e)
    dest = out.joinpath(*d.folder) / rec.path.name
    res = add_items([PlanItem(rec.path, dest)], Path(settings.source), out)
    if res.errors:
        return None, res.errors[0]
    return dest, ""


def process(url: str, settings: Settings,
            progress: Optional[Callable[[str, float], None]] = None,
            cancel: Optional[threading.Event] = None,
            video_id: str = "") -> IntakeResult:
    report = progress or (lambda *a: None)
    source = Path(settings.source)
    if not settings.source or not source.is_dir():
        raise RuntimeError("Pick your beats folder first (downloads are saved inside it).")
    dest_dir = download_folder(settings)

    existing = already_downloaded(video_id) if video_id else None
    if existing is not None:
        report("Already downloaded", 1.0)
        rec = make_record(existing, source, parse_filename(existing.name))
        d = classify(rec, settings)
        return IntakeResult(existing.stem, rec, d, None,
                            note=f"Already downloaded: {existing.name}")

    dl = download(url, dest_dir, progress=report, cancel=cancel,
                  fmt=settings.download_format)
    report("Analyzing", 1.0)
    rec = make_record(dl.path, source, dl.tags)
    d = classify(rec, settings)
    report("Sorting", 1.0)
    dest, note = sort_into_library(rec, d, settings)
    return IntakeResult(dl.title, rec, d, dest, note)
