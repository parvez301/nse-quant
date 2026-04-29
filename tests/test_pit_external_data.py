"""Tests for nse_pit_external_data — the paid-data adapter shell.

Today the EOD Historical Data adapter is stub-only. We test:
  * NoOpAdapter is always available and returns []
  * EOD adapter without an API key is unavailable, returns [] gracefully
  * EOD adapter with a key is "available" but stubbed (raises NotImplementedError
    on actual fetch — by design until the user wires the real call)
  * get_adapter() routes by name and rejects unknowns
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "examples"))

import nse_pit_external_data as mod


def test_noop_is_always_available_and_returns_empty():
    a = mod.NoOpAdapter()
    assert a.is_available() is True
    assert a.list_delisted_tickers(2008, 2024) == []


def test_eod_unavailable_without_api_key(monkeypatch):
    monkeypatch.delenv("EOD_HISTORICAL_API_KEY", raising=False)
    a = mod.EODHistoricalDataAdapter()
    assert a.is_available() is False
    # Calling list_delisted on an unavailable adapter must NOT crash;
    # it returns [] with a stderr warning so cron jobs stay green.
    assert a.list_delisted_tickers(2008, 2024) == []


def test_eod_available_when_api_key_set(monkeypatch):
    monkeypatch.setenv("EOD_HISTORICAL_API_KEY", "test-key-stub")
    a = mod.EODHistoricalDataAdapter()
    assert a.is_available() is True
    # Still stubbed — fetching raises until the user wires real requests.get()
    with pytest.raises(NotImplementedError):
        a.list_delisted_tickers(2008, 2024)


def test_eod_explicit_api_key_overrides_env(monkeypatch):
    monkeypatch.delenv("EOD_HISTORICAL_API_KEY", raising=False)
    a = mod.EODHistoricalDataAdapter(api_key="explicit")
    assert a.is_available() is True


def test_get_adapter_known_provider_returns_instance():
    assert isinstance(mod.get_adapter("no-op"), mod.NoOpAdapter)
    assert isinstance(mod.get_adapter("eod-historical"), mod.EODHistoricalDataAdapter)
    assert isinstance(mod.get_adapter("nse-bhavcopy"), mod.NSEBhavcopyAdapter)


def test_get_adapter_unknown_provider_raises():
    with pytest.raises(ValueError):
        mod.get_adapter("nonexistent")


# ---------------------------------------------------------------------------
# NSEBhavcopyAdapter
# ---------------------------------------------------------------------------

def test_bhavcopy_unavailable_when_cache_missing(tmp_path):
    a = mod.NSEBhavcopyAdapter(cache_dir=tmp_path / "no-such-dir")
    assert a.is_available() is False
    # Must NOT crash when cache absent — same graceful pattern as EOD.
    assert a.list_delisted_tickers(2008, 2024) == []


def test_bhavcopy_unavailable_when_cache_empty(tmp_path):
    (tmp_path / "2024").mkdir()  # year dir but no CSVs inside
    a = mod.NSEBhavcopyAdapter(cache_dir=tmp_path)
    assert a.is_available() is False
    assert a.list_delisted_tickers(2008, 2024) == []


def test_bhavcopy_available_with_partial_cache(tmp_path):
    """Even one CSV in one year dir is enough to flag the cache as 'usable';
    the math layer can still produce a partial result."""
    (tmp_path / "2024").mkdir()
    (tmp_path / "2024" / "BhavCopy_NSE_CM_0_0_0_20241231_F_0000.csv").write_text(
        "SYMBOL,SERIES\nINFY,EQ\n"
    )
    a = mod.NSEBhavcopyAdapter(cache_dir=tmp_path)
    assert a.is_available() is True
    # Real ingestion runs end-to-end now. The single-day case has no
    # delisted candidates (last_seen == last_cache_date for every symbol).
    assert a.list_delisted_tickers(2008, 2024) == []


def test_date_from_bhavcopy_filename_old_format():
    assert mod._date_from_bhavcopy_filename("cm02JAN2024bhav.csv") == "2024-01-02"
    assert mod._date_from_bhavcopy_filename("cm31DEC2008bhav.csv") == "2008-12-31"
    assert mod._date_from_bhavcopy_filename("CM01jul2015bhav.CSV") == "2015-07-01"


def test_date_from_bhavcopy_filename_new_format():
    assert (
        mod._date_from_bhavcopy_filename("BhavCopy_NSE_CM_0_0_0_20241231_F_0000.csv")
        == "2024-12-31"
    )
    assert (
        mod._date_from_bhavcopy_filename("BhavCopy_NSE_CM_0_0_0_20240801_F_0000.csv")
        == "2024-08-01"
    )


def test_date_from_bhavcopy_filename_returns_none_for_garbage():
    assert mod._date_from_bhavcopy_filename("README.csv") is None
    assert mod._date_from_bhavcopy_filename("cmXXXXXXXX.csv") is None
    assert mod._date_from_bhavcopy_filename("") is None


def _write_bhav_csv(path, rows: list[tuple[str, str]]):
    """Helper — writes an old-format Bhavcopy with just SYMBOL/SERIES and
    enough trailing columns to satisfy the parser's column lookup."""
    lines = [" SYMBOL, SERIES, DATE1, PREV_CLOSE, CLOSE_PRICE"]
    for sym, series in rows:
        lines.append(f"{sym}, {series}, 02-Jan-2024, 100.0, 101.0")
    path.write_text("\n".join(lines) + "\n")


