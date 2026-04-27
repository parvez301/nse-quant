"""Unit tests for nse_outage_monte_carlo."""
import csv
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "examples"))

import nse_outage_monte_carlo as mod


def test_zero_outage_recovers_baseline():
    """With outage_rate = 0, degraded excess == baseline (rounded)."""
    rng = random.Random(1)
    trials = mod.simulate_window(0.30, outage_rate=0.0, n_trials=50, rng=rng)
    # Every trial loses 0 days, so degraded == (1 + 0.30/252)^252 - 1 == ~ exp(0.30) - 1
    expected = (1 + 0.30 / 252) ** 252 - 1
    assert all(abs(t - expected) < 1e-9 for t in trials)


def test_full_outage_kills_alpha():
    """With outage_rate = 1.0, every day missed -> degraded = 0."""
    rng = random.Random(1)
    trials = mod.simulate_window(0.30, outage_rate=1.0, n_trials=20, rng=rng)
    assert all(t == 0.0 for t in trials)


def test_partial_outage_degrades_proportionally():
    """Median degraded excess should decrease as outage rate increases."""
    rng = random.Random(7)
    a = mod.simulate_window(0.30, 0.02, 500, rng=rng)
    b = mod.simulate_window(0.30, 0.10, 500, rng=rng)
    assert mod.percentile(a, 0.5) > mod.percentile(b, 0.5)


def test_percentile_basics():
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert mod.percentile(xs, 0.0) == 1.0
    assert mod.percentile(xs, 1.0) == 5.0
    assert mod.percentile(xs, 0.5) == 3.0
    assert mod.percentile([], 0.5) != mod.percentile([], 0.5)  # NaN check


def test_compute_against_synthetic_csv(tmp_path: Path):
    csv_path = tmp_path / "summary.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["window", "rank_ic_mean", "rank_ic_ir", "ic_mean",
                    "strat_ann_ret", "strat_sharpe", "strat_max_dd",
                    "excess_ann_ret", "excess_sharpe", "excess_max_dd"])
        w.writerow([2018, 0.08, 1.2, 0.11, 0.28, 1.2, -0.24, 0.20, 1.3, -0.13])
        w.writerow([2019, 0.07, 1.1, 0.12, 0.48, 2.0, -0.22, 0.30, 2.0, -0.12])
        w.writerow([2022, 0.07, 0.9, 0.08, 0.36, 1.5, -0.17, 0.25, 1.7, -0.11])

    result = mod.compute(csv_path, outage_rates=[0.0, 0.05, 0.10], n_trials=300)

    assert result["n_windows"] == 3
    assert len(result["scenarios"]) == 3

    # Increasing outage -> decreasing pooled median excess
    medians = [s["pooled_median_excess"] for s in result["scenarios"]]
    assert medians == sorted(medians, reverse=True)

    # 0% outage scenario must be in the same ball park as the baseline mean
    # (continuous compounding inflates the median slightly: e^r - 1 > r)
    zero = result["scenarios"][0]
    assert abs(zero["pooled_median_excess"] - result["baseline_mean_excess"]) < 0.05

    # JSON must be serializable
    json.dumps(result)


def test_compute_against_real_summary():
    """Smoke test against the actual CSV if present."""
    real = Path(__file__).resolve().parent.parent / "outputs" / "summary.csv"
    if not real.exists():
        return
    result = mod.compute(real, outage_rates=[0.0, 0.02, 0.05, 0.10], n_trials=200)
    # Sanity: with 0% outage, degraded median is positive and bounded
    zero_median = result["scenarios"][0]["pooled_median_excess"]
    assert zero_median > 0
    # Continuous compounding inflates: median should be >= baseline mean
    # but within a reasonable factor (not orders of magnitude off)
    assert zero_median >= result["baseline_mean_excess"] * 0.9
    assert zero_median <= result["baseline_mean_excess"] * 2.5
    # 10% outage must produce strictly lower median than 0% outage
    assert result["scenarios"][-1]["pooled_median_excess"] < zero_median
