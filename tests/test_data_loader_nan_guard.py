"""Tests for the NaN-OHLC guard in nse_data_loader.download_one.

Regression cover for the 2026-07-07 → 2026-08-07 outage: Yahoo began serving
the previous trading day's NSE bar with `volume` populated but
open/high/low/close null for ~36% of the universe at 08:00 IST. Those rows were
written to the per-ticker CSV verbatim, which advanced the qlib calendar to a
date holding a NaN close, which in turn tripped the 80% coverage gate in
nse_safety.check_data every weekday.

A date that exists only as NaN is strictly worse than a missing date: it makes
stale data look fresh to every downstream consumer. So the loader must drop
those rows before they ever reach disk.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "examples"))

import nse_data_loader as loader  # noqa: E402


def _yf_frame(rows):
    """Build a frame shaped like a real yfinance.download() response:
    DatetimeIndex named Date, title-cased price columns."""
    frame = pd.DataFrame(
        rows, columns=["Date", "Open", "High", "Low", "Close", "Volume"]
    )
    frame["Date"] = pd.to_datetime(frame["Date"])
    return frame.set_index("Date")


def _patch_yf(monkeypatch, frame):
    """Patch at the yfinance boundary so the real _yf_one runs — that is the
    seam the guard lives on."""
    import yfinance

    monkeypatch.setattr(yfinance, "download", lambda *_a, **_kw: frame.copy())


def test_row_with_all_ohlc_nan_is_dropped(monkeypatch, tmp_path):
    """The exact production shape: volume present, every price null."""
    _patch_yf(monkeypatch, _yf_frame([
        ["2026-08-05", 35885.0, 36280.0, 35605.0, 35805.0, 3173],
        ["2026-08-06", np.nan, np.nan, np.nan, np.nan, 4631],
    ]))

    symbol, n_bars, _exch = loader.download_one(
        "3MINDIA", "2026-08-01", "2026-08-07", tmp_path, incremental=True
    )

    written = pd.read_csv(tmp_path / "3MINDIA.csv")
    assert symbol == "3MINDIA"
    assert list(written["date"]) == ["2026-08-05"]
    assert n_bars == 1


def test_row_with_partial_ohlc_nan_is_dropped(monkeypatch, tmp_path):
    """A bar missing only `open` is still unusable for Alpha158."""
    _patch_yf(monkeypatch, _yf_frame([
        ["2026-08-05", 100.0, 105.0, 99.0, 104.0, 5000],
        ["2026-08-06", np.nan, 108.0, 101.0, 107.0, 6000],
    ]))

    _symbol, _n_bars, _exch = loader.download_one(
        "PARTIAL", "2026-08-01", "2026-08-07", tmp_path, incremental=True
    )

    written = pd.read_csv(tmp_path / "PARTIAL.csv")
    assert list(written["date"]) == ["2026-08-05"]


def test_zero_volume_row_with_valid_prices_is_kept(monkeypatch, tmp_path):
    """Illiquid microcaps legitimately print no volume — that is not junk."""
    _patch_yf(monkeypatch, _yf_frame([
        ["2026-08-05", 100.0, 105.0, 99.0, 104.0, 5000],
        ["2026-08-06", 104.0, 104.0, 104.0, 104.0, 0],
    ]))

    _symbol, _n_bars, _exch = loader.download_one(
        "ILLIQUID", "2026-08-01", "2026-08-07", tmp_path, incremental=True
    )

    written = pd.read_csv(tmp_path / "ILLIQUID.csv")
    assert list(written["date"]) == ["2026-08-05", "2026-08-06"]


def test_existing_good_row_is_not_clobbered_by_a_later_nan_row(monkeypatch, tmp_path):
    """The merge keeps `last` on duplicate dates. Without the guard, a NaN row
    arriving for a date we already hold good data for would destroy it."""
    csv_path = tmp_path / "RELIANCE.csv"
    pd.DataFrame({
        "date": ["2026-08-05", "2026-08-06"],
        "symbol": ["RELIANCE", "RELIANCE"],
        "open": [1293.0, 1285.0],
        "high": [1299.0, 1325.2],
        "low": [1270.1, 1281.2],
        "close": [1280.0, 1325.0],
        "volume": [24820782, 20342297],
        "factor": [1.0, 1.0],
    }).to_csv(csv_path, index=False)

    _patch_yf(monkeypatch, _yf_frame([
        ["2026-08-06", np.nan, np.nan, np.nan, np.nan, 20342297],
    ]))

    loader.download_one(
        "RELIANCE", "2026-08-01", "2026-08-07", tmp_path, incremental=True
    )

    written = pd.read_csv(csv_path)
    aug6 = written[written["date"] == "2026-08-06"].iloc[0]
    assert aug6["close"] == pytest.approx(1325.0)
    assert not pd.isna(aug6["open"])


def test_all_rows_nan_is_reported_as_empty_and_writes_nothing(monkeypatch, tmp_path):
    """A wholly-null response must not create a junk CSV."""
    _patch_yf(monkeypatch, _yf_frame([
        ["2026-08-06", np.nan, np.nan, np.nan, np.nan, 4631],
    ]))

    _symbol, n_bars, exch = loader.download_one(
        "ALLNAN", "2026-08-01", "2026-08-07", tmp_path, incremental=True
    )

    assert n_bars == 0
    assert exch is None
    assert not (tmp_path / "ALLNAN.csv").exists()


def test_all_rows_nan_leaves_a_pre_existing_csv_untouched(monkeypatch, tmp_path):
    """Losing today's bar must never cost us yesterday's history."""
    csv_path = tmp_path / "HISTORY.csv"
    original = pd.DataFrame({
        "date": ["2026-08-04", "2026-08-05"],
        "symbol": ["HISTORY", "HISTORY"],
        "open": [10.0, 11.0],
        "high": [12.0, 13.0],
        "low": [9.0, 10.0],
        "close": [11.0, 12.0],
        "volume": [100, 200],
        "factor": [1.0, 1.0],
    })
    original.to_csv(csv_path, index=False)

    _patch_yf(monkeypatch, _yf_frame([
        ["2026-08-06", np.nan, np.nan, np.nan, np.nan, 4631],
    ]))

    _symbol, n_bars, _exch = loader.download_one(
        "HISTORY", "2026-08-01", "2026-08-07", tmp_path, incremental=True
    )

    assert n_bars == 0
    pd.testing.assert_frame_equal(pd.read_csv(csv_path), original)