def test_bhavcopy_finds_delisted_when_symbol_disappears(tmp_path):
    """Multi-day cache: INFY trades all year, GONECO stops appearing in
    Feb. With the default 30-day staleness buffer and a Dec 31 'today',
    GONECO should show up as a candidate; INFY should not."""
    year_dir = tmp_path / "2024"
    year_dir.mkdir()
    # Jan 2 — both trade
    _write_bhav_csv(year_dir / "cm02JAN2024bhav.csv", [("INFY", "EQ"), ("GONECO", "EQ")])
    # Feb 1 — both still trade
    _write_bhav_csv(year_dir / "cm01FEB2024bhav.csv", [("INFY", "EQ"), ("GONECO", "EQ")])
    # Dec 30 — only INFY (GONECO disappeared mid-year)
    _write_bhav_csv(year_dir / "cm30DEC2024bhav.csv", [("INFY", "EQ")])
    a = mod.NSEBhavcopyAdapter(cache_dir=tmp_path)
    candidates = a.list_delisted_tickers(2024, 2024)
    syms = [c["ticker"] for c in candidates]
    assert "GONECO" in syms
    assert "INFY" not in syms
    g = next(c for c in candidates if c["ticker"] == "GONECO")
    assert g["first_date"] == "2024-01-02"
    assert g["last_date"] == "2024-02-01"
    assert g["staleness_days"] == (
        __import__("datetime").date(2024, 12, 30)
        - __import__("datetime").date(2024, 2, 1)
    ).days
    assert g["exit_event"] == "bhavcopy_disappeared"


def test_bhavcopy_skips_non_equity_series(tmp_path):
    """GS series rows (govt securities) and MF (mutual funds) shouldn't
    pollute the candidate list."""
    year_dir = tmp_path / "2024"
    year_dir.mkdir()
    _write_bhav_csv(year_dir / "cm02JAN2024bhav.csv", [
        ("INFY", "EQ"), ("GSEC10Y", "GS"), ("FRANKLIN", "MF"),
    ])
    _write_bhav_csv(year_dir / "cm30DEC2024bhav.csv", [("INFY", "EQ")])
    a = mod.NSEBhavcopyAdapter(cache_dir=tmp_path)
    candidates = a.list_delisted_tickers(2024, 2024)
    syms = {c["ticker"] for c in candidates}
    assert "GSEC10Y" not in syms
    assert "FRANKLIN" not in syms


def test_bhavcopy_staleness_buffer_suppresses_recent_disappearances(tmp_path):
    """A symbol that stopped trading <30 days before the cache end date is
    NOT a candidate — could be a holiday gap, suspension, or T2T move."""
    year_dir = tmp_path / "2024"
    year_dir.mkdir()
    _write_bhav_csv(year_dir / "cm02JAN2024bhav.csv", [("INFY", "EQ"), ("RECENT", "EQ")])
    _write_bhav_csv(year_dir / "cm15DEC2024bhav.csv", [("INFY", "EQ"), ("RECENT", "EQ")])
    _write_bhav_csv(year_dir / "cm30DEC2024bhav.csv", [("INFY", "EQ")])
    # RECENT last seen Dec 15, cache end Dec 30 → 15-day staleness < 30
    a = mod.NSEBhavcopyAdapter(cache_dir=tmp_path)
    syms = {c["ticker"] for c in a.list_delisted_tickers(2024, 2024)}
    assert "RECENT" not in syms


def test_bhavcopy_iter_cache_files_filters_by_year(tmp_path):
    """The pure walker is testable today even though full ingestion isn't."""
    for y in (2007, 2008, 2015, 2024, 2025):
        d = tmp_path / str(y)
        d.mkdir()
        (d / f"cm{y}.csv").write_text("SYMBOL\nFOO\n")
    # Also a non-numeric subdir we should ignore
    (tmp_path / "junk").mkdir()
    (tmp_path / "junk" / "ignored.csv").write_text("nope")
    a = mod.NSEBhavcopyAdapter(cache_dir=tmp_path)
    yrs = sorted({y for y, _ in a._iter_cache_files(2008, 2024)})
    assert yrs == [2008, 2015, 2024]


def test_bhavcopy_default_cache_dir_is_relative_repo_path():
    """Sanity: when no override, the adapter resolves to data/bhavcopy/ which
    is the documented project location."""
    a = mod.NSEBhavcopyAdapter()
    assert a.cache_dir == Path("data/bhavcopy")
