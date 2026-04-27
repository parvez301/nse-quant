#!/usr/bin/env python3
"""Walk-forward retraining helper.

Refits the baseline model on an extended training window (train + validation + all
but the last N months of test) and writes it alongside the prior model with a
timestamped folder.

Use monthly or quarterly: markets change, models decay. A rough cadence:

  Month 0 — train once on 2015-2022 (initial production model)
  Monthly — call this script to extend training through the most recent 30 days;
            old test segment becomes part of new train segment.

  python examples/nse_walkforward.py --refit_through 2026-03-31
  # -> new model at outputs/nse_baseline_500_2026_03_31/

Then point the daily runner at it:
  ./examples/run_daily.sh  # update MODEL_DIR in the shell script
"""
import argparse
import os
import pickle
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd


def main():
    p = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--refit_through", default=None,
                   help="train through this date (inclusive). Default: yesterday.")
    p.add_argument("--valid_months", type=int, default=6,
                   help="holdout validation months preceding refit_through")
    p.add_argument("--test_months", type=int, default=3,
                   help="out-of-sample evaluation months after refit_through")
    p.add_argument("--base_out_dir", default="outputs")
    p.add_argument("--name_prefix", default="nse_baseline_500")
    p.add_argument("--topk", type=int, default=30)
    p.add_argument("--n_drop", type=int, default=5)
    p.add_argument("--rebalance", type=int, default=5)
    args = p.parse_args()

    refit = pd.Timestamp(args.refit_through) if args.refit_through else (pd.Timestamp.today() - pd.Timedelta(days=1))
    valid_end = refit
    valid_start = (valid_end - pd.DateOffset(months=args.valid_months)).strftime("%Y-%m-%d")
    valid_end_s = valid_end.strftime("%Y-%m-%d")
    train_start = "2015-01-01"
    train_end = (valid_end - pd.DateOffset(months=args.valid_months) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    test_start = (valid_end + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    test_end = min(
        (valid_end + pd.DateOffset(months=args.test_months)),
        pd.Timestamp.today(),
    ).strftime("%Y-%m-%d")

    stamp = refit.strftime("%Y_%m_%d")
    out_dir = Path(args.base_out_dir) / f"{args.name_prefix}_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, "examples/nse_baseline.py",
        "--train", train_start, train_end,
        "--valid", valid_start, valid_end_s,
        "--test",  test_start,  test_end,
        "--rebalance", str(args.rebalance),
        "--topk", str(args.topk),
        "--n_drop", str(args.n_drop),
        "--out_dir", str(out_dir),
    ]
    print(f"[walkforward] refitting through {refit.date()}")
    print(f"  train {train_start} -> {train_end}")
    print(f"  valid {valid_start} -> {valid_end_s}")
    print(f"  test  {test_start}  -> {test_end}")
    print(f"  out   {out_dir}")
    print(f"[run] {' '.join(cmd)}")

    subprocess.run(cmd, check=True)

    # Write a pointer to the newest model for the daily runner to pick up
    pointer = Path(args.base_out_dir) / f"{args.name_prefix}_latest.txt"
    with open(pointer, "w") as f:
        f.write(str(out_dir) + "\n")
    print(f"\n[done] pointer updated: {pointer} -> {out_dir}")
    print("To switch the daily runner to this model, edit examples/run_daily.sh:")
    print(f"  MODEL_DIR={out_dir}")


if __name__ == "__main__":
    main()
