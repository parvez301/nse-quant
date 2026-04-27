#!/usr/bin/env python3
"""Re-run an existing model's backtest with point-in-time universe filter.

Why a separate script
---------------------
Retraining the LightGBM model on a PIT-filtered training set takes ~5 minutes
and is the more correct fix. But for a quick first look — "how much of the
+31% was survivorship?" — we can just filter the existing predictions and
re-run the backtest. That's what this script does.

What it does
------------
1. Load model_dir/pred.pkl
2. For each (datetime, instrument) row, drop it if the stock wasn't actually
   tradeable on that date (per PITMembership.was_tradeable)
3. Re-run qlib's backtest_daily with the filtered signal
4. Print before/after comparison

Usage
-----
  python examples/nse_pit_evaluate.py --model_dir outputs/nse_baseline_750_long
"""
import argparse
import json
import os
import pickle
from pathlib import Path

import numpy as np
import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).parent))
from nse_universe_pit import PITMembership


def filter_predictions_pit(pred: pd.DataFrame, pit: PITMembership) -> tuple[pd.DataFrame, dict]:
    """Drop (date, instrument) rows where instrument wasn't tradeable that date."""
    if isinstance(pred, pd.Series):
        pred = pred.to_frame("score")
    if "score" not in pred.columns:
        pred.columns = ["score"]

    pred = pred.copy()
    n_before = len(pred)

    # Vectorised filter: pre-compute per-instrument first/last bar lookup
    listing = pit.df  # indexed by instrument

    idx = pred.index.to_frame(index=False)
    idx.columns = ["datetime", "instrument"]
    idx["instrument"] = idx["instrument"].str.upper()

    listing_lookup = listing[["first_bar", "last_bar"]].reset_index()
    listing_lookup["instrument"] = listing_lookup["instrument"].str.upper()
    merged = idx.merge(listing_lookup, on="instrument", how="left")
    merged["warmup_floor"] = merged["datetime"] - pd.Timedelta(days=pit.warmup_days)
    eligible = (
        merged["first_bar"].notna()
        & (merged["first_bar"] <= merged["warmup_floor"])
        & (merged["last_bar"]  >= merged["datetime"])
    )
    keep_mask = eligible.values

    filtered = pred[keep_mask].copy()
    n_after = len(filtered)

    # Daily counts
    daily = pd.DataFrame({"datetime": idx["datetime"], "kept": keep_mask})
    daily_kept = daily.groupby("datetime")["kept"].agg(["sum", "count"])
    daily_kept.columns = ["kept", "total"]

    stats = {
        "rows_before": int(n_before),
        "rows_after": int(n_after),
        "rows_dropped_pct": float(1 - n_after / n_before) if n_before else 0.0,
        "min_universe_per_day": int(daily_kept["kept"].min()),
        "median_universe_per_day": float(daily_kept["kept"].median()),
        "max_universe_per_day": int(daily_kept["kept"].max()),
    }
    return filtered, stats


def run_backtest(
    pred_series: pd.Series,
    test_range: tuple[str, str],
    benchmark: str,
    topk: int,
    n_drop: int,
    capital: float,
    open_cost: float,
    close_cost: float,
    min_cost: float,
    limit_threshold: float,
    provider_uri: str,
):
    import qlib
    from qlib.contrib.evaluate import backtest_daily, risk_analysis

    qlib.init(provider_uri=os.path.expanduser(provider_uri), region="cn")

    strategy_config = {
        "class": "TopkDropoutStrategy",
        "module_path": "qlib.contrib.strategy",
        "kwargs": {
            "signal": pred_series,
            "topk": topk,
            "n_drop": n_drop,
        },
    }
    exchange_kwargs = {
        "freq": "day",
        "limit_threshold": limit_threshold,
        "deal_price": "close",
        "open_cost": open_cost,
        "close_cost": close_cost,
        "min_cost": min_cost,
        "trade_unit": None,
    }
    report, positions = backtest_daily(
        start_time=test_range[0],
        end_time=test_range[1],
        strategy=strategy_config,
        exchange_kwargs=exchange_kwargs,
        benchmark=benchmark,
        account=capital,
    )
    analysis = {
        "strategy_post_cost": risk_analysis(
            report["return"] - report["cost"], freq="day"
        ),
        "excess_post_cost": risk_analysis(
            report["return"] - report["bench"] - report["cost"], freq="day"
        ),
    }
    return report, analysis


def fmt_block(name: str, block: pd.DataFrame) -> str:
    s = block.iloc[:, 0]
    return (
        f"  {name:25s}  "
        f"ann_ret={s.get('annualized_return', float('nan')):+7.2%}  "
        f"sharpe={s.get('information_ratio', float('nan')):+6.3f}  "
        f"mdd={s.get('max_drawdown', float('nan')):+7.2%}"
    )


