#!/usr/bin/env python3
"""Outage Monte Carlo — what happens if you miss trading days?

Reads the per-window walk-forward summary (outputs/summary.csv) and simulates
degradation when the strategy misses a fraction of rebalance days (laptop
asleep, internet down, kid had fever, etc.). On a missed day the strategy
holds whatever it had into the next session — no rebalance, no harvest.

Model:
  daily_alpha = window_ann_excess / 252
  for each trial:
    k = Binomial(252, outage_rate)             # days missed
    degraded_ann_excess = (1 + daily_alpha)^(252 - k) - 1
                         + bench_daily * k     # missed days = bench-only return
    -> approximated as: window_ann * (1 - outage_rate) for the alpha portion,
       i.e. linear decay in alpha. We're not trying to be exact, just to
       give the reader a feel for "how robust is this if I lose 5% of days?"

Output: outputs/outage_monte_carlo.json
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path
from statistics import mean


def simulate_window(window_ann_excess: float, outage_rate: float,
                    n_trials: int, n_days: int = 252,
                    rng: random.Random | None = None) -> list[float]:
    """Return list of degraded ann_excess values, one per trial."""
    rng = rng or random.Random()
    daily_alpha = window_ann_excess / n_days
    results = []
    for _ in range(n_trials):
        # k = number of missed days ~ Binomial(n_days, outage_rate)
        k = sum(1 for _ in range(n_days) if rng.random() < outage_rate)
        # Degraded: kept (n_days - k) days of alpha, lost k days of it
        # Compound the daily alpha for kept days; missed days contribute 0 alpha
        # (they're held-flat or in cash, picking up benchmark — since we're
        # working with EXCESS returns, missed days = 0 excess)
        kept_days = n_days - k
        degraded = (1 + daily_alpha) ** kept_days - 1
        results.append(degraded)
    return results


def percentile(xs: list[float], q: float) -> float:
    """Inclusive percentile (no numpy dependency)."""
    if not xs:
        return float("nan")
    s = sorted(xs)
    rank = (len(s) - 1) * q
    lo = int(rank)
    hi = min(lo + 1, len(s) - 1)
    frac = rank - lo
    return s[lo] * (1 - frac) + s[hi] * frac


def compute(summary_csv: Path, outage_rates: list[float],
            n_trials: int = 2000, seed: int = 42) -> dict:
    rows = []
    with open(summary_csv) as f:
        for r in csv.DictReader(f):
            rows.append({
                "window": int(r["window"]),
                "excess_ann_ret": float(r["excess_ann_ret"]),
            })
    if not rows:
        raise SystemExit(f"[abort] {summary_csv} empty")

    rng = random.Random(seed)
    scenarios = []
    for outage in outage_rates:
        # Pool degraded-excess across all windows
        pooled = []
        per_window = []
        for r in rows:
            trials = simulate_window(r["excess_ann_ret"], outage, n_trials, rng=rng)
            pooled.extend(trials)
            per_window.append({
                "window": r["window"],
                "baseline_excess": round(r["excess_ann_ret"], 4),
                "median_degraded_excess": round(percentile(trials, 0.5), 4),
                "p10": round(percentile(trials, 0.10), 4),
                "p90": round(percentile(trials, 0.90), 4),
            })
        scenarios.append({
            "outage_rate": outage,
            "expected_missed_days_per_year": round(252 * outage, 1),
            "pooled_median_excess": round(percentile(pooled, 0.5), 4),
            "pooled_p10":  round(percentile(pooled, 0.10), 4),
            "pooled_p90":  round(percentile(pooled, 0.90), 4),
            "pooled_mean": round(mean(pooled), 4),
            "by_window": per_window,
        })

    baseline_mean = mean(r["excess_ann_ret"] for r in rows)
    return {
        "source": str(summary_csv),
        "n_windows": len(rows),
        "n_trials_per_cell": n_trials,
        "baseline_mean_excess": round(baseline_mean, 4),
        "scenarios": scenarios,
        "interpretation": (
            f"Baseline mean excess across {len(rows)} walk-forward windows: "
            f"{baseline_mean:.1%}. At a {outage_rates[-1]:.0%} outage rate "
            f"(~{int(252 * outage_rates[-1])} missed days/yr), pooled median "
            f"excess drops to {scenarios[-1]['pooled_median_excess']:.1%}. "
            "The strategy degrades roughly linearly with missed days because "
            "alpha compounds multiplicatively — missing 5% of days costs "
            "~5% of the year's alpha, not the full year."
        ),
        "caveats": [
            "Model assumes missed days contribute zero EXCESS return — i.e. "
            "you sat in cash or held existing positions through the gap. "
            "In practice you might also miss a SELL signal and amplify a loss.",
            "Binomial outage model assumes independent daily failures. A real "
            "outage is often clustered (one weekend, one bad week of travel).",
            "Per-window degradation does not account for which specific days "
            "you missed — missing a top-1% day is much worse than average.",
        ],
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--summary_csv", default="outputs/summary.csv")
    p.add_argument("--out", default="outputs/outage_monte_carlo.json")
    p.add_argument("--outage_rates", type=float, nargs="+",
                   default=[0.01, 0.02, 0.05, 0.10])
    p.add_argument("--n_trials", type=int, default=2000)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    result = compute(Path(args.summary_csv), args.outage_rates,
                     n_trials=args.n_trials, seed=args.seed)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=2))
    print(f"[outage-mc] wrote {args.out}")
    print(f"[outage-mc] {result['interpretation']}")


if __name__ == "__main__":
    main()
