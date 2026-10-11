"""Decide the final BPM, key and destination folder for each file.

Pure logic on cached measurements, so settings changes apply instantly.

Folder layout inside Sorted:
  140-149 BPM/A minor/      confident BPM + key (from filename or detection)
  140-149 BPM/No Key/       tempo but no tonal content (drum loops)
  No BPM/A minor/           tonal but no steady pulse (pads, textures)
  One-Shots/Kicks/, 808s/, Snares/, Hi-Hats/...  short files, by type
  _Review/140-149 BPM/A minor/  detection unsure: best guess, check by ear
BPM range folders are zero-padded ("090-099 BPM") so they sort in order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .config import Settings
from .keys import Key, compare_bpm, compare_keys, parse_key_name
from .pipeline import Record

# Tonality thresholds: below these a file is treated as having no key.
# Set from test audio; check the accuracy report on your own files.
MIN_HARMONIC_RATIO = 0.76
MIN_KEY_CORRELATION = 0.38

NO_KEY = "No Key"
KEY_UNKNOWN = "Key unknown"
NO_BPM = "No BPM"
ONESHOTS = "One-Shots"
REVIEW = "_Review"


@dataclass
class Decision:
    category: str  # "Sorted", "One-Shots", "Review", "Error", "Not analyzed"
    bpm: Optional[float] = None
    bpm_source: str = ""  # "filename" | "detected" | ""
    key: Optional[Key] = None
    key_source: str = ""
    no_key: bool = False
    detected_bpm: Optional[float] = None  # folded into preferred range
    detected_key: Optional[Key] = None
    folder: Tuple[str, ...] = ()  # path parts inside Sorted
    flags: List[str] = field(default_factory=list)
    shot_type: str = ""  # one-shots: Kicks, 808s, Snares, ...

    @property
    def key_label(self) -> str:
        if self.key:
            return self.key.name
        return NO_KEY if self.no_key else (KEY_UNKNOWN if self.category not in ("One-Shots", "Error", "Not analyzed") else "")


def fold_bpm(bpm: float, lo: float, hi: float) -> float:
    """Halve/double a tempo until it lands in [lo, hi] (if possible)."""
    if not bpm or bpm <= 0:
        return 0.0
    b = bpm
    for _ in range(4):
        if b < lo and b * 2 <= hi + 1e-6:
            b *= 2
        elif b > hi and b / 2 >= lo - 1e-6:
            b /= 2
        else:
            break
    return round(b, 1)


BPM_BUCKET = 10  # each folder covers 10 BPM: "140-149 BPM"


def bpm_folder(bpm: float) -> str:
    """BPM range folder, zero-padded so FL's Browser lists them in order
    ("090-099 BPM" comes before "140-149 BPM")."""
    lo = int(round(bpm)) // BPM_BUCKET * BPM_BUCKET
    return f"{lo:03d}-{lo + BPM_BUCKET - 1:03d} BPM"


def detected_key(a: dict) -> Optional[Key]:
    pc = a.get("key_pc", -1)
    if pc is None or pc < 0 or not a.get("key_mode"):
        return None
    return Key(int(pc), a["key_mode"])


# Files at least this long are treated as full beats, which nearly always
# have a key. Real beats measured as low as 0.28 harmonic ratio, so the
# "No Key" test is only used on shorter files (loops).
FULL_TRACK_SECONDS = 30.0


def is_tonal(a: dict) -> bool:
    if a.get("key_pc", -1) < 0:
        return False
    if a.get("duration", 0) >= FULL_TRACK_SECONDS:
        return True
    return (a.get("harm_ratio", 0) >= MIN_HARMONIC_RATIO
            and a.get("key_r", 0) >= MIN_KEY_CORRELATION)


def classify(rec: Record, s: Settings) -> Decision:
    a = rec.analysis
    if not a:
        return Decision("Not analyzed")
    if a.get("error") and not a.get("analyzed"):
        return Decision("Error", flags=[a["error"]])

    dur = a.get("duration", 0.0)
    tags = rec.tags
    ov = rec.override or {}
    ov_bpm = ov.get("bpm")
    ov_key = parse_key_name(ov["key"]) if ov.get("key") not in (None, "none") else None
    ov_nokey = ov.get("key") == "none"

    if dur < s.oneshot_seconds:
        from .oneshots import classify_shot
        typ, how = classify_shot(str(rec.rel), a.get("shot"))
        d = Decision(ONESHOTS, folder=(ONESHOTS, typ),
                     bpm=tags.bpm, bpm_source="filename" if tags.bpm else "",
                     key=tags.key, key_source="filename" if tags.key else "")
        d.shot_type = typ
        if how == "sound":
            d.flags.append(f"{typ.rstrip('s')} (guessed from sound)")
        return d

    d = Decision("Sorted")
    review = False
    if a.get("warning"):
        d.flags.append(a["warning"])

    # ---- BPM ----
    det_bpm = fold_bpm(a.get("bpm", 0.0), s.bpm_min, s.bpm_max)
    bpm_conf = a.get("bpm_conf", 0.0)
    d.detected_bpm = det_bpm or None
    if ov_bpm:  # your fix wins over everything
        d.bpm, d.bpm_source = float(ov_bpm), "you"
    elif tags.bpm:
        d.bpm, d.bpm_source = tags.bpm, "filename"
        rel = compare_bpm(det_bpm, tags.bpm)
        if rel in ("wrong", "triplet") and bpm_conf >= s.bpm_conf_min:
            d.flags.append(f"BPM tag {tags.bpm:g}, detected {det_bpm:g}")
    elif det_bpm and bpm_conf > 0:
        d.bpm, d.bpm_source = det_bpm, "detected"
        if bpm_conf < s.bpm_conf_min:
            review = True
            d.flags.append("low BPM confidence")

    # ---- Key ----
    det_key = detected_key(a)
    key_conf = a.get("key_conf", 0.0)
    tonal = is_tonal(a)
    d.detected_key = det_key if tonal else None
    if ov_key or ov_nokey:  # your fix wins over everything
        d.key, d.key_source = ov_key, "you"
        d.no_key = ov_nokey
    elif tags.key:
        d.key, d.key_source = tags.key, "filename"
        rel = compare_keys(det_key, tags.key)
        if tonal and rel in ("wrong", "fifth", "parallel") and key_conf >= s.key_conf_min:
            d.flags.append(f"key tag {tags.key.short}, detected {det_key.short}")
    elif not tonal:
        d.no_key = True
    elif det_key and not s.use_detected_key:
        d.flags.append(f"key not in name (detector guessed {det_key.short})")
    elif det_key:
        d.key, d.key_source = det_key, "detected"
        d.flags.append("key not in name: detected (often wrong on dark trap beats)")
        if key_conf < s.key_conf_min:
            review = True
            d.flags.append("low key confidence")
    else:
        d.no_key = True

    # A short sound with no steady beat (crash, riser, impact) is a one-shot
    # even if it's longer than the one-shot limit, as long as we can tell
    # what it is.
    from .pipeline import SHOT_MAX_SECONDS
    if not d.bpm and dur < SHOT_MAX_SECONDS and not rec.override:
        from .oneshots import classify_shot
        typ, how = classify_shot(str(rec.rel), a.get("shot"))
        if typ != "Other":
            shot = Decision(ONESHOTS, folder=(ONESHOTS, typ), key=d.key,
                            key_source=d.key_source, shot_type=typ)
            if how == "sound":
                shot.flags.append(f"{typ.rstrip('s')} (guessed from sound)")
            return shot

    bpm_part = bpm_folder(d.bpm) if d.bpm else NO_BPM
    key_part = d.key.name if d.key else (NO_KEY if d.no_key else KEY_UNKNOWN)
    if review:
        d.category = "Review"
        d.folder = (REVIEW, bpm_part, key_part)
    else:
        d.folder = (bpm_part, key_part)
    return d
