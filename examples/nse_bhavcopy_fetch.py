#!/usr/bin/env python3
"""Download NSE daily Bhavcopy CSVs for a date range into a local cache.

Wraps `jugaad-data`'s `bhavcopy_save` — that lib handles the NSE-side
fetching (browser-mimicking headers, the ddmmm-format URL, both archive
eras). All this script does is iterate dates, skip weekends, organise
the downloaded CSVs into year-subdirectories under data/bhavcopy/, and
keep going past 404s (NSE holidays return 404 — that's expected).

Cache layout (consumed by NSEBhavcopyAdapter):

    data/bhavcopy/
        2024/
            cm02JAN2024bhav.csv
            cm03JAN2024bhav.csv
            ...

Usage:

    # Fetch all of 2024 (~250 trading days, ~5-10 min over a normal connection)
    python examples/nse_bhavcopy_fetch.py --start 2024-01-01 --end 2024-12-31

    # Smoke fetch — every Friday of 2024 (52 files, ~2 min)
    python examples/nse_bhavcopy_fetch.py --start 2024-01-01 --end 2024-12-31 --weekly

    # Custom cache root
    python examples/nse_bhavcopy_fetch.py --start 2024-01-01 --end 2024-12-31 \\
        --cache-dir /path/to/bhavcopy

Exits 0 even on per-day 404s — NSE holidays are normal and skipping them
is the correct behaviour.
"""
from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path


def _trading_days(start: datetime.date, end: datetime.date, weekly: bool):
    """Yield candidate trading days. Skip weekends. NSE holidays are
    handled downstream via the 404 the bhavcopy_save call raises."""
    d = start
    while d <= end:
        is_weekend = d.weekday() >= 5  # Sat=5, Sun=6
        is_friday = d.weekday() == 4
        if not is_weekend and (not weekly or is_friday):
            yield d
        d += datetime.timedelta(days=1)


def fetch_range(
    start: datetime.date,
    end: datetime.date,
    cache_dir: Path,
    *,
    weekly: bool = False,
    verbose: bool = True,
) -> dict:
    """Download every Bhavcopy CSV in [start, end] into cache_dir/YYYY/.

    Returns {fetched, skipped_existing, skipped_holiday, errors}.
    Pure-ish — easy to wrap in a test by passing a tmp_path."""
    from jugaad_data.nse import bhavcopy_save  # noqa: PLC0415

    fetched = 0
    skipped_existing = 0
    skipped_holiday = 0
    errors: list[tuple[str, str]] = []

    for day in _trading_days(start, end, weekly):
        year_dir = cache_dir / str(day.year)
        year_dir.mkdir(parents=True, exist_ok=True)
        try:
            path = bhavcopy_save(day, str(year_dir))
            # bhavcopy_save uses skip_if_present=True; fall back to checking
            # mtime only matters if we cared about freshness — for this
            # cache we don't, presence is enough.
            if Path(path).exists():
                fetched += 1
                if verbose:
                    print(f"[fetch] {day} -> {Path(path).name}")
        except Exception as exc:  # noqa: BLE001 — NSE 404s on holidays are normal
            msg = str(exc)
            if "404" in msg or "not found" in msg.lower():
                skipped_holiday += 1
                if verbose:
                    print(f"[skip] {day}: holiday or no archive ({msg[:80]})")
            else:
                errors.append((str(day), msg[:200]))
                if verbose:
                    print(f"[error] {day}: {msg[:200]}", file=sys.stderr)

    return {
        "fetched": fetched,
        "skipped_existing": skipped_existing,
        "skipped_holiday": skipped_holiday,
        "errors": errors,
    }


def _parse_date(s: str) -> datetime.date:
    return datetime.datetime.strptime(s, "%Y-%m-%d").date()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--start", required=True, type=_parse_date,
                   help="YYYY-MM-DD, inclusive")
    p.add_argument("--end", required=True, type=_parse_date,
                   help="YYYY-MM-DD, inclusive")
    p.add_argument("--cache-dir", default="data/bhavcopy",
                   help="Local cache root (default: data/bhavcopy)")
    p.add_argument("--weekly", action="store_true",
                   help="Fridays only (smoke mode — ~52 files/yr instead of ~250)")
    args = p.parse_args()

    if args.start > args.end:
        sys.exit(f"[abort] start {args.start} after end {args.end}")

    summary = fetch_range(args.start, args.end, Path(args.cache_dir), weekly=args.weekly)
    print()
    print(f"[bhavcopy-fetch] done in window {args.start}..{args.end}")
    print(f"[bhavcopy-fetch]   fetched  : {summary['fetched']}")
    print(f"[bhavcopy-fetch]   holidays : {summary['skipped_holiday']}")
    print(f"[bhavcopy-fetch]   errors   : {len(summary['errors'])}")
    if summary["errors"]:
        for date_str, msg in summary["errors"][:5]:
            print(f"[bhavcopy-fetch]     - {date_str}: {msg}", file=sys.stderr)
        if len(summary["errors"]) > 5:
            print(f"[bhavcopy-fetch]     ... +{len(summary['errors']) - 5} more", file=sys.stderr)


if __name__ == "__main__":
    main()
