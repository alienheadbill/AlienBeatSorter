"""Standalone update installer. Imports nothing from beatsorter, because it
replaces beatsorter's own files: the app copies this script to a temp
folder and runs it from there, then quits.

  python apply_update.py <app_root> <new_code_root> <app_pid> <log_file>

Steps: wait for the app to close -> back up the current code to
_backup/<version> -> copy the new code in -> install packages if
requirements.txt changed -> relaunch Beat Sorter.
If anything fails, the backup is restored and the old version relaunched.

Only the app's own code is touched. The .venv, _backup, and everything in
%LOCALAPPDATA%\\BeatSorter (settings, tags, cache) are never modified, and
the user's beats and Sorted folder are never involved.
"""

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

PACKAGE = "beatsorter"
CODE_DIRS = (PACKAGE, "tests")  # replaced wholesale
ROOT_FILES = ("*.bat", "*.txt", "*.md", "update.json", ".gitignore", ".gitattributes")
KEEP_BACKUPS = 3
LOG = None


def log(msg):
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
    if LOG:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    else:
        print(line)


def version_of(root: Path) -> str:
    try:
        txt = (root / PACKAGE / "version.py").read_text(encoding="utf-8")
        return re.search(r'__version__\s*=\s*"([^"]+)"', txt).group(1)
    except Exception:
        return "unknown"


def wait_for_exit(pid: int, timeout: float = 60.0) -> None:
    if pid <= 0:
        return
    if os.name == "nt":
        import ctypes
        SYNCHRONIZE = 0x00100000
        h = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if h:
            ctypes.windll.kernel32.WaitForSingleObject(h, int(timeout * 1000))
            ctypes.windll.kernel32.CloseHandle(h)
        time.sleep(0.5)  # let Windows release file handles
        return
    end = time.time() + timeout
    while time.time() < end:
        try:
            os.kill(pid, 0)
        except OSError:
            return
        time.sleep(0.2)


def root_files(root: Path):
    seen = set()
    for pat in ROOT_FILES:
        for p in root.glob(pat):
            if p.is_file() and p.name not in seen:
                seen.add(p.name)
                yield p


def copy_code(src: Path, dst: Path) -> None:
    """Copy the app's code from src into dst (dst's .venv/_backup untouched)."""
    for d in CODE_DIRS:
        if (dst / d).exists():
            shutil.rmtree(dst / d)
        if (src / d).exists():
            shutil.copytree(src / d, dst / d,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for f in root_files(src):
        shutil.copy2(f, dst / f.name)


def backup(app: Path) -> Path:
    ver = version_of(app)
    dest = app / "_backup" / ver
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    copy_code(app, dest)
    # prune old backups (keep the newest few)
    olds = sorted((p for p in (app / "_backup").iterdir() if p.is_dir()),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    for p in olds[KEEP_BACKUPS:]:
        shutil.rmtree(p, ignore_errors=True)
    return dest


def venv_python(app: Path, windowless: bool) -> Path:
    if os.name == "nt":
        name = "pythonw.exe" if windowless else "python.exe"
        return app / ".venv" / "Scripts" / name
    return app / ".venv" / "bin" / "python"


def install_requirements(app: Path) -> None:
    py = venv_python(app, windowless=False)
    if not py.exists():
        raise RuntimeError(f"Python environment not found at {py}. Run setup.bat.")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    r = subprocess.run([str(py), "-m", "pip", "install", "-r", str(app / "requirements.txt")],
                       capture_output=True, text=True, creationflags=flags, cwd=str(app))
    log(r.stdout[-2000:])
    if r.returncode != 0:
        raise RuntimeError("Installing packages failed:\n" + (r.stderr or r.stdout)[-1500:])


def relaunch(app: Path) -> None:
    if os.environ.get("BEATSORTER_NO_RELAUNCH"):
        log("relaunch skipped (test mode)")
        return
    py = venv_python(app, windowless=True)
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([str(py), "-m", PACKAGE], cwd=str(app), creationflags=flags,
                     close_fds=True)


def main(argv) -> int:
    global LOG
    app, new, pid, LOG = Path(argv[1]).resolve(), Path(argv[2]).resolve(), int(argv[3]), argv[4]
    if not (new / PACKAGE / "version.py").exists():
        log(f"ERROR: {new} doesn't look like Beat Sorter")
        return 2
    wait_for_exit(pid)
    old_ver, new_ver = version_of(app), version_of(new)
    log(f"Updating {old_ver} -> {new_ver} in {app}")
    old_req = (app / "requirements.txt").read_bytes() if (app / "requirements.txt").exists() else b""
    bk = backup(app)
    log(f"Backed up {old_ver} to {bk}")
    try:
        copy_code(new, app)
        new_req = (app / "requirements.txt").read_bytes()
        if new_req.replace(b"\r", b"") != old_req.replace(b"\r", b""):
            log("requirements.txt changed: installing packages")
            install_requirements(app)
        log(f"Update to {new_ver} complete")
        (Path(LOG).parent / "update_result.txt").write_text(f"ok\n{old_ver}\n{new_ver}\n",
                                                             encoding="utf-8")
    except Exception as e:
        log(f"ERROR: {e}\nRestoring {old_ver}")
        try:
            copy_code(bk, app)  # also restores the old requirements.txt
        except Exception as e2:
            log(f"ERROR while restoring: {e2}")
        (Path(LOG).parent / "update_result.txt").write_text(f"failed\n{old_ver}\n{new_ver}\n{e}\n",
                                                             encoding="utf-8")
    relaunch(app)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
