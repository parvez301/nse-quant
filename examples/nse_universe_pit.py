#!/usr/bin/env python3
"""Point-in-time universe filter — the free survivorship-bias correction.

Why
---
Current backtest uses today's NIFTY Total Market 750 list across all of
2008-2026. That's wrong: ~150 of those 750 stocks weren't listed yet in 2008.
The model implicitly "knows" they will exist and out-perform.

This module derives each stock's first-trade date from our local yfinance
CSVs and builds a membership oracle:

    membership.was_tradeable(stock, date) -> bool

Used by `nse_baseline.py --pit_universe` to filter the training instruments
to those that were actually listed on each training day.

What this fixes
---------------
- Look-ahead bias: model can no longer learn from stocks that didn't exist
- Recent-IPO inflation: NIFTY 500 additions skew young/tech/recent winners
- Effective-N inflation: 2008-era models see ~600 stocks instead of fake 750

What this does NOT fix
----------------------
- Delisted tickers that yfinance dropped entirely (DHFL, Yes Bank reorg, etc.)
- Index membership boundaries (a stock listed in 2010 may not have been in
  NIFTY 500 until 2018; we treat it as eligible from 2010 onwards)

Estimated correction: ~40-60% of total survivorship inflation.

Usage
-----
  # 1. Build the membership cache (fast — just scans CSV first dates)
  python examples/nse_universe_pit.py build

  # 2. Inspect coverage
  python examples/nse_universe_pit.py inspect --year 2010
  python examples/nse_universe_pit.py inspect --year 2020

  # 3. Use in your baseline
  python examples/nse_baseline.py --pit_universe \
      --train 2010-01-01 2018-12-31 \
      --test  2024-01-01 2025-12-31
"""
import argparse
import glob
import json
import os
from pathlib import Path

import pandas as pd


CACHE_PATH = Path("outputs/pit_universe.parquet")
DEFAULT_CSV_DIR = os.path.expanduser("data/qlib_data/in_data/_csv")


def build_listing_dates(csv_dir: str = DEFAULT_CSV_DIR) -> pd.DataFrame:
    """Scan all CSVs and record first/last bar date per instrument."""
    rows = []
    for path in sorted(glob.glob(os.path.join(csv_dir, "*.csv"))):
        try:
            df = pd.read_csv(path, parse_dates=["date"], usecols=["date"])
        except (ValueError, KeyError):
            continue
        if df.empty:
            continue
        instrument = os.path.basename(path).replace(".csv", "").upper()
        rows.append({
            "instrument": instrument,
            "first_bar": df["date"].min(),
            "last_bar": df["date"].max(),
            "n_bars": len(df),
        })
    return pd.DataFrame(rows)


def save_cache(df: pd.DataFrame, path: Path = CACHE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


def load_cache(path: Path = CACHE_PATH) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Cache not found at {path}. Run: python examples/nse_universe_pit.py build")
    return pd.read_parquet(path)


class PITMembership:
    """Point-in-time tradeable-universe oracle.

    A stock is "tradeable" on date D iff first_bar <= D - warmup_days <= last_bar.
    The warmup_days buffer ensures Alpha158 features have enough history.
    """

    def __init__(self, df: pd.DataFrame, warmup_days: int = 60):
        self.df = df.set_index("instrument")
        self.warmup_days = warmup_days

    @classmethod
    def load(cls, warmup_days: int = 60) -> "PITMembership":
        return cls(load_cache(), warmup_days=warmup_days)

    def was_tradeable(self, instrument: str, date) -> bool:
        instrument = instrument.upper()
        if instrument not in self.df.index:
            return False
        row = self.df.loc[instrument]
        d = pd.Timestamp(date)
        warmup_floor = d - pd.Timedelta(days=self.warmup_days)
        return row["first_bar"] <= warmup_floor <= row["last_bar"]

    def filter_universe(self, instruments: list[str], asof_date) -> list[str]:
        """Return only those instruments tradeable as of `asof_date`."""
        d = pd.Timestamp(asof_date)
        warmup_floor = d - pd.Timedelta(days=self.warmup_days)
        df = self.df.reindex([i.upper() for i in instruments]).dropna()
        eligible = df[(df["first_bar"] <= warmup_floor) & (df["last_bar"] >= d)]
        return eligible.index.tolist()

    def universe_size_history(self, dates: pd.DatetimeIndex) -> pd.Series:
        """For each date, how many stocks were tradeable?"""
        counts = []
        for d in dates:
            warmup_floor = d - pd.Timedelta(days=self.warmup_days)
            n = int(((self.df["first_bar"] <= warmup_floor) &
                     (self.df["last_bar"] >= d)).sum())
            counts.append(n)
        return pd.Series(counts, index=dates, name="universe_size")


def cmd_build(args):
    print(f"[scan] {args.csv_dir}")
    df = build_listing_dates(args.csv_dir)
    print(f"[done] {len(df)} instruments")
    save_cache(df, Path(args.out))
    print(f"[saved] {args.out}")
    print()
    print("First-bar histogram by year:")
    yr = df["first_bar"].dt.year
    for y, n in yr.value_counts().sort_index().items():
        bar = "█" * min(int(n / 5), 60)
        print(f"  {y}: {n:4d}  {bar}")


def cmd_inspect(args):
    pit = PITMembership.load(warmup_days=args.warmup_days)
    target = pd.Timestamp(f"{args.year}-{args.month:02d}-15")
    eligible = pit.filter_universe(pit.df.index.tolist(), target)
    print(f"As-of {target.date()}: {len(eligible)} of {len(pit.df)} instruments tradeable")
    print(f"  warmup_days = {args.warmup_days} (need first_bar <= {(target - pd.Timedelta(days=args.warmup_days)).date()})")
    if args.show_excluded:
        excluded = sorted(set(pit.df.index) - set(eligible))
        print(f"\nExcluded ({len(excluded)}):")
        for i in excluded[:30]:
            row = pit.df.loc[i]
            print(f"  {i:20s}  first={row['first_bar'].date()}  last={row['last_bar'].date()}")
        if len(excluded) > 30:
            print(f"  ... and {len(excluded) - 30} more")


def cmd_history(args):
    pit = PITMembership.load(warmup_days=args.warmup_days)
    dates = pd.date_range(args.start, args.end, freq=args.freq)
    hist = pit.universe_size_history(dates)
    print("\nTradeable-universe size over time:")
    for d, n in hist.items():
        bar = "█" * int(n / 15)
        print(f"  {d.date()}  {n:4d}  {bar}")
    out = Path("outputs/pit_universe_history.csv")
    hist.to_csv(out)
    print(f"\n[saved] {out}")


def main():
    p = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("build", help="Build the listing-date cache from CSVs")
    sp.add_argument("--csv_dir", default=DEFAULT_CSV_DIR)
    sp.add_argument("--out", default=str(CACHE_PATH))
    sp.set_defaults(fn=cmd_build)

    sp = sub.add_parser("inspect", help="Show universe size at a given date")
    sp.add_argument("--year", type=int, required=True)
    sp.add_argument("--month", type=int, default=6)
    sp.add_argument("--warmup_days", type=int, default=60)
    sp.add_argument("--show_excluded", action="store_true")
    sp.set_defaults(fn=cmd_inspect)

    sp = sub.add_parser("history", help="Print universe size over time")
    sp.add_argument("--start", default="2008-01-01")
    sp.add_argument("--end",   default="2026-01-01")
    sp.add_argument("--freq",  default="YS")
    sp.add_argument("--warmup_days", type=int, default=60)
    sp.set_defaults(fn=cmd_history)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
