"""Tests for nse_kite_reconcile — Tier 2 of the Kite read-only stack.

The script's job is to compute three signals from Kite + paper-state:
margin verdict, holdings diff, and a JSON report stitching them. We test
the pure helpers; the SDK boundary is mocked out so no network calls.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "examples"))

import nse_kite_reconcile as mod


# -----------------------------------------------------------------------------
# kite_available_cash
# -----------------------------------------------------------------------------

def test_available_cash_picks_equity_segment():
    margins = {
        "equity": {"available": {"cash": 482912.5, "live_balance": 482912.5}},
        "commodity": {"available": {"cash": 0}},
    }
    assert mod.kite_available_cash(margins) == 482912.5


def test_available_cash_falls_back_to_live_balance():
    margins = {"equity": {"available": {"live_balance": 100.0}}}
    assert mod.kite_available_cash(margins) == 100.0


def test_available_cash_returns_zero_on_garbage():
    assert mod.kite_available_cash(None) == 0.0
    assert mod.kite_available_cash({}) == 0.0
    assert mod.kite_available_cash({"equity": "wrong"}) == 0.0


# -----------------------------------------------------------------------------
# paper_gross_value
# -----------------------------------------------------------------------------

def test_paper_gross_uses_last_price_when_present():
    rows = [
        {"symbol": "INFY", "shares": "10", "avg_price": "1450", "last_price": "1500"},
        {"symbol": "TCS", "shares": "5", "avg_price": "3500", "last_price": "3600"},
    ]
    # 10*1500 + 5*3600 = 15000 + 18000 = 33000, plus cash 5000 = 38000
    assert mod.paper_gross_value(rows, cash=5000) == 38000.0


def test_paper_gross_falls_back_to_avg_price_for_unmarked_rows():
    rows = [{"symbol": "INFY", "shares": "10", "avg_price": "1450", "last_price": ""}]
    assert mod.paper_gross_value(rows, cash=0) == 14500.0


def test_paper_gross_clamps_negative_cash_to_zero():
    rows = [{"symbol": "INFY", "shares": "10", "avg_price": "100"}]
    assert mod.paper_gross_value(rows, cash=-500) == 1000.0


def test_paper_gross_skips_malformed_rows():
    rows = [
        {"symbol": "INFY", "shares": "abc", "avg_price": "100"},
        {"symbol": "TCS", "shares": "1", "avg_price": "100"},
    ]
    assert mod.paper_gross_value(rows, cash=0) == 100.0


# -----------------------------------------------------------------------------
# margin_verdict
# -----------------------------------------------------------------------------

def test_margin_verdict_ok_when_within_limit():
    out = mod.margin_verdict(kite_cash=100000, paper_gross=120000, ratio_limit=1.5)
    assert out["verdict"] == "ok"
    assert out["ratio"] == 1.2


def test_margin_verdict_exceeds_when_above_limit():
    out = mod.margin_verdict(kite_cash=100000, paper_gross=200000, ratio_limit=1.5)
    assert out["verdict"] == "exceeds_margin"
    assert out["ratio"] == 2.0


def test_margin_verdict_no_paper_state():
    out = mod.margin_verdict(kite_cash=50000, paper_gross=0)
    assert out["verdict"] == "no_paper_state"


def test_margin_verdict_no_kite_funds():
    out = mod.margin_verdict(kite_cash=0, paper_gross=10000)
    assert out["verdict"] == "no_kite_funds"
    # JSON has no native infinity, so we serialise the unbounded ratio as None
    assert out["ratio"] is None


# -----------------------------------------------------------------------------
# diff_holdings
# -----------------------------------------------------------------------------

def test_diff_holdings_classifies_three_buckets():
    paper = [
        {"symbol": "INFY", "shares": "10"},   # in both, qty matches
        {"symbol": "TCS",  "shares": "5"},    # in both, qty mismatch
        {"symbol": "WIPRO", "shares": "20"},  # paper-only
    ]
    kite = [
        {"tradingsymbol": "INFY", "quantity": 10},
        {"tradingsymbol": "TCS",  "quantity": 7},
        {"tradingsymbol": "GOLDBEES", "quantity": 5},   # kite-only
    ]
    diff = mod.diff_holdings(paper, kite)
    assert diff["paper_count"] == 3
    assert diff["kite_count"] == 3
    assert diff["paper_only"] == ["WIPRO"]
    assert diff["kite_only"] == ["GOLDBEES"]
    assert len(diff["qty_mismatch"]) == 1
    assert diff["qty_mismatch"][0]["symbol"] == "TCS"
    assert diff["qty_mismatch"][0]["paper_qty"] == 5.0
    assert diff["qty_mismatch"][0]["kite_qty"] == 7.0


def test_diff_holdings_handles_empty_inputs():
    assert mod.diff_holdings([], []) == {
        "paper_count": 0, "kite_count": 0,
        "paper_only": [], "kite_only": [], "qty_mismatch": [],
    }


def test_diff_holdings_ignores_rows_with_blank_symbol():
    paper = [{"symbol": "", "shares": "10"}, {"symbol": "INFY", "shares": "5"}]
    kite = [{"tradingsymbol": None, "quantity": 1}, {"tradingsymbol": "INFY", "quantity": 5}]
    diff = mod.diff_holdings(paper, kite)
    assert diff["paper_count"] == 1
    assert diff["kite_count"] == 1
    assert diff["paper_only"] == []
    assert diff["kite_only"] == []


# -----------------------------------------------------------------------------
# build_reconcile_report — the full stitch
# -----------------------------------------------------------------------------

def test_build_report_stitches_everything():
    margins = {"equity": {"available": {"cash": 100000.0}}}
    holdings = [{"tradingsymbol": "GOLDBEES", "quantity": 5}]
    paper = [{"symbol": "INFY", "shares": "10", "avg_price": "1450", "last_price": "1500"}]
    last_equity = {"date": "2026-04-23", "cash": "5000", "total_equity": "20000"}

    report = mod.build_reconcile_report(
        margins=margins, holdings=holdings, paper_portfolio=paper,
        last_equity_row=last_equity, as_of="2026-04-27T08:00:00Z",
    )
    assert report["as_of"] == "2026-04-27T08:00:00Z"
    assert report["margin"]["paper_gross_value"] == 20000.0  # 10*1500 + 5000
    assert report["margin"]["kite_available_cash"] == 100000.0
    assert report["margin"]["verdict"] == "ok"
    assert report["holdings"]["paper_only"] == ["INFY"]
    assert report["holdings"]["kite_only"] == ["GOLDBEES"]


def test_build_report_handles_missing_equity_row():
    """No equity log yet — should still produce a report, just with cash=0."""
    report = mod.build_reconcile_report(
        margins={}, holdings=[], paper_portfolio=[],
        last_equity_row=None,
    )
    assert report["margin"]["verdict"] == "no_paper_state"
    assert report["holdings"]["paper_count"] == 0
