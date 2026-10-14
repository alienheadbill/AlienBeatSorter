"""Settings and the app's data folder."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


def app_dir() -> Path:
    """%LOCALAPPDATA%\\BeatSorter on Windows, ~/.beatsorter elsewhere."""
    base = os.environ.get("LOCALAPPDATA")
    d = Path(base) / "BeatSorter" if base else Path.home() / ".beatsorter"
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class Settings:
    source: str = ""
    output: str = ""
    bpm_min: float = 70.0  # preferred BPM range; detected tempos are
    bpm_max: float = 180.0  # halved/doubled to land inside it
    bpm_auto: bool = True  # after each scan, learn the range from named beats
    oneshot_seconds: float = 2.0  # shorter files go to One-Shots
    bpm_conf_min: float = 0.35  # below this, a detected BPM goes to _Review
    key_conf_min: float = 0.25  # below this, a detected key goes to _Review
    use_detected_key: bool = True  # off: untagged keys go to "Key unknown"
    add_tags_to_names: bool = True  # name links in Sorted "name [140 Am].wav" (FL search)
    workers: int = 0  # 0 = automatic
    download_format: str = "wav"  # "wav" or "mp3" for YouTube downloads
    fl_user_data: str = ""  # FL's "Image-Line" user data folder; blank = find it
    fl_sync_bpm: bool = True  # what "Sync tags to FL Studio" sends
    fl_sync_key: bool = True
    fl_sync_types: bool = True
    fl_sync_mine: bool = True
    layout: str = "bpm_key"  # how Sorted nests folders (see organizer.LAYOUTS)
    folder_names: dict = field(default_factory=dict)  # your renames: "140-149 BPM" -> "Fast"
    number_my_folders: bool = False
    library_sidebar: int = 240  # width of the filter sidebar on the Library tab
    player_volume: float = 0.9
    player_loop: bool = False
    player_autoplay: bool = False  # play the next beat when one ends  # "01 Album" so FL shows My Folders in your order

    @classmethod
    def load(cls) -> "Settings":
        p = app_dir() / "settings.json"
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            known = {f.name for f in fields(cls)}
            return cls(**{k: v for k, v in data.items() if k in known})
        except Exception:
            return cls()

    def save(self) -> None:
        p = app_dir() / "settings.json"
        p.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    def worker_count(self) -> int:
        if self.workers > 0:
            return self.workers
        return max(1, min(6, (os.cpu_count() or 2) - 1))  # ~400 MB RAM each
