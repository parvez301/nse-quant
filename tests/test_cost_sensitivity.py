"""Smoke test for cost sensitivity wrapper — verifies the matrix builder
correctly delegates to simulate() and produces well-formed cells.

We mock simulate() to keep the test fast and independent of qlib data.
"""
import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "examples"))

import nse_cost_sensitivity as mod


def fake_simulate(*, pred, px, capital, topk, n_drop, rebalance, slip, benchmark_ret):
    """Return a deterministic mock that depends on capital + bps so we can
    verify each cell really called simulate with the right args."""
    return {
        "ann_return": 0.30 - capital * 1e-9 - slip.base_bps * 0.01,
        "sharpe": 1.5,
        "excess_ann_return": 0.20 - capital * 1e-9 - slip.base_bps * 0.005,
        "max_drawdown": -0.15,
        "avg_slippage_bps": slip.base_bps + 2.0,
        "p95_slippage_bps": slip.base_bps + 8.0,
        "total_cost_pct": 0.001 * (slip.base_bps + 5),
    }


def fake_load_universe_data(provider_uri, instruments, start, end):
    return pd.DataFrame()


def fake_get_benchmark_returns(provider_uri, name, start, end):
    return pd.Series([0.001, -0.001, 0.002])


def test_matrix_builds_all_cells(tmp_path: Path):
    pred = pd.DataFrame(
        {"score": [0.5, 0.3, 0.1]},
        index=pd.MultiIndex.from_tuples(
            [(pd.Timestamp("2024-01-01"), "AAA"),
             (pd.Timestamp("2024-01-01"), "BBB"),
             (pd.Timestamp("2024-01-01"), "CCC")],
            names=["datetime", "instrument"],
        ),
    )
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    pred.to_pickle(model_dir / "pred.pkl")

    with patch.object(mod, "simulate", side_effect=fake_simulate), \
         patch.object(mod, "load_universe_data", side_effect=fake_load_universe_data), \
         patch.object(mod, "get_benchmark_returns", side_effect=fake_get_benchmark_returns):
        result = mod.run_matrix(
            model_dir=model_dir,
            provider_uri="ignored",
            benchmark="NIFTY50",
            capitals=[1_000_000, 10_000_000],
            base_bps_list=[5.0, 20.0],
            impact_coef=50.0,
            topk=30, n_drop=5, rebalance=5,
        )

    assert len(result["cells"]) == 4  # 2 capitals × 2 base_bps
    # Order: outer loop capital, inner loop bps
    cells = result["cells"]
    assert cells[0]["capital_inr"] == 1_000_000 and cells[0]["base_bps"] == 5.0
    assert cells[1]["capital_inr"] == 1_000_000 and cells[1]["base_bps"] == 20.0
    assert cells[2]["capital_inr"] == 10_000_000 and cells[2]["base_bps"] == 5.0
    assert cells[3]["capital_inr"] == 10_000_000 and cells[3]["base_bps"] == 20.0

    # Higher base_bps must produce lower excess returns (sanity)
    assert cells[0]["excess_ann_return"] > cells[1]["excess_ann_return"]
    # Higher capital must produce lower returns (sanity — bigger trades = more impact)
    assert cells[0]["ann_return"] > cells[2]["ann_return"]


def test_aborts_when_no_pred_pickle(tmp_path: Path):
    import pytest
    with pytest.raises(SystemExit):
        mod.run_matrix(
            model_dir=tmp_path,  # empty dir, no pred.pkl
            provider_uri="ignored",
            benchmark="NIFTY50",
            capitals=[1_000_000],
            base_bps_list=[5.0],
            impact_coef=50.0,
            topk=30, n_drop=5, rebalance=5,
        )
