"""Read BPM and key tags that are already written in a filename.

Design rule: when unsure, return nothing. A missed tag just means the
file gets analyzed; a wrong tag would sort the file into the wrong folder.

Handled, for example:
  "Midnight 140bpm Am"        -> 140, A minor
  "dark_beat_C#min_92"        -> 92, C# minor
  "Type Beat (140 BPM, F#m)"  -> 140, F# minor
  "loop - 128 - Bb"           -> 128, Bb major (bare note next to BPM)
  "Song in A minor"           -> key only
Ignored on purpose: "808", "v2", "beat 3", "2024", "Who I Am" (no BPM
nearby, so "Am" is treated as a word, not a key).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePath
from typing import List, Optional, Tuple

from .keys import Key, note_to_pc

BPM_MIN, BPM_MAX = 40.0, 250.0  # with an explicit "bpm" label
BARE_MIN, BARE_MAX = 60.0, 200.0  # bare number next to a key

_MODE_WORDS = {
    "min": "minor", "minor": "minor", "maj": "major", "major": "major",
}
_ACC_WORDS = {"sharp": "#", "flat": "b"}

# One token = a whole key, e.g. "Am", "F#m", "Ebmaj", "Cminor", "Bb", "A".
_KEY_TOKEN = re.compile(
    r"^(?P<note>[A-Ga-g])(?P<acc>#|b|sharp|flat)?(?P<mode>m|min|minor|maj|major)?$",
    re.IGNORECASE,
)

_TOKENIZE = re.compile(r"\d+(?:\.\d+)?|[A-Za-z][A-Za-z#]*")


@dataclass
class FilenameTags:
    bpm: Optional[float] = None
    key: Optional[Key] = None

    @property
    def empty(self) -> bool:
        return self.bpm is None and self.key is None


@dataclass
class _KeyHit:
    index: int  # token index (first token of the key)
    end: int  # last token index
    key: Key
    strong: bool  # strong = unmistakably a key (e.g. "F#m", "A minor")
    tight: bool = False  # only counts right next to a BPM ("fm", bare "A")


def _tokens(stem: str) -> List[str]:
    s = stem.replace("♯", "#").replace("♭", "b")
    s = re.sub(r"(?i)bpm", " bpm ", s)
    return _TOKENIZE.findall(s)


def _is_number(tok: str) -> bool:
    return tok[0].isdigit()


def _parse_key_token(tok: str) -> Optional[Tuple[Key, bool, bool]]:
    """Single-token key. Returns (key, strong, tight) or None."""
    m = _KEY_TOKEN.match(tok)
    if not m:
        return None
    note, acc, mode = m.group("note"), m.group("acc") or "", m.group("mode") or ""
    mode_l = mode.lower()
    long_mode = mode_l in ("min", "minor", "maj", "major")

    # Lowercase short keys ("fm", "gm", "am") are often just words, so they
    # only count directly next to a BPM number ("127_fm"). Lowercase with
    # no mode ("a", "bb") never counts.
    lower_short = note.islower() and not long_mode
    if lower_short and mode_l != "m":
        return None
    # A one-letter mode must be a lowercase "m" ("AM" is a time of day).
    if mode == "M":
        return None
    pc = note_to_pc(note, acc)
    if pc is None:
        return None
    if mode_l in ("m", "min", "minor"):
        key_mode = "minor"
    else:
        key_mode = "major"  # "maj", "major", or no mode (uppercase = major)

    # Strong: spelled-out mode, or accidental + minor ("F#m", "Ebm").
    strong = (long_mode or (bool(acc) and mode_l == "m")) and not lower_short
    tight = lower_short or (len(tok) == 1)
    return Key(pc, key_mode), strong, tight


def _find_keys(toks: List[str]) -> List[_KeyHit]:
    hits: List[_KeyHit] = []
    i = 0
    while i < len(toks):
        tok = toks[i]
        # Multi-token forms: "A minor", "C# Min", "F sharp minor".
        if re.fullmatch(r"[A-Ga-g](#|b)?", tok):
            j = i + 1
            acc = ""
            note = tok[0]
            if len(tok) > 1:
                acc = tok[1:]
            elif j < len(toks) and toks[j].lower() in _ACC_WORDS:
                acc = _ACC_WORDS[toks[j].lower()]
                j += 1
            if j < len(toks) and toks[j].lower() in _MODE_WORDS:
                pc = note_to_pc(note, acc)
                if pc is not None:
                    # "A minor" is a strong tag; lowercase "a minor" could be
                    # ordinary words, so it needs a BPM nearby.
                    hits.append(_KeyHit(i, j, Key(pc, _MODE_WORDS[toks[j].lower()]),
                                        note.isupper()))
                    i = j + 1
                    continue
        parsed = _parse_key_token(tok)
        if parsed:
            key, strong, tight = parsed
            hits.append(_KeyHit(i, i, key, strong, tight))
        i += 1
    return hits


def _find_bpms(toks: List[str]) -> Tuple[List[Tuple[int, float]], List[Tuple[int, float]]]:
    """Returns (explicit, bare) as lists of (token_index, value)."""
    explicit, bare = [], []
    used = set()
    for i, tok in enumerate(toks):
        if tok.lower() != "bpm":
            continue
        for j in (i - 1, i + 1):  # "140 bpm" preferred over "bpm 140"
            if 0 <= j < len(toks) and _is_number(toks[j]) and j not in used:
                v = float(toks[j])
                if BPM_MIN <= v <= BPM_MAX:
                    explicit.append((j, v))
                    used.add(j)
                    break
    for i, tok in enumerate(toks):
        if i in used or not _is_number(tok):
            continue
        if tok.startswith("0") or "." in tok:
            continue
        v = float(tok)
        if BARE_MIN <= v <= BARE_MAX:
            bare.append((i, v))
    return explicit, bare


def _near(a_start: int, a_end: int, b: int, dist: int) -> bool:
    return (a_start - dist) <= b <= (a_end + dist)


def parse_filename(name: str) -> FilenameTags:
    """Parse BPM/key from a filename (with or without folders/extension)."""
    return parse_text(PurePath(name).stem)


def parse_text(text: str) -> FilenameTags:
    """Parse BPM/key from free text such as a YouTube title."""
    toks = _tokens(text)
    if not toks:
        return FilenameTags()

    keys = _find_keys(toks)
    explicit, bare = _find_bpms(toks)

    # Positions where a "key" label word appears ("Key Am", "key of A minor").
    key_words = {i for i, t in enumerate(toks) if t.lower() == "key"}

    # --- BPM ---
    bpm: Optional[float] = None
    explicit_vals = {v for _, v in explicit}
    if len(explicit_vals) == 1:
        bpm = explicit_vals.pop()
    elif len(explicit_vals) > 1:
        bpm = None  # conflicting labels: unsure
    else:
        # A bare number counts when it sits next to a key. If several
        # numbers qualify ("Speeding in the 64 150 Em"), the one closest to
        # the key wins; a tie means unsure.
        best: List[Tuple[int, float]] = []
        for idx, v in bare:
            dists = [min(abs(idx - k.index), abs(idx - k.end)) for k in keys
                     if min(abs(idx - k.index), abs(idx - k.end)) <= (1 if k.tight else 2)]
            if dists:
                best.append((min(dists), v))
        if best:
            best.sort()
            if len(best) == 1 or best[0][0] < best[1][0] or best[0][1] == best[1][1]:
                bpm = best[0][1]
        # Name ending in a plain number ("Treetop_144"): treat it as the BPM
        # when nothing else gave one. If it's really part of the title,
        # detection will disagree and the file gets flagged.
        if bpm is None and len(toks) >= 2 and bare and bare[-1][0] == len(toks) - 1 \
                and not keys:
            bpm = bare[-1][1]

    # --- Key ---
    bpm_positions = [i for i, _ in explicit] + [
        i for i, v in bare if bpm is not None and v == bpm
    ]
    accepted: List[_KeyHit] = []
    for k in keys:
        if k.strong:
            accepted.append(k)
            continue
        # Weak key ("Am", "Bb", "A"): needs a BPM or the word "key" nearby.
        if any(kw in (k.index - 1, k.index - 2) for kw in key_words):
            accepted.append(k)
            continue
        dist = 1 if k.tight else 3
        if any(_near(k.index, k.end, p, dist) for p in bpm_positions):
            accepted.append(k)

    key: Optional[Key] = None
    strong = {k.key for k in accepted if k.strong}
    weak = {k.key for k in accepted if not k.strong}
    if len(strong) == 1:
        key = next(iter(strong))
    elif not strong and len(weak) == 1:
        key = next(iter(weak))
    # else: none found, or conflicting keys -> unsure, leave empty

    return FilenameTags(bpm=bpm, key=key)


def parse_description(text: str) -> FilenameTags:
    """BPM/key from a video description. Only lines that mention "bpm" or
    "key" are read, so links, dates and contact info are ignored."""
    out = FilenameTags()
    for line in (text or "").splitlines():
        low = line.lower()
        if "bpm" not in low and "key" not in low and "tempo" not in low:
            continue
        line = re.sub(r"(?i)tempo", "bpm", line)
        t = parse_text(line)
        if out.bpm is None and t.bpm is not None and "bpm" in line.lower():
            out.bpm = t.bpm
        if out.key is None and t.key is not None:
            out.key = t.key
        if out.bpm is not None and out.key is not None:
            break
    return out
