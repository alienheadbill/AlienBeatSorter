"""How the Sorted folder is laid out, and what dragging a beat onto a
folder means. Pure logic (no GUI, no disk), so it's easy to test.

Folder names produced here are "canonical" (e.g. "140-149 BPM", "F minor").
Your renames are a separate name map applied when building the Sorted
folder and when showing the tree, so a renamed folder still knows what it
means ("Fast trap" is still 140-149 BPM when you drop a beat on it).
"""

from __future__ import annotations

import re
from typing import Dict, Optional, Tuple

from .keys import Key, camelot, parse_key_name

# layout id -> label shown in the app
LAYOUTS = {
    "bpm_key": "BPM → Key",
    "key_bpm": "Key → BPM",
    "camelot_bpm": "Camelot → BPM",
    "bpm": "BPM only",
    "key": "Key only",
    "flat": "All in one folder",
}
DEFAULT_LAYOUT = "bpm_key"
ALL_BEATS = "All Beats"
MY_FOLDERS = "My Folders"

_BPM_RE = re.compile(r"^(\d{2,3})-(\d{2,3}) BPM$")
_CAMELOT_RE = re.compile(r"^(\d{1,2})([AB]) - (.+)$")


def camelot_folder(key: Key) -> str:
    """'08A - A minor': zero-padded so 1A..12B list in wheel order."""
    code = camelot(key)  # e.g. "8A"
    return f"{int(code[:-1]):02d}{code[-1]} - {key.name}"


def arrange(bpm_part: str, key_part: str, key: Optional[Key], layout: str) -> Tuple[str, ...]:
    """Folder parts for one beat under the chosen layout."""
    k = camelot_folder(key) if key is not None else key_part
    return {
        "bpm_key": (bpm_part, key_part),
        "key_bpm": (key_part, bpm_part),
        "camelot_bpm": (k, bpm_part),
        "bpm": (bpm_part,),
        "key": (key_part,),
        "flat": (ALL_BEATS,),
    }.get(layout, (bpm_part, key_part))


def display(part: str, names: Dict[str, str]) -> str:
    """A folder's name as you renamed it (or its own name)."""
    return names.get(part, part) if names else part


def bpm_range(part: str) -> Optional[Tuple[int, int]]:
    m = _BPM_RE.match(part)
    return (int(m.group(1)), int(m.group(2))) if m else None


def key_of(part: str):
    """Key meant by a folder name: a Key, "none" for No Key, or None if the
    folder isn't about key."""
    if part == "No Key":
        return "none"
    m = _CAMELOT_RE.match(part)
    if m:
        return parse_key_name(m.group(3))
    return parse_key_name(part)


def fit_bpm(bpm: Optional[float], lo: int, hi: int) -> Optional[float]:
    """The beat's tempo moved into lo..hi by the usual half/double (or
    triplet) mix-ups, or None if none of those fit."""
    if not bpm:
        return None
    for b in (bpm, bpm * 2, bpm / 2, bpm * 1.5, bpm / 1.5, bpm * 4, bpm / 4):
        if lo <= round(b, 1) < hi + 1:
            return round(b, 1)
    return None


def fix_for_drop(parts: Tuple[str, ...], bpm: Optional[float], key: Optional[Key]) -> dict:
    """What dropping a beat on an auto folder should change.

    Returns {"bpm": float?, "key": str?, "ask_bpm": (lo, hi)?}. "key" is a
    key name or "none". "ask_bpm" means the beat's tempo can't simply be
    halved/doubled into that range, so the user should type one.
    """
    out: dict = {}
    for p in parts:
        r = bpm_range(p)
        if r:
            lo, hi = r
            new = fit_bpm(bpm, lo, hi)
            if new is None:
                out["ask_bpm"] = (lo, hi)
            elif new != bpm:
                out["bpm"] = new
            continue
        k = key_of(p)
        if k == "none":
            out["key"] = "none"
        elif k is not None and k != key:
            out["key"] = k.name
    return out


def is_drop_target(parts: Tuple[str, ...]) -> bool:
    """Auto folders a beat can be dropped on to change its BPM/key."""
    if not parts or parts[0] in ("One-Shots", MY_FOLDERS, "Tags"):
        return False
    return any(bpm_range(p) or key_of(p) is not None for p in parts)
