import pathlib

import pytest

from options.underlying import (AdjustedCloseStore, historical_volatility,
                                rsi14, spot_for_symbol)

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
QLIB_ROOT = REPO_ROOT / "data" / "qlib_data" / "in_data"


def _row(kind, expiry, settle, underlying_close=None):
    return {"date": "2020-02-03", "symbol": "X", "kind": kind, "expiry": expiry,
            "strike": 0.0, "close": settle, "settle": settle, "oi": 10,
            "volume": 5, "underlying_close": underlying_close, "lot_size": None}


def test_spot_prefers_underlying_close():
    rows = [_row("CE", "2020-02-27", 25.0, underlying_close=1406.2),
            _row("FUT", "2020-02-27", 1420.55)]
    assert spot_for_symbol(rows) == 1406.2


def test_spot_falls_back_to_nearest_fut():
    rows = [_row("CE", "2020-02-27", 25.0),
            _row("FUT", "2020-03-26", 1432.10),
            _row("FUT", "2020-02-27", 1420.55)]
    assert spot_for_symbol(rows) == 1420.55


def test_spot_none_when_no_reference():
    assert spot_for_symbol([_row("CE", "2020-02-27", 25.0)]) is None


def test_rsi14_all_gains_is_100():
    closes = [100.0 + step for step in range(20)]
    assert rsi14(closes) == pytest.approx(100.0)


def test_rsi14_symmetric_alternation_is_50():
    closes = [100.0]
    for step in range(20):
        closes.append(closes[-1] + (1.0 if step % 2 == 0 else -1.0))
    assert rsi14(closes) == pytest.approx(50.0, abs=1.0)


def test_rsi14_insufficient_returns_none():
    assert rsi14([100.0] * 14) is None


def test_hv_of_constant_series_is_zero():
    assert historical_volatility([500.0] * 40) == pytest.approx(0.0)


def test_hv_insufficient_returns_none():
    assert historical_volatility([500.0] * 10) is None


def test_adjusted_close_store_reads_real_reliance():
    store = AdjustedCloseStore(QLIB_ROOT)
    closes = store.closes_upto("RELIANCE", "2026-08-10")
    assert closes, "reliance series should exist in the qlib store"
    assert closes[-1] == pytest.approx(1327.3, abs=0.1)


def test_adjusted_close_store_missing_symbol_returns_empty():
    store = AdjustedCloseStore(QLIB_ROOT)
    assert store.closes_upto("NOSUCHSYM", "2026-08-10") == []
