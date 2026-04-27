#!/usr/bin/env python3
"""Walk-forward backtest: N rolling train/test windows, aggregated stats.

Why this exists
---------------
A single train/test split (e.g. train 2008-2022, test 2024-2026) gives you ONE
realization of the strategy. The Sharpe you read off that one number is half
luck (you happened to land on a benign test regime) and half skill. Cannot tell
which is which from a single window.

This script runs N rolling annual test windows and aggregates the results so
you can see the *distribution* of performance across regimes. Then "+31% excess"
becomes "median +12%, p25 -3%, p75 +28%, hit-rate 65%" — much more honest.

Usage
-----
  python examples/nse_walkforward_backtest.py \
      --first_test_year 2018 --last_test_year 2025 \
      --train_start 2008-01-01 --benchmark NIFTY50

Outputs
-------
  outputs/walkforward_backtest/
      window_2018/headline.json   (one per year)
      window_2019/headline.json
      ...
      summary.csv                  (one row per window)
      summary.txt                  (aggregated stats — read this)
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def run_one_window(
    train_start: str,
    train_end: str,
    valid_start: str,
    valid_end: str,
    test_start: str,
    test_end: str,
    out_dir: Path,
    benchmark: str,
    topk: int,
    n_drop: int,
    rebalance: int,
    provider_uri: str,
) -> dict | None:
    """Train + test one window via nse_baseline.py. Returns headline dict or None on fail."""
    out_dir.mkdir(parents=True, exist_ok=True)
    headline_path = out_dir / "headline.json"

    if headline_path.exists():
        print(f"  [skip] {out_dir.name} already done")
        return json.loads(headline_path.read_text())

    cmd = [
        sys.executable, "examples/nse_baseline.py",
        "--provider_uri", provider_uri,
        "--benchmark", benchmark,
        "--train", train_start, train_end,
        "--valid", valid_start, valid_end,
        "--test",  test_start,  test_end,
        "--rebalance", str(rebalance),
        "--topk", str(topk),
        "--n_drop", str(n_drop),
        "--out_dir", str(out_dir),
    ]
    print(f"  [run] train {train_start[:7]}..{train_end[:7]}  "
          f"valid {valid_start[:7]}..{valid_end[:7]}  "
          f"test {test_start[:7]}..{test_end[:7]}")

    log_path = out_dir / "run.log"
    with open(log_path, "w") as logf:
        result = subprocess.run(cmd, stdout=logf, stderr=subprocess.STDOUT)

    if result.returncode != 0 or not headline_path.exists():
        print(f"  [FAIL] window {out_dir.name} — see {log_path}")
        return None
    return json.loads(headline_path.read_text())


def extract_metrics(headline: dict) -> dict:
    """Pull the numbers we want to aggregate into a flat row."""
    sig = headline.get("signal", {})
    strat = headline.get("strategy_post_cost", {})
    excess = headline.get("excess_post_cost", {})

    def _f(d, k):
        try:
            return float(d.get(k, float("nan")))
        except (TypeError, ValueError):
            return float("nan")

    return {
        "rank_ic_mean": sig.get("rank_ic_mean", float("nan")),
        "rank_ic_ir":   sig.get("rank_ic_ir",   float("nan")),
        "ic_mean":      sig.get("ic_mean",      float("nan")),
        "strat_ann_ret":   _f(strat, "annualized_return"),
        "strat_sharpe":    _f(strat, "information_ratio"),
        "strat_max_dd":    _f(strat, "max_drawdown"),
        "excess_ann_ret":  _f(excess, "annualized_return"),
        "excess_sharpe":   _f(excess, "information_ratio"),
        "excess_max_dd":   _f(excess, "max_drawdown"),
    }


def summarize(rows: list[dict]) -> str:
    """Build a human-readable summary string."""
    if not rows:
        return "No completed windows."
    df = pd.DataFrame(rows).set_index("window")

    keys = [
        ("excess_ann_ret",  "Excess return"),
        ("excess_sharpe",   "Excess Sharpe"),
        ("strat_ann_ret",   "Strategy return"),
        ("strat_sharpe",    "Strategy Sharpe"),
        ("strat_max_dd",    "Strategy max DD"),
        ("rank_ic_mean",    "Rank IC"),
    ]

    lines = []
    lines.append(f"Walk-forward backtest — {len(df)} windows")
    lines.append("=" * 72)
    lines.append("")
    lines.append("Per-window:")
    show_cols = ["excess_ann_ret", "excess_sharpe", "strat_max_dd", "rank_ic_mean"]
    lines.append(df[show_cols].to_string(float_format=lambda x: f"{x:+.3f}"))
    lines.append("")
    lines.append("Aggregated stats (across windows):")
    lines.append("-" * 72)
    lines.append(f"{'metric':<22} {'mean':>10} {'median':>10} {'std':>10} {'p25':>10} {'p75':>10} {'hit%':>7}")
    for col, label in keys:
        s = df[col].dropna()
        if len(s) == 0:
            continue
        hit = (s > 0).mean() * 100 if "max_dd" not in col else (s > -0.20).mean() * 100
        lines.append(
            f"{label:<22} "
            f"{s.mean():>+10.4f} {s.median():>+10.4f} {s.std():>10.4f} "
            f"{s.quantile(0.25):>+10.4f} {s.quantile(0.75):>+10.4f} {hit:>6.0f}%"
        )

    lines.append("")
    lines.append("Read this:")
    es = df["excess_sharpe"].dropna()
    er = df["excess_ann_ret"].dropna()
    if len(es) >= 3:
        # Sharpe of the Sharpe series — t-stat for "excess Sharpe > 0"
        t = es.mean() / (es.std() / np.sqrt(len(es))) if es.std() > 0 else float("nan")
        lines.append(f"  Excess-Sharpe t-stat across windows: {t:+.2f}  "
                     f"(>2.0 = statistically meaningful)")
        lines.append(f"  Years with positive excess: {(er > 0).sum()}/{len(er)}")
        lines.append(f"  Worst year:  {er.min():+.2%}    Best year: {er.max():+.2%}")
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(
        description="Walk-forward backtest with rolling annual test windows.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--provider_uri", default="data/qlib_data/in_data")
    p.add_argument("--benchmark", default="NIFTY50")
    p.add_argument("--train_start", default="2008-01-01",
                   help="anchor of the (expanding) training window")
    p.add_argument("--first_test_year", type=int, default=2018)
    p.add_argument("--last_test_year",  type=int, default=2025)
    p.add_argument("--valid_months", type=int, default=12,
                   help="length of the validation window (right before test)")
    p.add_argument("--rebalance", type=int, default=5)
    p.add_argument("--topk",      type=int, default=30)
    p.add_argument("--n_drop",    type=int, default=5)
    p.add_argument("--mode", choices=["expanding", "rolling"], default="expanding",
                   help="expanding = train_start fixed; rolling = fixed train length")
    p.add_argument("--rolling_train_years", type=int, default=7,
                   help="if mode=rolling, length of train window in years")
    p.add_argument("--out_dir", default="outputs/walkforward_backtest")
    args = p.parse_args()

    base = Path(args.out_dir)
    base.mkdir(parents=True, exist_ok=True)

    rows = []
    for year in range(args.first_test_year, args.last_test_year + 1):
        # test = full calendar year
        test_start = f"{year}-01-01"
        test_end   = f"{year}-12-31"

        # valid = N months immediately before test
        valid_end_ts   = pd.Timestamp(test_start) - pd.Timedelta(days=1)
        valid_start_ts = valid_end_ts - pd.DateOffset(months=args.valid_months) + pd.Timedelta(days=1)
        valid_start = valid_start_ts.strftime("%Y-%m-%d")
        valid_end   = valid_end_ts.strftime("%Y-%m-%d")

        # train = anchor (or rolling) up to valid_start - 1 day
        train_end_ts = valid_start_ts - pd.Timedelta(days=1)
        if args.mode == "expanding":
            train_start = args.train_start
        else:
            train_start = (train_end_ts - pd.DateOffset(years=args.rolling_train_years) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        train_end = train_end_ts.strftime("%Y-%m-%d")

        if pd.Timestamp(train_end) <= pd.Timestamp(train_start):
            print(f"[skip] {year} — train window degenerate ({train_start} -> {train_end})")
            continue

        out_dir = base / f"window_{year}"
        print(f"\n=== window {year} ===")
        headline = run_one_window(
            train_start, train_end, valid_start, valid_end,
            test_start, test_end, out_dir,
            args.benchmark, args.topk, args.n_drop, args.rebalance,
            args.provider_uri,
        )
        if headline is None:
            continue
        row = {"window": year, **extract_metrics(headline)}
        rows.append(row)

    if not rows:
        print("\nNo windows completed. Check window logs in", base)
        sys.exit(1)

    summary_df = pd.DataFrame(rows)
    summary_df.to_csv(base / "summary.csv", index=False)

    text = summarize(rows)
    (base / "summary.txt").write_text(text + "\n")
    print("\n" + text)
    print(f"\n[saved] per-window dirs + summary.csv + summary.txt under {base}/")


if __name__ == "__main__":
    main()
