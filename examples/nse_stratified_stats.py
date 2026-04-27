#!/usr/bin/env python3
"""Stratified walk-forward statistics — answers "how does the model look in
different weather", not just the cherry-picked headline.

Reads outputs/summary.csv (the per-window walk-forward results) and writes
outputs/stratified_stats.json with:
  - all-windows stats (mean, std, t-stat, win rate, worst window)
  - excluding 2020+2021 (the COVID dispersion regime)
  - high-volatility vs low-volatility windows (proxied by strat_max_dd magnitude)
  - rolling worst 1-year and 2-year aggregates

Designed to be readable by a friend reviewing the methodology page.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from statistics import mean, stdev


def t_stat(values: list[float]) -> float:
    """One-sample t-stat against zero. Returns 0 if too few points."""
    if len(values) < 2:
        return 0.0
    m = mean(values)
    s = stdev(values)
    if s == 0:
        return 0.0
    return m / (s / math.sqrt(len(values)))


def summarise(label: str, rows: list[dict]) -> dict:
    if not rows:
        return {
            "label": label, "n_windows": 0,
            "mean_excess": None, "median_excess": None,
            "win_rate": None, "t_stat": None,
            "worst_window": None, "best_window": None,
        }
    excess = [float(r["excess_ann_ret"]) for r in rows]
    excess_sorted = sorted(zip(excess, [r["window"] for r in rows]))
    return {
        "label": label,
        "n_windows": len(rows),
        "mean_excess": round(mean(excess), 4),
        "median_excess": round(sorted(excess)[len(excess) // 2], 4),
        "win_rate": round(sum(1 for x in excess if x > 0) / len(excess), 4),
        "t_stat": round(t_stat(excess), 4),
        "worst_window": {"year": int(excess_sorted[0][1]), "excess": round(excess_sorted[0][0], 4)},
        "best_window":  {"year": int(excess_sorted[-1][1]), "excess": round(excess_sorted[-1][0], 4)},
    }


def compute(summary_csv: Path) -> dict:
    import csv
    rows = []
    with open(summary_csv) as f:
        for r in csv.DictReader(f):
            rows.append(r)

    if not rows:
        raise SystemExit(f"[abort] {summary_csv} is empty")

    rows_for_stats = [{**r, "window": int(r["window"])} for r in rows]

    all_windows = summarise("All windows", rows_for_stats)

    # Strip the COVID dispersion regime
    ex_covid = [r for r in rows_for_stats if r["window"] not in (2020, 2021)]
    ex_covid_stats = summarise("Excluding 2020 + 2021", ex_covid)

    # Volatility regime proxy: split windows by median strat_max_dd magnitude.
    # Bigger drawdowns = higher-vol regime.
    dd_pairs = sorted(
        rows_for_stats,
        key=lambda r: abs(float(r["strat_max_dd"])),
    )
    half = len(dd_pairs) // 2
    low_vol  = summarise("Low-volatility windows (smallest drawdowns)",  dd_pairs[:half])
    high_vol = summarise("High-volatility windows (biggest drawdowns)", dd_pairs[half:])

    # Concatenated 2-year periods (rolling): smallest 2-year mean is informative
    excess_by_year = {int(r["window"]): float(r["excess_ann_ret"]) for r in rows_for_stats}
    years = sorted(excess_by_year.keys())
    two_year_means = []
    for i in range(len(years) - 1):
        y1, y2 = years[i], years[i + 1]
        two_year_means.append({
            "period": f"{y1}-{y2}",
            "mean_excess": round((excess_by_year[y1] + excess_by_year[y2]) / 2, 4),
        })
    worst_2yr = min(two_year_means, key=lambda d: d["mean_excess"]) if two_year_means else None
    best_2yr  = max(two_year_means, key=lambda d: d["mean_excess"]) if two_year_means else None

    return {
        "source": str(summary_csv),
        "scenarios": [all_windows, ex_covid_stats, low_vol, high_vol],
        "rolling_2yr": {
            "all_periods": two_year_means,
            "worst": worst_2yr,
            "best": best_2yr,
        },
        "interpretation": {
            "headline_vs_honest": (
                f"Headline mean excess return = {all_windows['mean_excess']:.1%} per year "
                f"with t-stat {all_windows['t_stat']:.2f}. "
                f"Stripping the COVID-dispersion years (2020, 2021) drops it to "
                f"{ex_covid_stats['mean_excess']:.1%} with t-stat {ex_covid_stats['t_stat']:.2f}. "
                f"Worst rolling 2-year period: {worst_2yr['period']} at {worst_2yr['mean_excess']:.1%}."
                if worst_2yr else
                f"Headline mean excess = {all_windows['mean_excess']:.1%}; ex-COVID = {ex_covid_stats['mean_excess']:.1%}."
            ),
        },
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--summary_csv", default="outputs/summary.csv",
                   help="walk-forward per-window summary CSV")
    p.add_argument("--out", default="outputs/stratified_stats.json")
    args = p.parse_args()

    result = compute(Path(args.summary_csv))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=2))
    print(f"[stratified] wrote {args.out}")
    print(f"[stratified] {result['interpretation']['headline_vs_honest']}")


if __name__ == "__main__":
    main()
