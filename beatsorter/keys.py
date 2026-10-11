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
