"""CSV export and the filename-tag accuracy report."""

from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple

from .classifier import Decision, detected_key, fold_bpm, is_tonal
from .keys import compare_bpm, compare_keys
from .pipeline import Record

CSV_FIELDS = ["file", "folder_in_sorted", "category", "bpm", "bpm_source", "key",
              "key_source", "detected_bpm", "bpm_confidence", "detected_key",
              "key_confidence", "duration_s", "flags", "full_path"]


def write_csv(path: Path, records: List[Record], decisions: List[Decision]) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:  # BOM: Excel-friendly
        w = csv.writer(f)
        w.writerow(CSV_FIELDS)
        for r, d in zip(records, decisions):
            a = r.analysis
            w.writerow([
                r.path.name, "/".join(d.folder), d.category,
                f"{d.bpm:g}" if d.bpm else "", d.bpm_source, d.key_label, d.key_source,
                f"{d.detected_bpm:g}" if d.detected_bpm else "",
                a.get("bpm_conf", ""),
                d.detected_key.name if d.detected_key else "",
                a.get("key_conf", ""), a.get("duration", ""),
                "; ".join(d.flags), str(r.path),
            ])


@dataclass
class Accuracy:
    bpm_counts: Counter = field(default_factory=Counter)
    key_counts: Counter = field(default_factory=Counter)
    bpm_total: int = 0
    key_total: int = 0
    disagreements: List[Tuple[str, str]] = field(default_factory=list)

    def summary_lines(self) -> List[str]:
        lines = []

        def pct(n, t):
            return f"{100 * n / t:.0f}%" if t else "-"

        lines.append(f"BPM: {self.bpm_total} files with a BPM in the name")
        for k in ("exact", "close", "half/double", "triplet", "wrong"):
            if self.bpm_counts[k]:
                lines.append(f"   {k:12} {self.bpm_counts[k]:5}  {pct(self.bpm_counts[k], self.bpm_total)}")
        lines.append(f"Key: {self.key_total} files with a key in the name")
        labels = {"exact": "exact", "relative": "relative maj/min", "fifth": "a fifth off",
                  "parallel": "major/minor flip", "wrong": "wrong", "no key": "said no key"}
        for k in ("exact", "relative", "fifth", "parallel", "wrong", "no key"):
            if self.key_counts[k]:
                lines.append(f"   {labels[k]:17} {self.key_counts[k]:5}  {pct(self.key_counts[k], self.key_total)}")
        return lines


def accuracy(records: List[Record], bpm_min: float, bpm_max: float,
             oneshot_seconds: float) -> Accuracy:
    """Compare detection with filename tags (one-shots excluded)."""
    acc = Accuracy()
    for r in records:
        a = r.analysis
        if not a or not a.get("analyzed") or a.get("duration", 0) < oneshot_seconds:
            continue
        if r.tags.bpm:
            det = fold_bpm(a.get("bpm", 0), bpm_min, bpm_max)
            rel = compare_bpm(det, r.tags.bpm)
            if rel != "n/a":
                acc.bpm_total += 1
                acc.bpm_counts[rel] += 1
                if rel not in ("exact", "close"):
                    acc.disagreements.append((r.path.name, f"BPM: name {r.tags.bpm:g}, detected {det:g}"))
        if r.tags.key:
            acc.key_total += 1
            if not is_tonal(a):
                acc.key_counts["no key"] += 1
                continue
            k = detected_key(a)
            rel = compare_keys(k, r.tags.key)
            acc.key_counts[rel] += 1
            if rel != "exact" and k:
                acc.disagreements.append((r.path.name, f"Key: name {r.tags.key.short}, detected {k.short}"))
    return acc


def suggest_bpm_range(records: List[Record], oneshot_seconds: float) -> Tuple[float, float, float]:
    """Find the one-octave window [lo, 2*lo] that best matches the BPMs in
    your filenames. Returns (lo, hi, match_rate)."""
    pairs = [(r.analysis.get("bpm", 0), r.tags.bpm) for r in records
             if r.tags.bpm and r.analysis.get("analyzed")
             and r.analysis.get("duration", 0) >= oneshot_seconds
             and r.analysis.get("bpm", 0) > 0]
    if not pairs:
        return 0.0, 0.0, 0.0
    best = (0.0, 0.0, -1.0)
    for lo in range(55, 121, 1):
        hi = lo * 2 - 1
        ok = sum(compare_bpm(fold_bpm(d, lo, hi), t) in ("exact", "close") for d, t in pairs)
        rate = ok / len(pairs)
        if rate > best[2] + 1e-9:
            best = (float(lo), float(hi), rate)
    return best
