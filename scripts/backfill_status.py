#!/usr/bin/env python3
"""One-shot backfill: derive status from business fields for historical proposals.

Reads db/proposals.csv, runs derive_status_from_fields() on every row where
status == "intake" but business fields (stage / acceptance / prd_confirmation /
tech_expectations / deployment_url) suggest a more advanced status, and writes
the corrected rows back. Original CSV is backed up to db/proposals.csv.bak
before any change.

Usage:
    python scripts/backfill_status.py            # dry-run (shows plan, no writes)
    python scripts/backfill_status.py --apply    # actually write the corrections
"""
import argparse
import csv
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

# Bootstrap so we can import the package
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ai_superpower.models import (  # noqa: E402
    PROPOSALS_CSV_HEADERS,
    STATUS_TRANSITIONS,
    derive_status_from_fields,
)


def plan(csv_path: Path) -> tuple[list[tuple[int, str, str, str]], Counter, int]:
    """Return (changes, distribution, skipped_illegal_count).

    Note: derived status is applied unconditionally here, mirroring the
    storage layer's behavior. The state machine STATUS_TRANSITIONS only
    applies to explicit update_proposal_status() calls; auto-derive from
    business fields accepts any derived value since business fields are
    the ground truth.
    """
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    changes = []
    skipped_illegal = 0
    for idx, row in enumerate(rows):
        if row.get("status") != "intake":
            continue
        derived = derive_status_from_fields(row)
        if not derived or derived == "intake":
            continue
        changes.append((idx, row.get("id", ""), "intake", derived))

    distribution = Counter(c[3] for c in changes)
    return changes, distribution, skipped_illegal


def apply(csv_path: Path, changes: list[tuple[int, str, str, str]]) -> int:
    """Apply changes in-place. Returns number of rows written."""
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    today = datetime.now().strftime("%Y-%m-%d")
    for idx, pid, old, new in changes:
        rows[idx]["status"] = new
        rows[idx]["last_update"] = today

    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PROPOSALS_CSV_HEADERS)
        writer.writeheader()
        writer.writerows(rows)
    return len(changes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Actually write changes (default: dry-run)")
    parser.add_argument("--csv", type=Path, default=ROOT / "db" / "proposals.csv",
                        help="Path to proposals.csv (default: db/proposals.csv)")
    args = parser.parse_args()

    if not args.csv.exists():
        print(f"ERROR: {args.csv} does not exist", file=sys.stderr)
        sys.exit(1)

    print(f"Reading {args.csv}")
    changes, distribution, skipped = plan(args.csv)
    print(f"\nProposed changes: {len(changes)}")
    print(f"Skipped (illegal transition from intake): {skipped}")
    print("\nDistribution of new statuses:")
    for status, count in distribution.most_common():
        print(f"  {status:25s} : {count}")

    if not changes:
        print("\nNo changes needed. Done.")
        return

    # Show first few changes as sample
    print("\nSample changes (first 10):")
    for idx, pid, old, new in changes[:10]:
        print(f"  row {idx:4d} | {pid} | {old} → {new}")

    if not args.apply:
        print(f"\n[DRY-RUN] Re-run with --apply to write {len(changes)} corrections.")
        print("Original CSV will be backed up to {csv}.bak".format(csv=args.csv))
        return

    # Backup first
    backup = args.csv.with_suffix(args.csv.suffix + ".bak")
    shutil.copy2(args.csv, backup)
    print(f"\nBacked up to {backup}")

    n = apply(args.csv, changes)
    print(f"Wrote {n} corrections to {args.csv}")
    print("\nRecommendation: re-run with --csv to verify intake count dropped.")


if __name__ == "__main__":
    main()
