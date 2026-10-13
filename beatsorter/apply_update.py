"""Standalone update installer. Imports nothing from beatsorter, because it
replaces beatsorter's own files: the app copies this script to a temp
folder and runs it from there, then quits.

  python apply_update.py <app_root> <new_code_root> <app_pid> <log_file>

Steps: wait for the app to close -> stop any leftover Beat Sorter helper
-> back up the current code to _backup/<version> -> swap the new code in
(never leaving a half-replaced folder) -> install packages if
requirements.txt changed -> start the new version and wait until it has
really opened (it writes started.txt). If anything fails, or the new
version doesn't open within START_TIMEOUT seconds, the backup is put back
and the old version started.

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
START_TIMEOUT = 120  # seconds the new version gets to open its window
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


def _retry(fn, tries: int = 60, delay: float = 1.0):
    """Windows won't rename/replace files a running program still holds
    (e.g. a helper that hasn't finished closing). Keep trying for a minute."""
    for n in range(tries):
        try:
            return fn()
        except OSError:
            if n == tries - 1:
                raise
            time.sleep(delay)


def replace_dir(src: Path, dst: Path) -> None:
    """Swap folder dst for a copy of src without ever leaving it half-deleted:
    move dst aside (waits until nothing holds it), copy src in, then delete
    the old one. If the copy fails, the old folder is put back."""
    old = None
    if dst.exists():
        old = dst.with_name(f"{dst.name}.old-{int(time.time() * 1000)}")
        _retry(lambda: os.rename(dst, old))
    try:
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    except Exception:
        shutil.rmtree(dst, ignore_errors=True)
        if old is not None:
            _retry(lambda: os.rename(old, dst))
        raise
    if old is not None:
        shutil.rmtree(old, ignore_errors=True)  # leftovers are cleaned next time


def clean_leftovers(root: Path) -> None:
    for d in CODE_DIRS:
        for p in root.glob(f"{d}.old-*"):
            shutil.rmtree(p, ignore_errors=True)


def copy_code(src: Path, dst: Path) -> None:
    """Copy the app's code from src into dst (dst's .venv/_backup untouched)."""
    for d in CODE_DIRS:
        if (src / d).exists():
            replace_dir(src / d, dst / d)
    for f in root_files(src):
        _retry(lambda f=f: shutil.copy2(f, dst / f.name))


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


def stop_helpers() -> None:
    """End leftover Essentia helpers (deno running essentia_key.mjs) from
    the closed app: Windows won't let us replace files they hold."""
    if os.name != "nt":
        return
    cmd = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "
           "'*essentia_key.mjs*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")
    try:
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd],
                       capture_output=True, timeout=30,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as e:
        log(f"(couldn't check for helpers: {e})")


def relaunch(app: Path):
    """Start Beat Sorter. Returns the process (or None in test mode)."""
    if os.environ.get("BEATSORTER_NO_RELAUNCH"):
        log("relaunch skipped (test mode)")
        return None
    py = venv_python(app, windowless=True)
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return subprocess.Popen([str(py), "-m", PACKAGE], cwd=str(app), creationflags=flags,
                            close_fds=True)


def started_file() -> Path:
    return Path(LOG).parent / "started.txt"


def wait_started(proc, version: str, timeout: float = None) -> bool:
    """Did the new version open its window? (The app writes its version to
    started.txt once it's up.) False if it quit or took too long."""
    timeout = START_TIMEOUT if timeout is None else timeout
    end = time.time() + timeout
    while time.time() < end:
        try:
            if started_file().read_text(encoding="utf-8").strip() == version:
                return True
        except OSError:
            pass
        if proc is not None and proc.poll() is not None:
            time.sleep(1)  # it may have written the file just before exiting
            try:
                return started_file().read_text(encoding="utf-8").strip() == version
            except OSError:
                return False
        time.sleep(0.5)
    return False


def _result(text: str) -> None:
    (Path(LOG).parent / "update_result.txt").write_text(text, encoding="utf-8")


def main(argv) -> int:
    global LOG
    app, new, pid, LOG = Path(argv[1]).resolve(), Path(argv[2]).resolve(), int(argv[3]), argv[4]
    if not (new / PACKAGE / "version.py").exists():
        log(f"ERROR: {new} doesn't look like Beat Sorter")
        return 2
    wait_for_exit(pid)
    clean_leftovers(app)
    old_ver, new_ver = version_of(app), version_of(new)
    log(f"Updating {old_ver} -> {new_ver} in {app}")
    old_req = (app / "requirements.txt").read_bytes() if (app / "requirements.txt").exists() else b""
    stop_helpers()
    bk = backup(app)
    log(f"Backed up {old_ver} to {bk}")

    def restore(reason: str) -> None:
        log(f"Restoring {old_ver}: {reason}")
        try:
            copy_code(bk, app)  # also restores the old requirements.txt
            _result(f"failed\n{old_ver}\n{new_ver}\n{reason}\n")
        except Exception as e2:
            log(f"ERROR while restoring: {e2}")
            _result(f"restore_failed\n{old_ver}\n{new_ver}\n{reason}\n{e2}\n")

    try:
        copy_code(new, app)
        new_req = (app / "requirements.txt").read_bytes()
        if new_req.replace(b"\r", b"") != old_req.replace(b"\r", b""):
            log("requirements.txt changed: installing packages")
            install_requirements(app)
    except Exception as e:
        log(f"ERROR: {e}")
        restore(str(e))
        relaunch(app)
        return 0

    log(f"Installed {new_ver}; starting it")
    try:
        started_file().unlink()
    except OSError:
        pass
    _result(f"ok\n{old_ver}\n{new_ver}\n")
    proc = relaunch(app)
    if proc is None or wait_started(proc, new_ver):
        log(f"Update to {new_ver} complete")
        return 0
    # The new version didn't open: put the old one back.
    log(f"ERROR: v{new_ver} didn't open within {START_TIMEOUT} s")
    if proc.poll() is None:
        proc.kill()
    stop_helpers()
    time.sleep(1)
    restore(f"v{new_ver} didn't open on this computer")
    relaunch(app)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
