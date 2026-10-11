"""Self-update from a GitHub repository's main branch. No GUI code here.

The repository is set in update.json next to setup.bat:
  {"repo": "owner/name", "branch": "main"}

check()   -> is a newer version on GitHub?   (reads beatsorter/version.py)
stage()   -> download + unpack it to a temp folder
launch()  -> start apply_update.py (from a temp copy) and let the app quit;
             it swaps the code, installs new packages if needed, relaunches.
rollback  -> same installer, pointed at the newest _backup/<version>.
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from .config import app_dir
from .version import __version__

APP_ROOT = Path(__file__).resolve().parent.parent
RAW_BASE = os.environ.get("BEATSORTER_RAW_BASE", "https://raw.githubusercontent.com")
ZIP_BASE = os.environ.get("BEATSORTER_ZIP_BASE", "https://codeload.github.com")


@dataclass
class UpdateInfo:
    version: str
    notes: str
    repo: str
    branch: str


def parse_version(v: str) -> Tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:4]) or (0,)


def config() -> Tuple[str, str]:
    """(repo, branch) from update.json, or ("", "") if not set up."""
    try:
        data = json.loads((APP_ROOT / "update.json").read_text(encoding="utf-8"))
        repo = (data.get("repo") or "").strip().strip("/")
        if re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
            return repo, (data.get("branch") or "main").strip()
    except Exception:
        pass
    return "", ""


def _ssl_context() -> ssl.SSLContext:
    """Trust the computer's own certificate store (on Windows, the Windows
    store, which also covers networks with their own security proxy) plus
    certifi's standard bundle."""
    ctx = ssl.create_default_context()
    try:
        import certifi
        ctx.load_verify_locations(certifi.where())
    except Exception:
        pass
    return ctx


def _get(url: str, timeout: float = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": f"BeatSorter/{__version__}",
                                               "Cache-Control": "no-cache"})
    ctx = None if url.startswith("http://") else _ssl_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return r.read()


def check() -> Optional[UpdateInfo]:
    """Newer version available? None if up to date or not configured.
    Raises on network errors so the caller can say so."""
    repo, branch = config()
    if not repo:
        return None
    txt = _get(f"{RAW_BASE}/{repo}/{branch}/beatsorter/version.py").decode("utf-8", "replace")
    m = re.search(r'__version__\s*=\s*"([^"]+)"', txt)
    if not m:
        raise RuntimeError("Couldn't read the version on GitHub.")
    latest = m.group(1)
    if parse_version(latest) <= parse_version(__version__):
        return None
    notes = ""
    try:
        log = _get(f"{RAW_BASE}/{repo}/{branch}/CHANGELOG.txt").decode("utf-8", "replace")
        notes = changelog_section(log, latest)
    except Exception:
        pass
    return UpdateInfo(latest, notes, repo, branch)


def changelog_section(text: str, version: str) -> str:
    """The notes under the '1.5.1' heading of CHANGELOG.txt."""
    lines, out, on = text.splitlines(), [], False
    for ln in lines:
        if re.match(r"^\s*v?\d+\.\d+", ln):
            if on:
                break
            on = parse_version(ln.split()[0]) == parse_version(version)
            continue
        if on:
            out.append(ln)
    return "\n".join(out).strip()


def stage(info: UpdateInfo) -> Path:
    """Download the branch zip and unpack it. Returns the new code's root."""
    data = _get(f"{ZIP_BASE}/{info.repo}/zip/refs/heads/{info.branch}", timeout=120)
    dest = Path(tempfile.mkdtemp(prefix="beatsorter_update_"))
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for m in z.infolist():
            parts = Path(m.filename).parts
            # GitHub zips have one top folder ("name-main/"); drop it, and
            # refuse anything that would land outside dest.
            if len(parts) < 2 or ".." in parts or Path(m.filename).is_absolute():
                continue
            target = dest.joinpath(*parts[1:])
            if m.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(m) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
    if not (dest / "beatsorter" / "version.py").exists():
        raise RuntimeError("The download doesn't look like Beat Sorter.")
    return dest


def _launch_installer(new_root: Path) -> None:
    """Run apply_update.py from a temp copy (it replaces our own files)."""
    tmp = Path(tempfile.mkdtemp(prefix="beatsorter_installer_"))
    script = tmp / "apply_update.py"
    shutil.copy2(Path(__file__).with_name("apply_update.py"), script)
    py = sys.executable
    if py.lower().endswith("pythonw.exe"):  # use the console python, hidden
        cand = py[:-len("pythonw.exe")] + "python.exe"
        if os.path.exists(cand):
            py = cand
    log = app_dir() / "update.log"
    # Windows: no console window, and keep running after the app quits.
    flags = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
             | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)) if os.name == "nt" else 0
    subprocess.Popen([py, str(script), str(APP_ROOT), str(new_root), str(os.getpid()), str(log)],
                     cwd=str(tmp), creationflags=flags, close_fds=True)


def install(new_root: Path) -> None:
    """Start installing new_root; the caller must quit the app right after."""
    _launch_installer(new_root)


def latest_backup() -> Optional[Tuple[str, Path]]:
    b = APP_ROOT / "_backup"
    if not b.is_dir():
        return None
    dirs = sorted((p for p in b.iterdir() if (p / "beatsorter" / "version.py").exists()),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    return (dirs[0].name, dirs[0]) if dirs else None


def rollback() -> Optional[str]:
    """Reinstall the newest backup. Returns its version, or None."""
    lb = latest_backup()
    if not lb:
        return None
    ver, path = lb
    staged = Path(tempfile.mkdtemp(prefix="beatsorter_rollback_"))
    shutil.copytree(path, staged, dirs_exist_ok=True)  # backup itself gets rotated
    _launch_installer(staged)
    return ver


def last_result() -> Optional[Tuple[str, str, str, str]]:
    """Result of the last update attempt (status, old, new, error), once.
    Read after the app restarts so it can say 'Updated to 1.5.1'."""
    p = app_dir() / "update_result.txt"
    if not p.exists():
        return None
    try:
        lines = p.read_text(encoding="utf-8").splitlines() + ["", "", "", ""]
        p.unlink()
        return lines[0], lines[1], lines[2], "\n".join(lines[3:]).strip()
    except Exception:
        return None
