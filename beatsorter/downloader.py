"""Download beats from YouTube as WAV using yt-dlp.

No GUI code here. Everything needed installs through pip (setup.bat):
  yt-dlp[default]  the downloader (+ yt-dlp-ejs for YouTube's JS checks)
  deno             JavaScript runtime yt-dlp uses for YouTube
  imageio-ffmpeg   a bundled ffmpeg for converting to WAV

File naming rule: BPM/key are added to the file name only when they come
from the video's title or description, never from audio detection. A
detected guess written into a name would later be treated as a label.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from .config import app_dir
from .filename_tags import FilenameTags, parse_description, parse_text

TMP_DIR_NAME = ".beatsorter_downloading"
_BAD = '<>:"/\\|?*'


class Cancelled(Exception):
    pass


@dataclass
class Probe:
    url: str
    title: str
    is_playlist: bool
    video_id: str = ""
    entries: List[Tuple[str, str]] = field(default_factory=list)  # (url, title)
    has_single_video: bool = False  # playlist link that also points at one video


@dataclass
class Downloaded:
    path: Path
    title: str
    video_id: str
    tags: FilenameTags  # BPM/key read from the title + description


# ---------------------------------------------------------------- setup
def _ffmpeg() -> Optional[str]:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg")


def _deno() -> Optional[str]:
    try:
        import deno
        return deno.find_deno_bin()
    except Exception:
        return shutil.which("deno")


def _base_opts() -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "socket_timeout": 30,
        "retries": 5,
        "fragment_retries": 5,
        "noplaylist": True,
    }
    ff = _ffmpeg()
    if ff:
        opts["ffmpeg_location"] = ff
    dn = _deno()
    if dn:
        opts["js_runtimes"] = {"deno": {"path": dn}}
    return opts


def available() -> Tuple[bool, str]:
    """Whether downloading can work here, and why not."""
    import importlib.util
    from .config import edition
    core_msg = ("YouTube download is part of the Full edition. This is the Core "
                "edition — get the Full download from the Beat Sorter releases page "
                "(More → Report a problem has the link), or run setup.bat if you "
                "installed from source.")
    setup_msg = "The downloader isn't installed. Run setup.bat again."
    miss = edition() == "core"
    if importlib.util.find_spec("yt_dlp") is None:
        return False, (core_msg if miss else setup_msg)
    if not _ffmpeg():
        return False, (core_msg if miss else "ffmpeg isn't installed. Run setup.bat again.")
    return True, ""


def downloader_version() -> str:
    try:
        import yt_dlp
        return yt_dlp.version.__version__
    except Exception:
        return "not installed"


# ---------------------------------------------------------------- probe
def _video_id_from_url(url: str) -> Optional[str]:
    u = urlparse(url)
    if u.netloc.endswith("youtu.be"):
        return u.path.strip("/") or None
    q = parse_qs(u.query)
    if "v" in q:
        return q["v"][0]
    m = re.match(r"^/(shorts|live)/([^/?#]+)", u.path)
    return m.group(2) if m else None


def probe(url: str) -> Probe:
    """Look up a link without downloading: title, and playlist contents."""
    import yt_dlp

    opts = dict(_base_opts(), skip_download=True, extract_flat="in_playlist",
                noplaylist=False)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if info.get("_type") == "playlist":
        entries = []
        for e in info.get("entries") or []:
            if not e:
                continue
            vurl = e.get("url") or ""
            if not vurl.startswith("http") and e.get("id"):
                vurl = f"https://www.youtube.com/watch?v={e['id']}"
            if vurl:
                entries.append((vurl, e.get("title") or vurl))
        return Probe(url, info.get("title") or "Playlist", True, entries=entries,
                     has_single_video=_video_id_from_url(url) is not None)
    return Probe(url, info.get("title") or url, False, video_id=info.get("id") or "")


# ---------------------------------------------------------------- download
_REPLACE = {"|": "-", "/": "-", "\\": "-", ":": " -", '"': "'", "?": "", "*": "",
            "<": "", ">": ""}


def _clean(name: str, limit: int = 150) -> str:
    """Make a title safe as a Windows file name, keeping it readable."""
    name = "".join(_REPLACE.get(c, c) if ord(c) >= 32 else " " for c in name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return (name[:limit].rstrip(" .") or "untitled")


def _tag_suffix(title_tags: FilenameTags, desc_tags: FilenameTags) -> str:
    """BPM/key to append to the name: only what the title lacks and the
    description provides."""
    bits = []
    if title_tags.bpm is None and desc_tags.bpm is not None:
        bits.append(f"{desc_tags.bpm:g}")
    if title_tags.key is None and desc_tags.key is not None:
        bits.append(desc_tags.key.short)
    return f" [{' '.join(bits)}]" if bits else ""


def _unique(folder: Path, stem: str, ext: str) -> Path:
    p = folder / f"{stem}{ext}"
    n = 2
    while p.exists():
        p = folder / f"{stem} ({n}){ext}"
        n += 1
    return p


def _log_path() -> Path:
    return app_dir() / "downloads.json"


def already_downloaded(video_id: str) -> Optional[Path]:
    try:
        log = json.loads(_log_path().read_text(encoding="utf-8"))
        p = Path(log.get(video_id, ""))
        return p if video_id in log and p.is_file() else None
    except Exception:
        return None


def _remember(video_id: str, path: Path) -> None:
    try:
        log = json.loads(_log_path().read_text(encoding="utf-8"))
    except Exception:
        log = {}
    log[video_id] = str(path)
    _log_path().write_text(json.dumps(log, indent=1), encoding="utf-8")


ProgressFn = Callable[[str, float], None]  # (stage, fraction 0-1)


FORMATS = {
    # key: (yt-dlp codec, quality, file extension)
    "wav": ("wav", None, ".wav"),  # full quality of the source, ~30 MB per beat
    "mp3": ("mp3", "320", ".mp3"),  # 320 kbps, ~6 MB per beat
}


def download(url: str, dest: Path, progress: Optional[ProgressFn] = None,
             cancel: Optional[threading.Event] = None, fmt: str = "wav") -> Downloaded:
    """Download one video's audio to dest as WAV or MP3. Returns the final file."""
    codec, quality, ext = FORMATS.get(fmt, FORMATS["wav"])
    import yt_dlp

    cancel = cancel or threading.Event()
    report = progress or (lambda *a: None)
    dest.mkdir(parents=True, exist_ok=True)
    tmp = dest / TMP_DIR_NAME
    tmp.mkdir(exist_ok=True)

    def hook(d):
        if cancel.is_set():
            raise Cancelled()
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            got = d.get("downloaded_bytes") or 0
            report("Downloading", (got / total) if total else 0.0)
        elif d.get("status") == "finished":
            report("Converting", 1.0)

    def pp_hook(d):
        if cancel.is_set():
            raise Cancelled()
        if d.get("status") == "started":
            report("Converting", 1.0)

    opts = dict(_base_opts())
    opts.update({
        "format": "bestaudio/best",
        "outtmpl": str(tmp / "%(id)s.%(ext)s"),
        "postprocessors": [dict({"key": "FFmpegExtractAudio", "preferredcodec": codec},
                                **({"preferredquality": quality} if quality else {}))],
        "progress_hooks": [hook],
        "postprocessor_hooks": [pp_hook],
        "overwrites": True,
    })
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except Cancelled:
        _cleanup(tmp)
        raise
    except yt_dlp.utils.DownloadError as e:
        _cleanup(tmp)
        if cancel.is_set():
            raise Cancelled()
        raise RuntimeError(_friendly_error(str(e))) from None

    vid = info.get("id") or "video"
    outs = [Path(d["filepath"]) for d in info.get("requested_downloads") or []
            if d.get("filepath") and Path(d["filepath"]).suffix.lower() == ext
            and Path(d["filepath"]).is_file()]
    if not outs:  # fall back to whatever file of that type is in our temp folder
        outs = sorted(tmp.glob(f"*{ext}"))
    if not outs:
        _cleanup(tmp)
        raise RuntimeError(f"Download finished but no {ext[1:].upper()} was produced.")

    title = info.get("title") or vid
    t_tags = parse_text(title)
    d_tags = parse_description(info.get("description") or "")
    tags = FilenameTags(bpm=t_tags.bpm if t_tags.bpm is not None else d_tags.bpm,
                        key=t_tags.key if t_tags.key is not None else d_tags.key)
    final = _unique(dest, _clean(title) + _tag_suffix(t_tags, d_tags), ext)
    shutil.move(str(outs[0]), str(final))
    _cleanup(tmp)
    _remember(vid, final)
    return Downloaded(final, title, vid, tags)


