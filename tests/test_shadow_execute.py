"""Tests for nse_shadow_execute — Tier 1 of the Kite read-only stack.

The pure helpers carry the logic. The CLI just plumbs them. We test the
helpers directly and one end-to-end run with a mocked quote fetcher.
"""
import csv
import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "examples"))

import nse_shadow_execute as mod


# -----------------------------------------------------------------------------
# kite_symbol
# -----------------------------------------------------------------------------

def test_kite_symbol_adds_nse_prefix():
    assert mod.kite_symbol("INFY") == "NSE:INFY"


def test_kite_symbol_passes_through_prefixed():
    assert mod.kite_symbol("BSE:RELIANCE") == "BSE:RELIANCE"


# -----------------------------------------------------------------------------
# walk_book — the pricing kernel
# -----------------------------------------------------------------------------

def test_walk_book_full_fill_at_first_level():
    levels = [{"price": 100.0, "quantity": 500}, {"price": 101.0, "quantity": 200}]
    result = mod.walk_book(levels, shares=300)
    assert result["fill_price"] == 100.0
    assert result["fully_filled"] is True
    assert result["levels_consumed"] == 1


def test_walk_book_partial_fill_two_levels_vwap():
    """Shares 250 -> consume 100 @ 100.0 then 150 @ 101.0 = 25150 / 250 = 100.6"""
    levels = [{"price": 100.0, "quantity": 100}, {"price": 101.0, "quantity": 200}]
    result = mod.walk_book(levels, shares=250)
    assert math.isclose(result["fill_price"], 100.6, rel_tol=1e-9)
    assert result["fully_filled"] is True
    assert result["levels_consumed"] == 2


def test_walk_book_insufficient_depth():
    """Total depth 100, want 200: fully_filled False, fill_price = NaN-ish."""
    levels = [{"price": 100.0, "quantity": 100}]
    result = mod.walk_book(levels, shares=200)
    assert result["fully_filled"] is False
    # Even though we couldn't fully fill, we report the partial VWAP.
    # That's the "what would have actually happened" signal.
    assert result["fill_price"] == 100.0
    assert result["available_qty"] == 100


def test_walk_book_empty_book():
    result = mod.walk_book([], shares=100)
    assert math.isnan(result["fill_price"])
    assert result["fully_filled"] is False
    assert result["available_qty"] == 0


def test_walk_book_zero_shares_raises():
    with pytest.raises(ValueError):
        mod.walk_book([{"price": 100.0, "quantity": 100}], shares=0)


def test_walk_book_malformed_level_raises():
    with pytest.raises(ValueError):
        mod.walk_book([{"price": -1.0, "quantity": 100}], shares=10)


def test_walk_book_skips_zero_padded_kite_levels():
    """Kite returns 5 depth slots per side; unused ones come back as
    {price:0, quantity:0} — must be treated as no-op, not malformed."""
    levels = [
        {"price": 100.0, "quantity": 50, "orders": 1},
        {"price": 101.0, "quantity": 100, "orders": 2},
        {"price": 0,     "quantity": 0,  "orders": 0},   # unused slot
        {"price": 0,     "quantity": 0,  "orders": 0},
        {"price": 0,     "quantity": 0,  "orders": 0},
    ]
    result = mod.walk_book(levels, shares=120)
    # 50 @ 100 + 70 @ 101 = 5000 + 7070 = 12070 / 120 = 100.583...
    assert math.isclose(result["fill_price"], 12070 / 120, rel_tol=1e-9)
    assert result["fully_filled"] is True
    assert result["levels_consumed"] == 2  # zero-padded slots not counted


# -----------------------------------------------------------------------------
# compute_slippage_bps
# -----------------------------------------------------------------------------

def test_slippage_buy_paid_up_is_positive():
    """Bought at 100.5 vs model 100.0 -> +50 bps unfavorable."""
    assert math.isclose(
        mod.compute_slippage_bps(100.0, 100.5, "BUY"), 50.0, rel_tol=1e-9
    )


def test_slippage_sell_under_model_is_positive():
    """Sold at 99.5 vs model 100.0 -> +50 bps unfavorable."""
    assert math.isclose(
        mod.compute_slippage_bps(100.0, 99.5, "SELL"), 50.0, rel_tol=1e-9
    )


def test_slippage_better_than_model_is_negative():
    """Bought below model (rare) -> negative slippage = favorable."""
    assert mod.compute_slippage_bps(100.0, 99.0, "BUY") < 0


def test_slippage_nan_propagates():
    assert math.isnan(mod.compute_slippage_bps(100.0, float("nan"), "BUY"))
    assert math.isnan(mod.compute_slippage_bps(0.0, 100.0, "BUY"))


# -----------------------------------------------------------------------------
# merge_decision_with_fills
# -----------------------------------------------------------------------------

def _decision(as_of, buys=(), sells=()):
    return {
        "as_of": as_of,
        "actions": {
            "BUY": [{"symbol": s, "rank": i, "score": 0.1} for i, s in enumerate(buys)],
            "SELL": [{"symbol": s, "rank": i, "score": 0.0} for i, s in enumerate(sells)],
            "HOLD": [],
        },
    }


def test_merge_pairs_paper_fills_with_decision():
    decision = _decision("2026-04-23", buys=("INFY", "TCS"), sells=("ITC",))
    paper = [
        {"date": "2026-04-23", "action": "BUY", "symbol": "INFY", "shares": "10", "price": "1450.0"},
        {"date": "2026-04-23", "action": "SELL", "symbol": "ITC", "shares": "100", "price": "470.0"},
        # noise: different date
        {"date": "2026-04-22", "action": "BUY", "symbol": "WIPRO", "shares": "50", "price": "500.0"},
        # noise: TCS in BUY list but never executed (paper skipped it)
    ]
    fills = mod.merge_decision_with_fills(decision, paper)
    assert len(fills) == 2
    by_sym = {f["symbol"]: f for f in fills}
    assert by_sym["INFY"]["shares"] == 10
    assert by_sym["INFY"]["model_price"] == 1450.0
    assert by_sym["ITC"]["action"] == "SELL"


