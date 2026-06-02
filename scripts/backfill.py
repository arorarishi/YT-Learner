"""
Backfill missing column values in the transcripts table.

HOW TO ADD A NEW COLUMN BACKFILLER
-----------------------------------
1. Write a fetcher function with this signature:
       def fetch_<column>(video_id: str, row: dict) -> optional_value
   Return the value to write, or None to skip this row.

2. Register it in the BACKFILLERS dict at the bottom of this file:
       "column_name": fetch_<column>

That's it. The runner handles DB reads, NULL detection, updates, and retries.

USAGE
-----
Backfill all registered columns:
    python scripts/backfill.py

Backfill specific columns only:
    python scripts/backfill.py --columns description

Preview what would change without writing:
    python scripts/backfill.py --dry-run

Combine:
    python scripts/backfill.py --columns description --dry-run
"""

import argparse
import os
import sys
import time
from typing import Any, Callable, Dict, Optional

# ---------------------------------------------------------------------------
# Make sure the project root is on sys.path so app imports work
# ---------------------------------------------------------------------------
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.db.factory import get_db  # noqa: E402

# ---------------------------------------------------------------------------
# Fetcher functions — one per column
# ---------------------------------------------------------------------------

def fetch_description(video_id: str, row: dict) -> Optional[str]:
    """Fetch full video description via yt-dlp.

    Returns:
        str  — the description text (may be empty string if video has no description)
        None — error fetching; row will be skipped and retried next run
    """
    try:
        from yt_dlp import YoutubeDL
        opts = {"quiet": True, "no_warnings": True, "skip_download": True}
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(
                f"https://www.youtube.com/watch?v={video_id}", download=False
            )
        # Return "" (not None) when yt-dlp succeeds but video has no description,
        # so the row is marked as "fetched" and won't be retried on the next run.
        return info.get("description") or ""
    except Exception as e:
        print(f"    [WARN] Could not fetch description for {video_id}: {e}")
        return None


# ---------------------------------------------------------------------------
# Registry — add new columns here
# ---------------------------------------------------------------------------

BACKFILLERS: Dict[str, Callable[[str, dict], Any]] = {
    "description": fetch_description,
}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_backfill(columns: list[str], dry_run: bool, delay: float = 0.5):
    db = get_db()

    # Resolve which columns to process
    unknown = [c for c in columns if c not in BACKFILLERS]
    if unknown:
        print(f"[ERROR] No backfiller registered for: {', '.join(unknown)}")
        print(f"        Available: {', '.join(BACKFILLERS)}")
        sys.exit(1)

    targets = {col: BACKFILLERS[col] for col in columns}

    # Load all rows once
    all_rows = db.get_all_transcripts_raw()
    total = len(all_rows)
    print(f"Loaded {total} videos from DB")

    for col, fetcher in targets.items():
        missing = [r for r in all_rows if r.get(col) is None]
        print(f"\n--- Column: {col} | Missing: {len(missing)}/{total} ---")

        updated = 0
        skipped = 0

        for i, row in enumerate(missing, 1):
            video_id = row["video_id"]
            print(f"  [{i}/{len(missing)}] {video_id}", end=" ... ", flush=True)

            value = fetcher(video_id, row)
            if value is None:
                print("skipped (no value returned)")
                skipped += 1
                continue

            if dry_run:
                preview = str(value)[:80].replace("\n", " ")
                print(f"DRY-RUN → {preview!r}")
            else:
                db.update_column(video_id, col, value)
                print("saved")
                updated += 1

            if i < len(missing):
                time.sleep(delay)

        print(f"  Done: {updated} updated, {skipped} skipped" + (" (dry-run)" if dry_run else ""))


def main():
    parser = argparse.ArgumentParser(description="Backfill missing transcript columns.")
    parser.add_argument(
        "--columns",
        default=",".join(BACKFILLERS),
        help=f"Comma-separated columns to backfill. Default: all ({', '.join(BACKFILLERS)})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing to the database.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Seconds to wait between requests (default: 0.5).",
    )
    args = parser.parse_args()

    columns = [c.strip() for c in args.columns.split(",") if c.strip()]
    run_backfill(columns, dry_run=args.dry_run, delay=args.delay)


if __name__ == "__main__":
    main()
