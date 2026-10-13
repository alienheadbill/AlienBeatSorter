"""Problem reports and comments from users. No GUI code here.

Reports go to the project's GitHub Issues (for people with a GitHub
account) or by email (everyone else). Where they go is set in update.json:
  {"repo": "owner/name", "branch": "release", "support_email": "you@example.com"}

Nothing is sent automatically: the app opens a pre-filled GitHub issue in
the browser, or a pre-filled email in the user's mail app, and the user
reviews and sends it. Technical details are shown to the user first and
have personal folder names replaced (e.g. C:\\Users\\Bill -> ~).
"""

from __future__ import annotations

import json
import os
import platform
import re
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import quote, urlencode

from .config import app_dir
from .version import __version__

APP_ROOT = Path(__file__).resolve().parent.parent
GITHUB_MAX = 6000  # keep issue links well under browsers' URL limits
EMAIL_MAX = 1700  # Windows mail links get cut off around 2,000 characters
KINDS = {"problem": "Bug", "idea": "Idea"}


def settings() -> dict:
    try:
        return json.loads((APP_ROOT / "update.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def repo() -> str:
    r = (settings().get("repo") or "").strip().strip("/")
    return r if re.fullmatch(r"[\w.-]+/[\w.-]+", r) else ""


def support_email() -> str:
    e = (settings().get("support_email") or "").strip()
    return e if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", e) else ""


def scrub(text: str) -> str:
    """Replace the user's home folder and user name in paths with ~."""
    home = str(Path.home())
    out = text.replace(home, "~").replace(home.replace("\\", "/"), "~")
    user = os.environ.get("USERNAME") or os.environ.get("USER") or ""
    if len(user) >= 3:
        out = re.sub(rf"(?i)([\\/]Users[\\/]){re.escape(user)}", r"\1~", out)
    return out


def _tail(path: Path, lines: int) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    except OSError:
        return ""


def _pkg(name: str) -> str:
    try:
        from importlib.metadata import version
        return version(name)
    except Exception:
        return "not installed"


def diagnostics(n_beats: Optional[int] = None, extra: str = "") -> str:
    """Technical details that help find a problem (shown to the user before
    anything is sent)."""
    lines = [
        f"Beat Sorter {__version__}",
        f"Windows/OS: {platform.platform()}",
        f"Python {platform.python_version()} ({'64' if sys.maxsize > 2**32 else '32'}-bit)",
        "Packages: " + ", ".join(f"{p} {_pkg(p)}" for p in
                                ("librosa", "numpy", "soundfile", "sounddevice", "yt-dlp",
                                 "deno", "tkinterdnd2")),
    ]
    if n_beats is not None:
        lines.append(f"Beats in library: {n_beats}")
    d = app_dir()
    for name, n in (("error.log", 40), ("update.log", 15)):
        t = _tail(d / name, n)
        if t.strip():
            lines += ["", f"--- last lines of {name} ---", t]
    if extra:
        lines += ["", "--- error ---", extra]
    return scrub("\n".join(lines))


def compose(kind: str, message: str, details: str = "") -> tuple:
    """(title, body) for a report. kind: "problem" or "idea"."""
    message = message.strip()
    first = message.splitlines()[0] if message else ""
    title = f"[{KINDS.get(kind, 'Bug')}] {first[:80] or ('Problem report' if kind == 'problem' else 'Idea')}"
    body = message or "(no description)"
    if details.strip():
        body += "\n\n<details><summary>Technical details</summary>\n\n```\n" + details.strip() + "\n```\n</details>"
    return title, body


def _fit(body: str, limit: int, note: str) -> str:
    if len(body) <= limit:
        return body
    return body[:limit - len(note)] + note


def github_url(title: str, body: str) -> str:
    """Link that opens a new, pre-filled GitHub issue (empty if no repo)."""
    r = repo()
    if not r:
        return ""
    body = _fit(body, GITHUB_MAX, "\n…\n(cut short: the full report was copied, paste it here)\n```\n</details>")
    return f"https://github.com/{r}/issues/new?" + urlencode({"title": title, "body": body})


def email_url(title: str, body: str) -> str:
    """mailto: link with the report filled in (empty if no email is set)."""
    to = support_email()
    if not to:
        return ""
    plain = body.replace("<details><summary>Technical details</summary>", "Technical details:")
    plain = plain.replace("</details>", "").replace("```", "")
    plain = _fit(plain, EMAIL_MAX, "\n…\n(cut short: the full report was copied, paste it here)")
    return f"mailto:{to}?subject={quote(title)}&body={quote(plain)}"
