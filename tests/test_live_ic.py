"""Tests for nse_live_ic — Tier 3 of the Kite read-only stack.

Pure helpers (compute_live_returns, compute_live_ic, picks_from_decision)
carry the math; we test them directly. No qlib, no kiteconnect, no network.
"""
import csv
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "examples"))

import nse_live_ic as mod


# -----------------------------------------------------------------------------
# compute_live_returns — the symbol-level join
# -----------------------------------------------------------------------------

def test_compute_live_returns_basic_join():
    rows = mod.compute_live_returns(
        scores={"INFY": 0.2, "TCS": -0.1, "WIPRO": 0.05},
        ref_closes={"INFY": 1450.0, "TCS": 3500.0, "WIPRO": 500.0},
        kite_last={"INFY": 1500.0, "TCS": 3450.0, "WIPRO": 510.0},
    )
    assert len(rows) == 3
    by_sym = {r["symbol"]: r for r in rows}
    assert math.isclose(by_sym["INFY"]["ret"], 50 / 1450, rel_tol=1e-9)
    assert math.isclose(by_sym["TCS"]["ret"], -50 / 3500, rel_tol=1e-9)


def test_compute_live_returns_drops_missing_ref_or_kite():
    rows = mod.compute_live_returns(
        scores={"INFY": 0.2, "TCS": 0.1, "WIPRO": 0.05},
        ref_closes={"INFY": 1450.0, "TCS": 3500.0},      # WIPRO missing here
        kite_last={"INFY": 1500.0, "WIPRO": 510.0},      # TCS missing here
    )
    assert [r["symbol"] for r in rows] == ["INFY"]


def test_compute_live_returns_skips_zero_or_negative_prices():
    rows = mod.compute_live_returns(
        scores={"X": 0.1, "Y": 0.2, "Z": 0.3},
        ref_closes={"X": 0.0, "Y": -1.0, "Z": 100.0},
        kite_last={"X": 100.0, "Y": 100.0, "Z": 110.0},
    )
    assert [r["symbol"] for r in rows] == ["Z"]


def test_compute_live_returns_skips_unparseable_strings():
    rows = mod.compute_live_returns(
        scores={"X": 0.1, "Y": 0.2},
        ref_closes={"X": "not-a-number", "Y": 100.0},
        kite_last={"X": 110, "Y": 110},
    )
    assert [r["symbol"] for r in rows] == ["Y"]


# -----------------------------------------------------------------------------
# compute_live_ic — pearson + spearman
# -----------------------------------------------------------------------------

def test_ic_perfect_positive_correlation():
    """When score and return rank-align perfectly, pearson and rank_ic both = 1."""
    rows = [
        {"symbol": "A", "score": 0.1, "ret": 0.01},
        {"symbol": "B", "score": 0.2, "ret": 0.02},
        {"symbol": "C", "score": 0.3, "ret": 0.03},
        {"symbol": "D", "score": 0.4, "ret": 0.04},
    ]
    ic = mod.compute_live_ic(rows)
    assert ic["n"] == 4
    assert math.isclose(ic["pearson_ic"], 1.0, rel_tol=1e-6)
    assert math.isclose(ic["rank_ic"], 1.0, rel_tol=1e-6)
    assert ic["pct_positive"] == 1.0


def test_ic_perfect_negative_correlation():
    rows = [
        {"symbol": "A", "score": 0.1, "ret": 0.04},
        {"symbol": "B", "score": 0.2, "ret": 0.03},
        {"symbol": "C", "score": 0.3, "ret": 0.02},
        {"symbol": "D", "score": 0.4, "ret": 0.01},
    ]
    ic = mod.compute_live_ic(rows)
    assert math.isclose(ic["pearson_ic"], -1.0, rel_tol=1e-6)
    assert math.isclose(ic["rank_ic"], -1.0, rel_tol=1e-6)


def test_ic_too_few_observations():
    rows = [
        {"symbol": "A", "score": 0.1, "ret": 0.01},
        {"symbol": "B", "score": 0.2, "ret": 0.02},
    ]
    ic = mod.compute_live_ic(rows)
    assert ic["pearson_ic"] is None
    assert ic["rank_ic"] is None


def test_ic_constant_scores_returns_none():
    """No variance in scores -> correlation undefined, must not crash."""
    rows = [
        {"symbol": "A", "score": 0.2, "ret": 0.01},
        {"symbol": "B", "score": 0.2, "ret": 0.02},
        {"symbol": "C", "score": 0.2, "ret": 0.03},
    ]
    ic = mod.compute_live_ic(rows)
    assert ic["pearson_ic"] is None
    assert ic["rank_ic"] is None
    # mean_return_bps should still be computable
    assert ic["mean_return_bps"] is not None


def test_ic_rank_robust_to_outlier():
    """Rank IC ignores magnitude — one big outlier shouldn't flip the rank."""
    rows = [
        {"symbol": "A", "score": 0.1, "ret": 0.01},
        {"symbol": "B", "score": 0.2, "ret": 0.02},
        {"symbol": "C", "score": 0.3, "ret": 0.03},
        {"symbol": "D", "score": 0.4, "ret": 100.0},  # huge outlier preserves rank
    ]
    ic = mod.compute_live_ic(rows)
    assert ic["rank_ic"] == 1.0
    # Pearson is dragged by the outlier but should remain positive
    assert ic["pearson_ic"] > 0


# -----------------------------------------------------------------------------
# picks_from_decision
# -----------------------------------------------------------------------------

def test_picks_from_decision_uses_actions_buckets():
    decision = {
        "as_of": "2026-04-23",
        "actions": {
            "BUY":  [{"symbol": "INFY", "score": 0.2, "rank": 1}],
            "SELL": [{"symbol": "ITC",  "score": -0.1, "rank": 100}],
            "HOLD": [{"symbol": "TCS",  "score": 0.05, "rank": 30}],
        },
    }
    out = mod.picks_from_decision(decision)
    assert out == {"INFY": 0.2, "ITC": -0.1, "TCS": 0.05}


def test_picks_from_decision_falls_back_to_candidates_list():
    decision = {
        "as_of": "2026-04-23",
        "actions": {"BUY": [], "SELL": [], "HOLD": []},
        "top_10_candidates": [
            {"instrument": "WIPRO", "score": 0.15},
            {"instrument": "INFY",  "score": 0.20},
        ],
    }
    out = mod.picks_from_decision(decision)
    assert out == {"WIPRO": 0.15, "INFY": 0.20}


def test_picks_from_decision_action_takes_precedence_over_candidates():
    decision = {
        "actions": {"BUY": [{"symbol": "INFY", "score": 0.99}], "SELL": [], "HOLD": []},
        "top_10_candidates": [{"instrument": "INFY", "score": 0.01}],
    }
    out = mod.picks_from_decision(decision)
    assert out["INFY"] == 0.99  # actions win


# -----------------------------------------------------------------------------
# CSV write
# -----------------------------------------------------------------------------

def test_append_csv_writes_header_then_appends(tmp_path):
    path = tmp_path / "live_ic.csv"
    mod.append_csv_row(path, {"a": 1, "b": 2})
    mod.append_csv_row(path, {"a": 3, "b": 4})
    with path.open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2
    assert rows[0]["a"] == "1"
    assert rows[1]["b"] == "4"
