#!/usr/bin/env python3
"""Rolling prediction-quality monitor for live paper/real trading.

Reads all past decisions under outputs/decisions/*.json and compares the scored
ranking on each decision date against the subsequent N-day realised returns from
the Qlib dataset. Emits rolling IC and signals if it degrades below a threshold.

Use weekly:
  python examples/nse_ic_monitor.py
  python examples/nse_ic_monitor.py --horizon 10 --window_days 30

What to watch:
  - Rolling 30-day IC mean    : should stay > 0.02 to justify the strategy
  - IC trend                  : consistent decline over 60+ days = model decayed; refit
  - IC > 0 days%              : should stay > 55%
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


def main():
    p = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--decisions_dir", default="outputs/decisions")
    p.add_argument("--qlib_provider", default="data/qlib_data/in_data")
    p.add_argument("--horizon", type=int, default=5,
                   help="days-ahead return to compare predictions against")
    p.add_argument("--window_days", type=int, default=30,
                   help="rolling window for IC summary")
    p.add_argument("--ic_floor", type=float, default=0.02,
                   help="if rolling IC drops below this, alert")
    args = p.parse_args()

    import qlib
    import os
    qlib.init(provider_uri=os.path.expanduser(args.qlib_provider), region="cn")
    from qlib.data import D

    decisions_dir = Path(args.decisions_dir)
    jsons = sorted(decisions_dir.glob("*.json"))
    if not jsons:
        print(f"[info] no decisions yet at {decisions_dir}")
        return

    rows = []
    for path in jsons:
        d = json.load(open(path))
        as_of = d["as_of"]
        candidates = d.get("top_10_candidates", [])
        # prefer the full ranked list from the daily decision if it was saved
        if not candidates:
            continue
        # We'll ask for forward returns for those symbols
        symbols = [c["instrument"] for c in candidates]
        scores = {c["instrument"]: c["score"] for c in candidates}

        end = (pd.Timestamp(as_of) + pd.Timedelta(days=args.horizon * 2)).strftime("%Y-%m-%d")
        prices = D.features(symbols, ["$close"], start_time=as_of, end_time=end)
        if prices.empty:
            continue
        # Forward return to H-th trading day
        fwd = []
        for sym in symbols:
            try:
                sub = prices.xs(sym, level="instrument")["$close"].dropna()
            except KeyError:
                continue
            if len(sub) <= args.horizon:
                continue
            ret = float(sub.iloc[args.horizon] / sub.iloc[0] - 1)
            fwd.append({"as_of": as_of, "symbol": sym, "score": scores[sym], "fwd_ret": ret})

        if fwd:
            df = pd.DataFrame(fwd)
            if df["score"].nunique() > 1:
                ic = df["score"].corr(df["fwd_ret"])
                rank_ic = df["score"].corr(df["fwd_ret"], method="spearman")
                rows.append({"as_of": as_of, "n_symbols": len(df), "ic": ic, "rank_ic": rank_ic})

    if not rows:
        print("[info] no fully-observable prediction windows yet. Come back after "
              f"{args.horizon}+ trading days.")
        return

    out = pd.DataFrame(rows).sort_values("as_of")
    out["as_of"] = pd.to_datetime(out["as_of"])
    out["ic_roll"] = out["ic"].rolling(args.window_days, min_periods=5).mean()
    out["rank_ic_roll"] = out["rank_ic"].rolling(args.window_days, min_periods=5).mean()

    print("=" * 60)
    print(f"  IC monitor  —  {len(out)} fully-observable decision days")
    print(f"  horizon {args.horizon}d, rolling window {args.window_days}d")
    print("=" * 60)
    print(out.tail(15).to_string(index=False))

    recent = out.tail(args.window_days)
    if len(recent) < 5:
        print(f"\n[info] only {len(recent)} recent obs, not enough to judge")
        return

    recent_ic = recent["ic"].mean()
    recent_rank_ic = recent["rank_ic"].mean()
    print(f"\n  Last {len(recent)} days:")
    print(f"    IC mean       {recent_ic:+.4f}")
    print(f"    Rank IC mean  {recent_rank_ic:+.4f}")
    print(f"    IC > 0 days   {(recent['ic'] > 0).mean():.1%}")

    alerts = []
    if recent_ic < args.ic_floor:
        alerts.append(f"Recent IC {recent_ic:.4f} < floor {args.ic_floor}")
    if len(out) > 60 and out["ic"].tail(30).mean() < out["ic"].tail(60).head(30).mean() - 0.01:
        alerts.append("Rolling IC declining materially over last 60 days")

    if alerts:
        print("\n  ⚠  ALERTS")
        for a in alerts:
            print("   -", a)
        print("\n  Consider running nse_walkforward.py to refit on recent data.")
    else:
        print("\n  ✓  signal quality stable")

    out.to_csv("outputs/ic_monitor.csv", index=False)
    print("\n[saved] outputs/ic_monitor.csv")


if __name__ == "__main__":
    main()
