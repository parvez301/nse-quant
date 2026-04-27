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


def test_get_adapter_unknown_provider_raises():
    with pytest.raises(ValueError):
        mod.get_adapter("nonexistent")
