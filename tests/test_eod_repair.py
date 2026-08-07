"""Tests for nse_eod_repair — the NSE Bhavcopy patch layer.

Second line of defence for the 2026-07 Yahoo outage. Layer 1 (the NaN guard in
nse_data_loader) stops junk reaching disk, but on its own it leaves the newest
session missing entirely, so decisions run a day stale. This module fills that
session from NSE's own official end-of-day file.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "examples"))

import nse_eod_repair as mod  # noqa: E402


OLD_HEADER = (
    "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,"
    "TOTTRDQTY,TOTTRDVAL,TIMESTAMP,TOTALTRADES,ISIN,\n"
)
NEW_HEADER = (
    "TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,"
    "OpnPric,HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,TtlTradgVol\n"
)


def _write_old_format(path: Path, rows):
    with path.open("w") as f:
        f.write(OLD_HEADER)
        for sym, series, o, h, low, c, vol in rows:
            f.write(
                f"{sym},{series},{o},{h},{low},{c},{c},{c},"
                f"{vol},1000000,06-AUG-2026,500,INE000A01001,\n"
            )


def _write_new_format(path: Path, rows):
    with path.open("w") as f:
        f.write(NEW_HEADER)
        for sym, series, o, h, low, c, vol in rows:
            f.write(
                f"2026-08-06,2026-08-06,CM,NSE,STK,1234,INE000A01001,{sym},{series},"
                f"{o},{h},{low},{c},{c},{c},{vol}\n"
            )


def _write_ticker_csv(csv_dir: Path, symbol: str, rows):
    frame = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
    frame["symbol"] = symbol
    frame["factor"] = 1.0
    frame = frame[["date", "symbol", "open", "high", "low", "close", "volume", "factor"]]
    frame.to_csv(csv_dir / f"{symbol}.csv", index=False)


# ---------------------------------------------------------------------------
# parse_bhavcopy_ohlc
# ---------------------------------------------------------------------------

def test_parses_old_format(tmp_path):
    path = tmp_path / "cm06AUG2026bhav.csv"
    _write_old_format(path, [("RELIANCE", "EQ", 1285.0, 1325.2, 1281.2, 1325.0, 20342297)])

    bars = mod.parse_bhavcopy_ohlc(path)

    assert bars["RELIANCE"] == pytest.approx(
        {"open": 1285.0, "high": 1325.2, "low": 1281.2, "close": 1325.0, "volume": 20342297.0}
    )


def test_parses_new_format(tmp_path):
    path = tmp_path / "BhavCopy_NSE_CM_0_0_0_20260806_F_0000.csv"
    _write_new_format(path, [("TCS", "EQ", 2417.0, 2434.5, 2368.5, 2373.0, 2729141)])

    bars = mod.parse_bhavcopy_ohlc(path)

    assert bars["TCS"]["close"] == pytest.approx(2373.0)
    assert bars["TCS"]["volume"] == pytest.approx(2729141.0)


def test_skips_series_outside_keep_list(tmp_path):
    """Only cash-segment equity series feed the ranker."""
    path = tmp_path / "cm06AUG2026bhav.csv"
    _write_old_format(path, [
        ("GOODNAME", "EQ", 10.0, 11.0, 9.0, 10.5, 1000),
        ("SOMEBOND", "N1", 100.0, 101.0, 99.0, 100.5, 50),
    ])

    bars = mod.parse_bhavcopy_ohlc(path)

    assert "GOODNAME" in bars
    assert "SOMEBOND" not in bars


def test_skips_rows_with_unparseable_prices(tmp_path):
    path = tmp_path / "cm06AUG2026bhav.csv"
    _write_old_format(path, [("BADROW", "EQ", "-", "-", "-", "-", 0)])

    assert mod.parse_bhavcopy_ohlc(path) == {}


# ---------------------------------------------------------------------------
# repair_csv_dir
# ---------------------------------------------------------------------------

def test_inserts_missing_target_date(tmp_path):
    _write_ticker_csv(tmp_path, "RELIANCE", [
        ["2026-08-05", 1293.0, 1299.0, 1270.1, 1280.0, 24820782],
    ])
    bars = {"RELIANCE": {"open": 1285.0, "high": 1325.2, "low": 1281.2,
                         "close": 1325.0, "volume": 20342297.0}}

    summary = mod.repair_csv_dir(tmp_path, "2026-08-06", bars, verbose=False)

    written = pd.read_csv(tmp_path / "RELIANCE.csv")
    assert list(written["date"]) == ["2026-08-05", "2026-08-06"]
    assert written.iloc[-1]["close"] == pytest.approx(1325.0)
    assert summary["patched"] == 1


def test_replaces_existing_nan_row(tmp_path):
    """Belt and braces — if a NaN row somehow survived, overwrite it."""
    _write_ticker_csv(tmp_path, "3MINDIA", [
        ["2026-08-05", 35885.0, 36280.0, 35605.0, 35805.0, 3173],
        ["2026-08-06", float("nan"), float("nan"), float("nan"), float("nan"), 4631],
    ])
    bars = {"3MINDIA": {"open": 35805.0, "high": 36595.0, "low": 35710.0,
                        "close": 36000.0, "volume": 4631.0}}

    summary = mod.repair_csv_dir(tmp_path, "2026-08-06", bars, verbose=False)

    written = pd.read_csv(tmp_path / "3MINDIA.csv")
    assert len(written) == 2
    assert written.iloc[-1]["close"] == pytest.approx(36000.0)
    assert summary["patched"] == 1


def test_leaves_good_existing_row_untouched(tmp_path):
    """Yahoo's adjusted price wins when it is present and valid — we only fill
    holes, never overwrite good data with unadjusted Bhavcopy prices."""
    _write_ticker_csv(tmp_path, "TCS", [
        ["2026-08-06", 2417.0, 2434.5, 2368.5, 2373.0, 2729141],
    ])
    bars = {"TCS": {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}}

    summary = mod.repair_csv_dir(tmp_path, "2026-08-06", bars, verbose=False)

    written = pd.read_csv(tmp_path / "TCS.csv")
    assert written.iloc[-1]["close"] == pytest.approx(2373.0)
    assert summary["patched"] == 0
    assert summary["already_ok"] == 1


def test_symbol_absent_from_bhavcopy_is_counted_not_fatal(tmp_path):
    _write_ticker_csv(tmp_path, "DELISTED", [
        ["2026-08-05", 10.0, 11.0, 9.0, 10.5, 100],
    ])

    summary = mod.repair_csv_dir(tmp_path, "2026-08-06", {}, verbose=False)

    written = pd.read_csv(tmp_path / "DELISTED.csv")
    assert list(written["date"]) == ["2026-08-05"]
    assert summary["patched"] == 0
    assert summary["unavailable"] == 1


def test_patched_rows_stay_sorted_and_deduped(tmp_path):
    """The patch must land in date order even if the source rows are not, and
    must replace the NaN row rather than sit alongside it."""
    _write_ticker_csv(tmp_path, "SORTME", [
        ["2026-08-04", 1.0, 2.0, 0.5, 1.5, 10],
        ["2026-08-06", float("nan"), float("nan"), float("nan"), float("nan"), 30],
        ["2026-08-05", 2.0, 3.0, 1.5, 2.5, 20],
    ])
    bars = {"SORTME": {"open": 9.0, "high": 9.0, "low": 9.0, "close": 9.0, "volume": 90.0}}

    summary = mod.repair_csv_dir(tmp_path, "2026-08-06", bars, verbose=False)

    written = pd.read_csv(tmp_path / "SORTME.csv")
    assert list(written["date"]) == ["2026-08-04", "2026-08-05", "2026-08-06"]
    assert len(written) == 3
    assert written.iloc[-1]["close"] == pytest.approx(9.0)
    assert summary["patched"] == 1


def test_preserves_symbol_and_factor_columns(tmp_path):
    _write_ticker_csv(tmp_path, "COLCHECK", [
        ["2026-08-05", 1.0, 2.0, 0.5, 1.5, 10],
    ])
    bars = {"COLCHECK": {"open": 2.0, "high": 3.0, "low": 1.0, "close": 2.5, "volume": 20.0}}

    mod.repair_csv_dir(tmp_path, "2026-08-06", bars, verbose=False)

    written = pd.read_csv(tmp_path / "COLCHECK.csv")
    assert list(written.columns) == [
        "date", "symbol", "open", "high", "low", "close", "volume", "factor"
    ]
    assert written.iloc[-1]["symbol"] == "COLCHECK"
    assert written.iloc[-1]["factor"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# find_cached_bhavcopy
# ---------------------------------------------------------------------------

def test_finds_cached_file_for_date_either_format(tmp_path):
    year_dir = tmp_path / "2026"
    year_dir.mkdir()
    (year_dir / "cm06AUG2026bhav.csv").write_text(OLD_HEADER)

    found = mod.find_cached_bhavcopy(tmp_path, "2026-08-06")

    assert found is not None and found.name == "cm06AUG2026bhav.csv"


def test_returns_none_when_date_not_cached(tmp_path):
    (tmp_path / "2026").mkdir()

    assert mod.find_cached_bhavcopy(tmp_path, "2026-08-06") is None
