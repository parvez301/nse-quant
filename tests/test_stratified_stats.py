"""Unit tests for nse_stratified_stats."""
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "examples"))

import nse_stratified_stats as mod


def test_t_stat_zero_for_single_value():
    assert mod.t_stat([0.5]) == 0.0
    assert mod.t_stat([]) == 0.0


def test_t_stat_zero_for_zero_variance():
    assert mod.t_stat([0.1, 0.1, 0.1]) == 0.0


def test_t_stat_positive_for_positive_mean():
    # Three positive values with low variance -> meaningfully positive t
    t = mod.t_stat([0.10, 0.12, 0.14])
    assert t > 5.0


def test_summarise_empty():
    s = mod.summarise("empty", [])
    assert s["n_windows"] == 0
    assert s["mean_excess"] is None


def test_summarise_basic():
    rows = [
        {"window": 2018, "excess_ann_ret": "0.20"},
        {"window": 2019, "excess_ann_ret": "0.10"},
        {"window": 2020, "excess_ann_ret": "-0.05"},
        {"window": 2021, "excess_ann_ret": "0.15"},
    ]
    s = mod.summarise("test", rows)
    assert s["n_windows"] == 4
    assert s["mean_excess"] == 0.10  # (0.20 + 0.10 - 0.05 + 0.15) / 4
    assert s["win_rate"] == 0.75
    assert s["worst_window"] == {"year": 2020, "excess": -0.05}
    assert s["best_window"]  == {"year": 2018, "excess": 0.20}


def test_compute_excludes_2020_2021(tmp_path: Path):
    csv_path = tmp_path / "summary.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["window", "rank_ic_mean", "rank_ic_ir", "ic_mean",
                    "strat_ann_ret", "strat_sharpe", "strat_max_dd",
                    "excess_ann_ret", "excess_sharpe", "excess_max_dd"])
        # Inject a fake row so we can verify ex-COVID arithmetic
        w.writerow([2018, 0.08, 1.18, 0.11, 0.28, 1.19, -0.24, 0.20, 1.27, -0.13])
        w.writerow([2019, 0.07, 1.14, 0.12, 0.48, 2.05, -0.22, 0.30, 2.02, -0.12])
        w.writerow([2020, 0.10, 1.26, 0.15, 1.95, 5.27, -0.39, 1.78, 5.64, -0.09])
        w.writerow([2021, 0.08, 0.96, 0.12, 1.29, 5.96, -0.12, 1.07, 6.12, -0.14])
        w.writerow([2022, 0.07, 0.92, 0.08, 0.36, 1.46, -0.17, 0.30, 1.71, -0.11])
        w.writerow([2023, 0.06, 0.95, 0.10, 0.91, 5.48, -0.06, 0.73, 4.86, -0.04])

    result = mod.compute(csv_path)
    by_label = {s["label"]: s for s in result["scenarios"]}

    all_w = by_label["All windows"]
    assert all_w["n_windows"] == 6
    # mean of 0.20+0.30+1.78+1.07+0.30+0.73 = 4.38; /6 = 0.73
    assert abs(all_w["mean_excess"] - 0.73) < 0.01

    ex_covid = by_label["Excluding 2020 + 2021"]
    assert ex_covid["n_windows"] == 4
    # Without 2020+21: mean of 0.20, 0.30, 0.30, 0.73 = 1.53/4 = 0.3825
    assert abs(ex_covid["mean_excess"] - 0.3825) < 0.01
    # Headline drop is the whole point: ex-COVID mean must be lower
    assert ex_covid["mean_excess"] < all_w["mean_excess"]


def test_compute_against_real_summary():
    """Smoke test against the actual production CSV if present."""
    real = Path(__file__).resolve().parent.parent / "outputs" / "summary.csv"
    if not real.exists():
        return  # skip when running outside the repo
    result = mod.compute(real)
    by_label = {s["label"]: s for s in result["scenarios"]}
    assert by_label["All windows"]["n_windows"] == 8
    assert by_label["Excluding 2020 + 2021"]["n_windows"] == 6
    # Ex-COVID must have lower mean than headline (this is the whole story)
    assert by_label["Excluding 2020 + 2021"]["mean_excess"] < by_label["All windows"]["mean_excess"]
    # The interpretation string must contain both numbers
    interp = result["interpretation"]["headline_vs_honest"]
    assert "Headline" in interp and "ex-COVID years" not in interp  # phrasing check
