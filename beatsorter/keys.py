"""Musical key helpers: one consistent naming scheme for all keys.

A key is stored as (pitch_class, mode): pitch_class 0-11 with C = 0,
mode is "major" or "minor". Enharmonic spellings collapse to one name
(A# and Bb are both shown as "Bb").
"""

from __future__ import annotations

from typing import NamedTuple, Optional

# Producer-friendly spelling: sharps for C#/F#, flats for the rest.
PC_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]

_LETTER_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


class Key(NamedTuple):
    pc: int  # 0-11
    mode: str  # "major" | "minor"

    @property
    def name(self) -> str:
        """Folder-style name, e.g. 'A minor', 'Eb major'."""
        return f"{PC_NAMES[self.pc]} {self.mode}"

    @property
    def short(self) -> str:
        """Compact name, e.g. 'Am', 'Eb'."""
        return PC_NAMES[self.pc] + ("m" if self.mode == "minor" else "")

    def relative(self) -> "Key":
        if self.mode == "major":
            return Key((self.pc + 9) % 12, "minor")
        return Key((self.pc + 3) % 12, "major")


def note_to_pc(letter: str, accidental: str = "") -> Optional[int]:
    letter = letter.upper()
    if letter not in _LETTER_PC:
        return None
    pc = _LETTER_PC[letter]
    acc = accidental.lower()
    if acc in ("#", "♯", "sharp", "s"):
        pc += 1
    elif acc in ("b", "♭", "flat"):
        pc -= 1
    elif acc:
        return None
    return pc % 12


def parse_key_name(text: str) -> Optional[Key]:
    """Parse a stored/display key name like 'A minor', 'Am', 'Eb major'."""
    if not text:
        return None
    t = text.strip()
    for pc, nm in enumerate(PC_NAMES):
        if t == f"{nm} major" or t == nm:
            return Key(pc, "major")
        if t == f"{nm} minor" or t == nm + "m":
            return Key(pc, "minor")
    return None


def compare_keys(detected: Optional[Key], labeled: Optional[Key]) -> str:
    """How a detected key relates to a labeled one.

    Returns one of: 'exact', 'relative', 'fifth', 'parallel', 'wrong',
    or 'n/a' if either is missing.
    """
    if detected is None or labeled is None:
        return "n/a"
    if detected == labeled:
        return "exact"
    if detected == labeled.relative():
        return "relative"
    if detected.mode == labeled.mode and (
        (detected.pc - labeled.pc) % 12 in (5, 7)
    ):
        return "fifth"
    if detected.pc == labeled.pc:
        return "parallel"
    return "wrong"


def compare_bpm(detected: Optional[float], labeled: Optional[float]) -> str:
    """'exact' (<=1 BPM off), 'close' (<=2), 'half/double', 'wrong', 'n/a'."""
    if not detected or not labeled:
        return "n/a"
    diff = abs(detected - labeled)
    if diff <= 1.0:
        return "exact"
    if diff <= 2.0:
        return "close"
    for factor in (2.0, 0.5, 1.5, 2 / 3):
        if abs(detected - labeled * factor) <= 2.0 * max(factor, 1.0):
            return "half/double" if factor in (2.0, 0.5) else "triplet"
    return "wrong"


# ---- Camelot wheel (compatible keys) ----
# Number = position on the wheel, A = minor, B = major. Keys that mix well
# are the same number (relative major/minor) or one step either way.
_CAMELOT_MINOR = {8: 1, 3: 2, 10: 3, 5: 4, 0: 5, 7: 6, 2: 7, 9: 8, 4: 9, 11: 10, 6: 11, 1: 12}
_CAMELOT_MAJOR = {11: 1, 6: 2, 1: 3, 8: 4, 3: 5, 10: 6, 5: 7, 0: 8, 7: 9, 2: 10, 9: 11, 4: 12}


def camelot(key: "Key") -> str:
    """Camelot code, e.g. F minor -> '4A', C major -> '8B'."""
    if key.mode == "minor":
        return f"{_CAMELOT_MINOR[key.pc]}A"
    return f"{_CAMELOT_MAJOR[key.pc]}B"


def from_camelot(code: str) -> "Key":
    n, letter = int(code[:-1]), code[-1].upper()
    table = _CAMELOT_MINOR if letter == "A" else _CAMELOT_MAJOR
    pc = next(p for p, num in table.items() if num == n)
    return Key(pc, "minor" if letter == "A" else "major")


def compatible(key: "Key") -> set:
    """The key itself, its relative major/minor, and its two neighbors on
    the wheel (one step up and down)."""
    code = camelot(key)
    n, letter = int(code[:-1]), code[-1]
    other = "B" if letter == "A" else "A"
    up, down = n % 12 + 1, (n - 2) % 12 + 1
    return {from_camelot(c) for c in (code, f"{n}{other}", f"{up}{letter}", f"{down}{letter}")}