def test_merge_skips_zero_share_rows():
    decision = _decision("2026-04-23", buys=("INFY",))
    paper = [{"date": "2026-04-23", "action": "BUY", "symbol": "INFY", "shares": "0", "price": "1450"}]
    assert mod.merge_decision_with_fills(decision, paper) == []


def test_merge_handles_missing_decision_date():
    decision = {"actions": {"BUY": [], "SELL": []}}
    assert mod.merge_decision_with_fills(decision, []) == []


# -----------------------------------------------------------------------------
# shadow_fill — wrapper around walk_book that picks the right side of the book
# -----------------------------------------------------------------------------

def test_shadow_fill_buy_consumes_asks():
    quote = {
        "last_price": 100.0,
        "depth": {
            "buy":  [{"price": 99.0, "quantity": 1000}],   # bids — irrelevant for BUY
            "sell": [{"price": 100.5, "quantity": 50}, {"price": 101.0, "quantity": 100}],
        },
    }
    result = mod.shadow_fill(quote, "BUY", shares=100)
    # 50 @ 100.5 + 50 @ 101.0 = (5025 + 5050) / 100 = 100.75
    assert math.isclose(result["fill_price"], 100.75, rel_tol=1e-9)


def test_shadow_fill_sell_consumes_bids():
    quote = {
        "last_price": 100.0,
        "depth": {
            "buy":  [{"price": 99.5, "quantity": 200}, {"price": 99.0, "quantity": 500}],
            "sell": [{"price": 100.5, "quantity": 1000}],
        },
    }
    result = mod.shadow_fill(quote, "SELL", shares=300)
    # 200 @ 99.5 + 100 @ 99.0 = (19900 + 9900) / 300 = 99.333...
    assert math.isclose(result["fill_price"], 99.333333, rel_tol=1e-5)


def test_shadow_fill_no_depth_returns_nan():
    result = mod.shadow_fill({"last_price": 100.0}, "BUY", shares=10)
    assert math.isnan(result["fill_price"])


# -----------------------------------------------------------------------------
# End-to-end with mocked fetcher
# -----------------------------------------------------------------------------

def test_run_shadow_execution_writes_csv(tmp_path):
    decision_path = tmp_path / "2026-04-23.json"
    decision_path.write_text(json.dumps(
        _decision("2026-04-23", buys=("INFY",), sells=("ITC",))
    ))
    trade_log = tmp_path / "trade_log.csv"
    trade_log.write_text(
        "date,action,symbol,shares,price,amount,reason\n"
        "2026-04-23,BUY,INFY,10,1450.0,14500,rank 0\n"
        "2026-04-23,SELL,ITC,100,470.0,47000,strategy drop\n"
    )

    def fetcher(keys):
        # Returns a dict keyed by exactly what the caller asked for.
        return {
            "NSE:INFY": {
                "last_price": 1452.0,
                "depth": {
                    "sell": [{"price": 1452.5, "quantity": 20}, {"price": 1453.0, "quantity": 100}],
                    "buy":  [{"price": 1451.0, "quantity": 100}],
                },
            },
            "NSE:ITC": {
                "last_price": 469.0,
                "depth": {
                    "sell": [{"price": 469.5, "quantity": 1000}],
                    "buy":  [{"price": 468.5, "quantity": 200}, {"price": 468.0, "quantity": 500}],
                },
            },
        }

    output_path = tmp_path / "shadow_trade_log.csv"
    summary = mod.run_shadow_execution(
        decision_path=decision_path,
        trade_log_path=trade_log,
        output_path=output_path,
        quote_fetcher=fetcher,
        quote_taken_at="2026-04-23T03:30:00+00:00",
    )

    assert summary["rows"] == 2
    assert summary["fully_filled"] == 2

    with output_path.open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2

    by_sym = {r["symbol"]: r for r in rows}
    # INFY: 10 shares @ 1452.5 -> fill = 1452.5, model 1450.0 -> +17.24 bps
    assert math.isclose(float(by_sym["INFY"]["fill_price"]), 1452.5, rel_tol=1e-4)
    assert float(by_sym["INFY"]["slippage_bps"]) > 0  # paid up
    # ITC: 100 @ 468.5 -> fill 468.5, model 470 -> sold under = +31.9 bps
    assert math.isclose(float(by_sym["ITC"]["fill_price"]), 468.5, rel_tol=1e-4)
    assert float(by_sym["ITC"]["slippage_bps"]) > 0


def test_run_shadow_execution_appends_on_repeat(tmp_path):
    decision_path = tmp_path / "2026-04-23.json"
    decision_path.write_text(json.dumps(_decision("2026-04-23", buys=("INFY",))))
    trade_log = tmp_path / "trade_log.csv"
    trade_log.write_text(
        "date,action,symbol,shares,price,amount,reason\n"
        "2026-04-23,BUY,INFY,10,1450.0,14500,rank 0\n"
    )
    output_path = tmp_path / "shadow.csv"

    def fetcher(_keys):
        return {"NSE:INFY": {"last_price": 1450.0,
                "depth": {"sell": [{"price": 1450.0, "quantity": 1000}]}}}

    mod.run_shadow_execution(decision_path, trade_log, output_path, fetcher)
    mod.run_shadow_execution(decision_path, trade_log, output_path, fetcher)

    with output_path.open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2  # appended, header written once
