"""Tests for the named-delisted-ticker layer of nse_survivorship_estimate.

The visible-exits computation needs qlib + a real dataset and is exercised
via the existing test_outage_monte_carlo / smoke runs. Here we focus on the
new `named_delisted_penalty` pure function and the JSON loader.
"""
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "examples"))

import nse_survivorship_estimate as mod


# -----------------------------------------------------------------------------
# load_known_delisted
# -----------------------------------------------------------------------------

def test_load_known_delisted_returns_empty_for_missing_path(tmp_path):
    assert mod.load_known_delisted(tmp_path / "absent.json") == []


def test_load_known_delisted_reads_curated_file(tmp_path):
    p = tmp_path / "delisted.json"
    p.write_text(json.dumps({
        "_meta": {"x": 1},
        "delisted": [
            {"ticker": "DHFL", "first_active_year": 2010,
             "last_active_year": 2021, "approx_total_return_pct": -95},
        ],
    }))
    rows = mod.load_known_delisted(p)
    assert len(rows) == 1
    assert rows[0]["ticker"] == "DHFL"


def test_real_curated_file_loads_and_has_required_keys():
    """Smoke-test the actual repo-shipped file; catches schema regressions."""
    rows = mod.load_known_delisted("data/known_delisted_nse.json")
    assert len(rows) >= 5
    for entry in rows:
        assert "ticker" in entry
        assert "approx_total_return_pct" in entry
        assert entry["approx_total_return_pct"] < 0  # sanity: all are losses


# -----------------------------------------------------------------------------
# named_delisted_penalty — pure math
# -----------------------------------------------------------------------------

def test_penalty_empty_inputs_return_zero():
    out = mod.named_delisted_penalty([], visible_universe_size=750, years=15)
    assert out["n_named_delisted"] == 0
    assert out["annualised_drag_bps"] is None
    assert out["implied_extra_universe_pct"] == 0.0


def test_penalty_zero_universe_returns_zero():
    out = mod.named_delisted_penalty(
        [{"ticker": "X", "first_active_year": 2010, "last_active_year": 2020,
          "approx_total_return_pct": -90}],
        visible_universe_size=0, years=10,
    )
    assert out["n_named_delisted"] == 0


def test_penalty_single_ticker_math():
    """One name held 10 years, total return -90% → annual ~ -20.6% per year.
    With universe 100 visible + 1 implied = 1.0% of widened universe.
    Drag = 0.01 * (-(-0.206)) ≈ 0.00206 of headline = ~20.6 bps/yr."""
    out = mod.named_delisted_penalty(
        [{"ticker": "DHFL", "first_active_year": 2010, "last_active_year": 2020,
          "approx_total_return_pct": -90}],
        visible_universe_size=100, years=10,
    )
    assert out["n_named_delisted"] == 1
    assert out["implied_extra_universe_pct"] == round(1 / 101 * 100, 2)
    # Independent compute for assertion
    annual = (1 + (-90 / 100)) ** (1 / 10) - 1   # ~ -0.2057
    expected = -(1 / 101) * annual * 1e4         # ~+20.4 bps
    assert math.isclose(out["annualised_drag_bps"], round(expected, 1), abs_tol=0.5)


def test_penalty_skips_malformed_entries():
    rows = [
        {"ticker": "GOOD", "first_active_year": 2010, "last_active_year": 2020,
         "approx_total_return_pct": -80},
        {"ticker": "BAD_NO_END", "first_active_year": 2010, "last_active_year": None,
         "approx_total_return_pct": -80},
        {"ticker": "BAD_INVERTED", "first_active_year": 2020, "last_active_year": 2015,
         "approx_total_return_pct": -80},
        {"ticker": "BAD_NO_RET", "first_active_year": 2010, "last_active_year": 2020},
    ]
    out = mod.named_delisted_penalty(rows, visible_universe_size=750, years=15)
    assert out["n_named_delisted"] == 1
    assert out["tickers"] == ["GOOD"]


def test_penalty_drag_increases_with_more_named_tickers():
    """Adding more delisted names should monotonically widen the penalty."""
    one = mod.named_delisted_penalty(
        [{"ticker": "A", "first_active_year": 2010, "last_active_year": 2020,
          "approx_total_return_pct": -90}],
        visible_universe_size=750, years=15,
    )
    five = mod.named_delisted_penalty(
        [{"ticker": f"T{i}", "first_active_year": 2010, "last_active_year": 2020,
          "approx_total_return_pct": -90}
         for i in range(5)],
        visible_universe_size=750, years=15,
    )
    assert five["annualised_drag_bps"] > one["annualised_drag_bps"]
