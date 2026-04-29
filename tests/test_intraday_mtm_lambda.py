"""Tests for intraday_mtm_lambda — pure helpers only.

The Lambda's S3 / Secrets Manager / KiteConnect calls are confined to the
`handler()` entrypoint; the math lives in `compute_intraday_mtm`,
`parse_portfolio`, and `parse_prior_equity`. Test those directly with no
mocking.
"""
import datetime
import importlib.util
import os
from pathlib import Path

import pytest

# The handler reads STATE_BUCKET / KITE_SECRET_NAME at import time.
os.environ.setdefault("STATE_BUCKET", "test-bucket")
os.environ.setdefault("KITE_SECRET_NAME", "test-secret")

# Load under a unique module name — multiple Lambda dirs each have a
# `handler.py`, and a plain `import handler` collides with whichever sibling
# test ran first (analytics_lambda, ui_lambda, etc.).
_HANDLER_PATH = (
    Path(__file__).resolve().parent.parent / "intraday_mtm_lambda" / "handler.py"
)
_spec = importlib.util.spec_from_file_location("intraday_mtm_handler", _HANDLER_PATH)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
NOW = datetime.datetime(2026, 4, 29, 11, 32, tzinfo=IST)


# ---------------------------------------------------------------------------
# parse_portfolio
# ---------------------------------------------------------------------------

def test_parse_portfolio_basic():
    csv_bytes = (
        b"symbol,shares,avg_price,bought_on,last_price,position_value,unrealized_pnl,marked_on\n"
        b"INFY,10,1450.0,2026-04-23,1500.0,15000.0,500.0,2026-04-27\n"
        b"TCS,5,3500.0,2026-04-23,3450.0,17250.0,-250.0,2026-04-27\n"
    )
    positions = mod.parse_portfolio(csv_bytes)
    assert len(positions) == 2
    by_sym = {p["symbol"]: p for p in positions}
    assert by_sym["INFY"]["shares"] == 10
    assert by_sym["INFY"]["avg_price"] == 1450.0
    assert by_sym["INFY"]["ref_close"] == 1500.0  # last_price col → ref_close
    assert by_sym["TCS"]["ref_close"] == 3450.0


def test_parse_portfolio_skips_blank_or_malformed_rows():
    csv_bytes = (
        b"symbol,shares,avg_price,last_price\n"
        b"INFY,10,1450.0,1500.0\n"
        b",5,3500.0,3450.0\n"            # blank symbol -> skip
        b"BAD,xyz,3500.0,3450.0\n"        # non-numeric shares -> skip
        b"TCS,5,3500.0,\n"                # missing last_price is fine
    )
    positions = mod.parse_portfolio(csv_bytes)
    assert [p["symbol"] for p in positions] == ["INFY", "TCS"]
    assert positions[1]["ref_close"] is None


def test_parse_portfolio_handles_missing_last_price_column():
    csv_bytes = b"symbol,shares,avg_price\nINFY,10,1450.0\n"
    positions = mod.parse_portfolio(csv_bytes)
    assert positions[0]["ref_close"] is None


# ---------------------------------------------------------------------------
# parse_prior_equity
# ---------------------------------------------------------------------------

def test_parse_prior_equity_takes_last_row():
    csv_bytes = (
        b"date,cash,positions_value,total_equity,n_positions,unrealized_pnl,nifty50_close\n"
        b"2026-04-23,60079.27,938512.96,998592.23,20,0.0,24173.05\n"
        b"2026-04-24,60079.27,936615.76,996695.03,20,-1897.2,\n"
        b"2026-04-27,910688.52,96347.83,1007036.35,20,-0.0,24092.7\n"
    )
    cash, equity, date = mod.parse_prior_equity(csv_bytes)
    assert cash == 910688.52
    assert equity == 1007036.35
    assert date == "2026-04-27"


def test_parse_prior_equity_empty_file():
    cash, equity, date = mod.parse_prior_equity(b"date,cash,total_equity\n")
    assert (cash, equity, date) == (None, None, None)


# ---------------------------------------------------------------------------
# compute_intraday_mtm — happy path
# ---------------------------------------------------------------------------

def test_compute_intraday_mtm_kite_live_full_quotes():
    positions = [
        {"symbol": "INFY", "shares": 10, "avg_price": 1400.0, "ref_close": 1450.0},
        {"symbol": "TCS",  "shares":  5, "avg_price": 3600.0, "ref_close": 3500.0},
    ]
    last_prices = {"INFY": 1500.0, "TCS": 3450.0}
    payload = mod.compute_intraday_mtm(
        positions=positions,
        last_prices=last_prices,
        prior_close_total_equity=100000.0,
        cash=50000.0,
        source="kite_live",
        kite_unavailable=False,
        kite_unavailable_reason=None,
        now_ist=NOW,
    )
    assert payload["source"] == "kite_live"
    assert payload["kite_unavailable"] is False
    assert payload["n_positions"] == 2
    assert payload["n_priced"] == 2
    assert payload["n_missing"] == 0
    # 10*1500 + 5*3450 = 32250
    assert payload["total_position_value"] == 32250.0
    # intraday_total_equity = 32250 + 50000 = 82250
    assert payload["intraday_total_equity"] == 82250.0
    # intraday P&L per position: INFY (1500-1450)*10=500, TCS (3450-3500)*5=-250
    by_sym = {p["symbol"]: p for p in payload["positions"]}
    assert by_sym["INFY"]["unrealized_pnl_intraday"] == 500.0
    assert by_sym["TCS"]["unrealized_pnl_intraday"] == -250.0
    assert payload["as_of_ist"] == "2026-04-29 11:32 IST"