def main():
    p = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--model_dir", required=True,
                   help="output dir from nse_baseline.py with pred.pkl + headline.json")
    p.add_argument("--provider_uri", default="data/qlib_data/in_data")
    p.add_argument("--benchmark", default="NIFTY50")
    p.add_argument("--warmup_days", type=int, default=60,
                   help="require first_bar <= test_date - warmup_days (Alpha158 needs ~60d)")
    p.add_argument("--out_suffix", default="pit",
                   help="output file suffix (writes pit_headline.json next to original)")

    # Strategy + cost knobs (must match the model's training-time settings)
    p.add_argument("--topk", type=int, default=30)
    p.add_argument("--n_drop", type=int, default=5)
    p.add_argument("--capital", type=float, default=1_000_000)
    p.add_argument("--open_cost",  type=float, default=0.0015)
    p.add_argument("--close_cost", type=float, default=0.0025)
    p.add_argument("--min_cost",   type=float, default=5.0)
    p.add_argument("--limit_threshold", type=float, default=0.095)
    args = p.parse_args()

    model_dir = Path(args.model_dir)
    pred_path = model_dir / "pred.pkl"
    headline_path = model_dir / "headline.json"
    if not pred_path.exists():
        raise SystemExit(f"pred.pkl not found in {model_dir}")

    # Load original headline for reference
    original = json.loads(headline_path.read_text()) if headline_path.exists() else {}
    cfg = original.get("config", {})
    test_range = cfg.get("test", [None, None])
    if not test_range[0]:
        raise SystemExit("Original headline.json missing test range. Pass --test manually.")

    # Resolve topk/n_drop from saved config if available, else CLI defaults
    topk    = int(cfg.get("topk", args.topk))
    n_drop  = int(cfg.get("n_drop", args.n_drop))
    benchmark = cfg.get("benchmark", args.benchmark)

    pred = pd.read_pickle(pred_path)
    print(f"[load] pred shape = {pred.shape if hasattr(pred,'shape') else len(pred)}")
    print(f"       test range = {test_range[0]} -> {test_range[1]}")
    print(f"       benchmark  = {benchmark}, topk={topk}, drop={n_drop}")

    pit = PITMembership.load(warmup_days=args.warmup_days)
    filtered, stats = filter_predictions_pit(pred, pit)
    print(f"\n[pit] dropped {stats['rows_dropped_pct']:.1%} of rows "
          f"({stats['rows_before']:,} -> {stats['rows_after']:,})")
    print(f"      universe per day: median={stats['median_universe_per_day']:.0f}, "
          f"min={stats['min_universe_per_day']}, max={stats['max_universe_per_day']}")

    # Re-run backtest with filtered signal
    print(f"\n[backtest] re-running with PIT-filtered signal...")
    signal = filtered["score"]
    _, analysis = run_backtest(
        pred_series=signal,
        test_range=tuple(test_range),
        benchmark=benchmark,
        topk=topk, n_drop=n_drop,
        capital=args.capital,
        open_cost=args.open_cost, close_cost=args.close_cost,
        min_cost=args.min_cost,
        limit_threshold=args.limit_threshold,
        provider_uri=args.provider_uri,
    )

    print("\n=========== ORIGINAL (no PIT filter) ===========")
    if original:
        b_strat = original.get("strategy_post_cost", {})
        b_excess = original.get("excess_post_cost", {})
        for label, d in [("strategy_post_cost", b_strat), ("excess_post_cost", b_excess)]:
            try:
                print(f"  {label:25s}  "
                      f"ann_ret={float(d.get('annualized_return', 'nan')):+7.2%}  "
                      f"sharpe={float(d.get('information_ratio', 'nan')):+6.3f}  "
                      f"mdd={float(d.get('max_drawdown', 'nan')):+7.2%}")
            except (TypeError, ValueError):
                pass

    print("\n=========== PIT-FILTERED ===========")
    for name, block in analysis.items():
        print(fmt_block(name, block))

    # Compute the gap
    if original:
        try:
            orig_excess = float(original["excess_post_cost"].get("annualized_return", "nan"))
            new_excess = float(analysis["excess_post_cost"].iloc[:, 0].get("annualized_return", float("nan")))
            gap = orig_excess - new_excess
            print(f"\n[gap] excess return inflated by {gap:+.2%} due to survivorship + look-ahead")
        except (TypeError, ValueError, KeyError):
            pass

    # Save
    pit_headline = {
        "stats": stats,
        "strategy_post_cost": analysis["strategy_post_cost"].iloc[:, 0].to_dict(),
        "excess_post_cost":   analysis["excess_post_cost"].iloc[:, 0].to_dict(),
        "config": {
            "warmup_days": args.warmup_days,
            "test_range": test_range,
            "benchmark": benchmark,
            "topk": topk, "n_drop": n_drop,
        },
    }
    out_path = model_dir / f"{args.out_suffix}_headline.json"
    out_path.write_text(json.dumps(pit_headline, indent=2, default=str))
    print(f"\n[saved] {out_path}")


if __name__ == "__main__":
    main()
