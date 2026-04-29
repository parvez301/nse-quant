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
    (tmp_path / "2024" / "BhavCopy_NSE_CM_0_0_0_20241231_F_0000.csv").write_text("SYMBOL,SERIES\nINFY,EQ\n")
    a = mod.NSEBhavcopyAdapter(cache_dir=tmp_path)
    assert a.is_available() is True
    # Real ingestion is shell-only — calling .list_delisted_tickers must
    # raise NotImplementedError so an over-eager caller doesn't get an empty
    # answer that LOOKS like a clean miss.
    with pytest.raises(NotImplementedError):
        a.list_delisted_tickers(2008, 2024)


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