def _cleanup(tmp: Path) -> None:
    """Remove our own temp folder (only ever the .beatsorter_downloading
    folder this module created)."""
    if tmp.name != TMP_DIR_NAME:
        return
    for p in tmp.glob("*"):
        try:
            p.unlink()
        except OSError:
            pass
    try:
        tmp.rmdir()
    except OSError:
        pass


def _friendly_error(msg: str) -> str:
    low = msg.lower()
    if "private" in low:
        return "This video is private."
    if "sign in" in low or "age" in low and "confirm" in low:
        return "YouTube wants a sign-in for this video (age-restricted or members-only)."
    if "unavailable" in low or "removed" in low:
        return "This video is unavailable."
    if "unsupported url" in low:
        return "That doesn't look like a video link."
    if "http error 403" in low or "signature" in low or "nsig" in low or "challenge" in low:
        return ("YouTube blocked the download. Click \"Update downloader\" and try again; "
                "YouTube changes often and the downloader needs to keep up.")
    return msg.replace("ERROR: ", "")[:300]


def update_downloader() -> Tuple[bool, str]:
    """pip-upgrade yt-dlp (+ its YouTube helper). Returns (ok, message)."""
    import subprocess
    import sys

    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    exe = sys.executable
    if exe.lower().endswith("pythonw.exe"):  # pip needs the console python
        cand = exe[:-len("pythonw.exe")] + "python.exe"
        if os.path.exists(cand):
            exe = cand
    try:
        r = subprocess.run([exe, "-m", "pip", "install", "-U", "yt-dlp[default]", "deno"],
                           capture_output=True, text=True, timeout=600, creationflags=flags)
    except Exception as e:
        return False, str(e)
    if r.returncode != 0:
        return False, (r.stderr or r.stdout)[-800:]
    return True, "Downloader updated. Restart Beat Sorter to use the new version."
