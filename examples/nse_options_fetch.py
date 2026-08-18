#!/usr/bin/env python3
"""Backfill / update the local NSE F&O bhavcopy archive.

Usage:
  python examples/nse_options_fetch.py --start 2019-01-01 --end 2026-08-18
Polite pacing: NSE archives throttle aggressive clients; default 0.6s sleep
between network fetches (cached days cost nothing and skip the sleep).
"""
from __future__ import annotations

import argparse
import datetime
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from options.fo_archive import fetch_day  # noqa: E402


def run_fetch(start_date: datetime.date, end_date: datetime.date,
              archive_root: pathlib.Path, sleep_seconds: float,
              fetch_day_fn=fetch_day) -> dict:
    summary = {"written": 0, "cached": 0, "no_file": 0, "error": 0}
    current_date = start_date
    while current_date <= end_date:
        if current_date.weekday() < 5:
            status = fetch_day_fn(current_date, archive_root)
            summary[status] += 1
            if status != "cached":
                print(f"{current_date} {status}", flush=True)
                if sleep_seconds:
                    time.sleep(sleep_seconds)
        current_date += datetime.timedelta(days=1)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, type=datetime.date.fromisoformat)
    parser.add_argument("--end", required=True, type=datetime.date.fromisoformat)
    parser.add_argument("--archive-root", default="data/fo_bhavcopy", type=pathlib.Path)
    parser.add_argument("--sleep", default=0.6, type=float)
    arguments = parser.parse_args()
    summary = run_fetch(arguments.start, arguments.end, arguments.archive_root, arguments.sleep)
    print(" ".join(f"{key}={value}" for key, value in summary.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