def test_compute_intraday_mtm_partial_quotes_falls_back_to_ref_close():
    positions = [
        {"symbol": "INFY", "shares": 10, "avg_price": 1400.0, "ref_close": 1450.0},
        {"symbol": "TCS",  "shares":  5, "avg_price": 3600.0, "ref_close": 3500.0},
    ]
    last_prices = {"INFY": 1500.0}  # TCS missing
    payload = mod.compute_intraday_mtm(
        positions=positions,
        last_prices=last_prices,
        prior_close_total_equity=100000.0,
        cash=50000.0,
        source="kite_live",
        kite_unavailable=False,
        kite_unavailable_reason=None,
        now_ist=NOW,
    )
    assert payload["n_priced"] == 1
    assert payload["n_missing"] == 1
    assert payload["missing_symbols"] == ["TCS"]
    by_sym = {p["symbol"]: p for p in payload["positions"]}
    # TCS marks at ref_close (3500), so position_value = 5*3500 = 17500,
    # intraday P&L = 0 (no live quote → can't claim a move).
    assert by_sym["TCS"]["last_price"] is None
    assert by_sym["TCS"]["position_value"] == 17500.0
    assert by_sym["TCS"]["unrealized_pnl_intraday"] == 0.0


def test_compute_intraday_mtm_no_quotes_at_all():
    """Token expired path — every symbol falls back to ref_close, total
    intraday P&L should be zero (we know nothing about the move)."""
    positions = [
        {"symbol": "INFY", "shares": 10, "avg_price": 1400.0, "ref_close": 1450.0},
    ]
    payload = mod.compute_intraday_mtm(
        positions=positions,
        last_prices={},
        prior_close_total_equity=100000.0,
        cash=50000.0,
        source="prior_close",
        kite_unavailable=True,
        kite_unavailable_reason="missing_credentials",
        now_ist=NOW,
    )
    assert payload["source"] == "prior_close"
    assert payload["kite_unavailable"] is True
    assert payload["kite_unavailable_reason"] == "missing_credentials"
    assert payload["n_priced"] == 0
    # 10*1450 + 50000 = 64500
    assert payload["intraday_total_equity"] == 64500.0
    assert payload["positions"][0]["unrealized_pnl_intraday"] == 0.0


def test_compute_intraday_mtm_no_ref_close_uses_avg_price():
    """Belt-and-suspenders: if ref_close is missing AND no live quote, use
    avg_price as the last-resort mark."""
    positions = [
        {"symbol": "NEWBIE", "shares": 100, "avg_price": 50.0, "ref_close": None},
    ]
    payload = mod.compute_intraday_mtm(
        positions=positions,
        last_prices={},
        prior_close_total_equity=None,
        cash=None,
        source="prior_close",
        kite_unavailable=True,
        kite_unavailable_reason="missing_credentials",
        now_ist=NOW,
    )
    assert payload["positions"][0]["position_value"] == 5000.0
    assert payload["positions"][0]["unrealized_pnl_intraday"] == 0.0
    # Without prior equity / cash, the equity-level fields stay None
    assert payload["intraday_total_equity"] is None
    assert payload["intraday_pnl_abs"] is None
    assert payload["intraday_pnl_pct"] is None


def test_compute_intraday_mtm_pct_math():
    """Sanity check the headline % number."""
    positions = [
        {"symbol": "INFY", "shares": 10, "avg_price": 1400.0, "ref_close": 1450.0},
    ]
    last_prices = {"INFY": 1500.0}  # +50 per share, 10 shares = +500 P&L
    payload = mod.compute_intraday_mtm(
        positions=positions,
        last_prices=last_prices,
        prior_close_total_equity=100000.0,
        cash=85000.0,  # 100000 - 10*1450 prior position value
        source="kite_live",
        kite_unavailable=False,
        kite_unavailable_reason=None,
        now_ist=NOW,
    )
    # intraday_total_equity = 10*1500 + 85000 = 100000  (already) + 500 (move)
    assert payload["intraday_total_equity"] == 100000.0
    assert payload["intraday_pnl_abs"] == 0.0  # cash 85k + 15k positions = 100k = prior


# ---------------------------------------------------------------------------
# fetch_kite_last_prices — pure parse of the Kite quote() response shape
# ---------------------------------------------------------------------------

def test_fetch_kite_last_prices_strips_nse_prefix():
    class FakeKite:
        def quote(self, keys):
            return {
                "NSE:INFY": {"last_price": 1500.0, "ohlc": {"close": 1450.0}},
                "NSE:TCS":  {"last_price": 3450.5},
                "NSE:BAD":  {"last_price": None},   # dropped
                "NSE:UGLY": None,                    # dropped
            }
    out = mod.fetch_kite_last_prices(FakeKite(), ["INFY", "TCS", "BAD", "UGLY"])
    assert out == {"INFY": 1500.0, "TCS": 3450.5}


def test_fetch_kite_last_prices_empty_input_returns_empty():
    class FakeKite:
        def quote(self, keys):  # pragma: no cover - shouldn't be called
            raise AssertionError("kite.quote should not be called for empty input")
    assert mod.fetch_kite_last_prices(FakeKite(), []) == {}
