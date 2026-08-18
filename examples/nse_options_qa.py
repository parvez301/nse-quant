#!/usr/bin/env python3
"""Run the Phase 0 QA gate over the local F&O archive. Exit 0 = gate passed."""
from __future__ import annotations

import argparse
import datetime
import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from options.qa import coverage_report, sample_cell_checks  # noqa: E402

_SAMPLE_SYMBOLS = ["RELIANCE", "HDFCBANK", "TCS", "SBIN", "ITC"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", default="data/fo_bhavcopy", type=pathlib.Path)
    parser.add_argument("--calendar", default="data/qlib_data/in_data/calendars/day.txt", type=pathlib.Path)
    parser.add_argument("--year-floor", default=0.95, type=float)
    arguments = parser.parse_args()

    calendar_dates = [datetime.date.fromisoformat(line.strip())
                      for line in arguments.calendar.read_text().splitlines()
                      if line.strip() >= "2019-01-01"]
    report = coverage_report(arguments.archive_root, calendar_dates)
    gate_failed = False
    for year, year_bucket in sorted(report.items()):
        flag = "" if year_bucket["coverage"] >= arguments.year_floor else "  <-- BELOW FLOOR"
        gate_failed |= bool(flag)
        print(f"{year}: {year_bucket['present']}/{year_bucket['expected']}"
              f" ({year_bucket['coverage']:.1%}){flag}")

    random.seed(20260818)  # reproducible sample
    present_dates = [d for d in calendar_dates
                     if (arguments.archive_root / f"{d:%Y}" / f"{d:%Y%m%d}.csv.gz").exists()]
    failed_cells = 0
    for sampled_date in random.sample(present_dates, min(10, len(present_dates))):
        symbol = random.choice(_SAMPLE_SYMBOLS)
        try:
            checks = sample_cell_checks(arguments.archive_root, sampled_date, symbol)
        except (StopIteration, ValueError) as exc:
            checks = {"error": str(exc)}
        cell_ok = checks.get("strikes_contiguous") and checks.get("atm_oi_positive") and checks.get("atm_iv_sane")
        failed_cells += 0 if cell_ok else 1
        print(f"{sampled_date} {symbol}: {'OK' if cell_ok else 'FAIL'} {checks}")

    gate_failed |= failed_cells > 3
    print(f"\nQA GATE: {'FAILED' if gate_failed else 'PASSED'} (cells failed: {failed_cells}/10)")
    return 1 if gate_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
