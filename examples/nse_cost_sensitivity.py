#!/usr/bin/env python3
"""Cost sensitivity matrix — what does the strategy look like at different
real-world cost assumptions?

Builds a 2D table: capital level × base_bps. Returns annual return, Sharpe,
and excess-vs-NIFTY at each cell. Used by the methodology page so a reader
can place themselves on the curve based on their own broker/AUM.

Wraps `simulate()` from nse_slippage_model.py rather than re-implementing.

Usage:
  python examples/nse_cost_sensitivity.py --model_dir outputs/nse_baseline_750_long
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nse_slippage_model import (
    SlippageParams, get_benchmark_returns, load_universe_data, simulate,
)


def run_matrix(
    *,
    model_dir: Path,
    provider_uri: str,
    benchmark: str,
    capitals: list[float],
    base_bps_list: list[float],
    impact_coef: float,
    topk: int,
    n_drop: int,
    rebalance: int,
) -> dict:
    pred_path = model_dir / "pred.pkl"
    if not pred_path.exists():
        raise SystemExit(f"pred.pkl not found in {model_dir}")
    pred = pd.read_pickle(pred_path)
    if isinstance(pred, pd.Series):
        pred = pred.to_frame("score")

    dates = pred.index.get_level_values("datetime")
    start = (dates.min() - pd.Timedelta(days=40)).strftime("%Y-%m-%d")
    end = dates.max().strftime("%Y-%m-%d")
    instruments = sorted(pred.index.get_level_values("instrument").unique())

    print(f"[load] {len(instruments)} instruments, {start}..{end}")
    px = load_universe_data(provider_uri, instruments, start, end)
    bench = get_benchmark_returns(provider_uri, benchmark, start, end)

    cells: list[dict] = []
    for cap in capitals:
        for bps in base_bps_list:
            print(f"\n[cell] capital=₹{cap:,.0f} base_bps={bps}")
            slip = SlippageParams(base_bps=bps, impact_coef=impact_coef)
            r = simulate(pred=pred, px=px, capital=cap,
                         topk=topk, n_drop=n_drop, rebalance=rebalance,
                         slip=slip, benchmark_ret=bench)
            cell = {
                "capital_inr": cap,
                "base_bps": bps,
                "ann_return": round(r["ann_return"], 4),
                "sharpe": round(r["sharpe"], 3),
                "excess_ann_return": round(r.get("excess_ann_return", 0.0), 4),
                "max_drawdown": round(r["max_drawdown"], 4),
                "avg_slippage_bps": round(r["avg_slippage_bps"], 2),
                "p95_slippage_bps": round(r["p95_slippage_bps"], 2),
                "total_cost_pct": round(r["total_cost_pct"], 4),
            }
            cells.append(cell)
            print(f"   ann_return={cell['ann_return']:+.2%}  "
                  f"excess={cell['excess_ann_return']:+.2%}  "
                  f"slippage avg/p95={cell['avg_slippage_bps']}/{cell['p95_slippage_bps']} bps")

    return {
        "model_dir": str(model_dir),
        "benchmark": benchmark,
        "topk": topk,
        "n_drop": n_drop,
        "rebalance": rebalance,
        "impact_coef": impact_coef,
        "capitals_inr": capitals,
        "base_bps_list": base_bps_list,
        "cells": cells,
        "interpretation": (
            "Each cell shows the strategy's annualised return + excess-vs-NIFTY "
            "at one (AUM, base-bps) combination. Read across a row to see how "
            "your broker fee level changes outcomes; read down a column to see "
            "how trade-size impact eats into returns as you scale up."
        ),
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model_dir", default="outputs/nse_baseline_750_long")
    p.add_argument("--provider_uri", default="data/qlib_data/in_data")
    p.add_argument("--benchmark", default="NIFTY50")
    p.add_argument("--out", default="outputs/cost_sensitivity.json")
    p.add_argument("--topk", type=int, default=30)
    p.add_argument("--n_drop", type=int, default=5)
    p.add_argument("--rebalance", type=int, default=5)
    p.add_argument("--impact_coef", type=float, default=50.0)
    p.add_argument("--capitals", type=float, nargs="+",
                   default=[1_000_000, 10_000_000, 50_000_000])
    p.add_argument("--base_bps", type=float, nargs="+",
                   default=[2.0, 5.0, 10.0, 20.0])
    args = p.parse_args()

    result = run_matrix(
        model_dir=Path(args.model_dir),
        provider_uri=args.provider_uri,
        benchmark=args.benchmark,
        capitals=args.capitals,
        base_bps_list=args.base_bps,
        impact_coef=args.impact_coef,
        topk=args.topk,
        n_drop=args.n_drop,
        rebalance=args.rebalance,
    )
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=2))
    print(f"\n[cost-sensitivity] wrote {args.out} ({len(result['cells'])} cells)")


if __name__ == "__main__":
    main()
