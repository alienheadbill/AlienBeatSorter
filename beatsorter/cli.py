"""Command-line version (useful for testing without the window).

  python -m beatsorter.cli analyze "D:\\Beats" [--csv results.csv]
  python -m beatsorter.cli build "D:\\Beats" "D:\\Beats Sorted" [--dry-run] [--allow-copy]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .builder import NeedsCopy, UnsafePath, build, check_folders, plan
from .classifier import classify
from .config import Settings
from .pipeline import analyze_library
from .report import accuracy, suggest_bpm_range, write_csv


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="beatsorter")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("analyze")
    a.add_argument("source")
    a.add_argument("--csv")
    b = sub.add_parser("build")
    b.add_argument("source")
    b.add_argument("output")
    b.add_argument("--dry-run", action="store_true")
    b.add_argument("--allow-copy", action="store_true")
    for p in (a, b):
        p.add_argument("--bpm-min", type=float)
        p.add_argument("--bpm-max", type=float)
    args = ap.parse_args(argv)

    s = Settings.load()
    if args.bpm_min:
        s.bpm_min = args.bpm_min
    if args.bpm_max:
        s.bpm_max = args.bpm_max
    source = Path(args.source)
    out = Path(args.output) if args.cmd == "build" else None
    if out:
        try:
            check_folders(source, out)
        except UnsafePath as e:
            print("Stopped:", e)
            return 2

    def prog(stage, done, total, rec):
        if total and (done % 10 == 0 or done == total):
            print(f"\r{stage} {done}/{total}", end="", flush=True)

    records = analyze_library(s, source, exclude=[out] if out else None, progress=prog)
    print()
    decisions = [classify(r, s) for r in records]

    for r, d in zip(records, decisions):
        print(f"{r.rel}  ->  {'/'.join(d.folder) or d.category}"
              f"{'   ! ' + '; '.join(d.flags) if d.flags else ''}")

    acc = accuracy(records, s.bpm_min, s.bpm_max, s.oneshot_seconds)
    print("\nDetection vs. filename tags:")
    print("\n".join(acc.summary_lines()))
    lo, hi, rate = suggest_bpm_range(records, s.oneshot_seconds)
    if rate > 0:
        print(f"Suggested BPM range from your tags: {lo:g}-{hi:g} ({rate:.0%} match)")

    if args.cmd == "analyze" and args.csv:
        write_csv(Path(args.csv), records, decisions)
        print("CSV written:", args.csv)

    if args.cmd == "build":
        items = plan(records, decisions, out, s.add_tags_to_names)
        if args.dry_run:
            print(f"\nDry run: would create {len(items)} files in {out}")
            return 0
        try:
            res = build(items, source, out, allow_copy=args.allow_copy)
        except NeedsCopy as e:
            print(f"\n{e.reason} Copying would use {e.total_bytes / 1e9:.2f} GB. "
                  "Re-run with --allow-copy to copy instead.")
            return 3
        print(f"\nDone ({res.mode}): {res.linked} linked, {res.copied} copied, "
              f"{res.skipped} skipped, {len(res.errors)} errors.")
        for e in res.errors[:20]:
            print("  ", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
