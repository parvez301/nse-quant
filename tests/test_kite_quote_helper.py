"""Tests for the new ui_lambda /api/kite_quote helper.

Stubs the secrets manager + urllib.request.urlopen to avoid live dependencies.
Covers happy path, bad creds, network failure, and the change_pct edge cases.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_REPO = Path(__file__).resolve().parent.parent


def _load_handler():
    os.environ.setdefault("STATE_BUCKET", "test")
    os.environ.setdefault("KITE_SECRET_NAME", "test/kite")
    sys.path.insert(0, str(_REPO / "ui_lambda"))
    spec = importlib.util.spec_from_file_location(
        "ui_handler_under_test", _REPO / "ui_lambda" / "handler.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def handler_module():
    return _load_handler()


def _fake_response(payload):
    body = json.dumps(payload).encode("utf-8")
    fp = io.BytesIO(body)
    resp = MagicMock()
    resp.__enter__ = lambda self: fp
    resp.__exit__ = lambda self, *_a: None
    resp.read = fp.read
    return resp


def test_kite_quote_happy_path(handler_module):
    payload = {
        "status": "success",
        "data": {
            "NSE:INFY": {
                "last_price": 1500.0,
                "ohlc": {"open": 1490, "high": 1510, "low": 1485, "close": 1480},
                "timestamp": "2026-04-29 14:00:00",
                "last_trade_time": "2026-04-29 14:00:01",
                "volume": 1234567,
            }
        }
    }
    with patch.object(handler_module, "_kite_secret",
                      return_value={"api_key": "k", "access_token": "t"}), \
         patch.object(handler_module.urllib.request, "urlopen",
                      return_value=_fake_response(payload)):
        out = handler_module._kite_quote(["INFY"])

    assert "INFY" in out
    quote = out["INFY"]
    assert quote["last_price"] == 1500.0
    assert quote["prev_close"] == 1480
    # change vs prev close = (1500/1480 - 1)*100 = 1.3514...
    assert abs(quote["change_pct"] - 1.3514) < 0.001
    assert quote["volume"] == 1234567


def test_kite_quote_handles_zero_prev_close(handler_module):
    payload = {
        "status": "success",
        "data": {
            "NSE:NEW": {
                "last_price": 100.0,
                "ohlc": {"open": 0, "high": 0, "low": 0, "close": 0},
            }
        }
    }
    with patch.object(handler_module, "_kite_secret",
                      return_value={"api_key": "k", "access_token": "t"}), \
         patch.object(handler_module.urllib.request, "urlopen",
                      return_value=_fake_response(payload)):
        out = handler_module._kite_quote(["NEW"])
    assert out["NEW"]["change_pct"] is None  # zero prev avoids div-by-zero


def test_kite_quote_missing_creds_raises(handler_module):
    with patch.object(handler_module, "_kite_secret", return_value={}):
        with pytest.raises(RuntimeError, match="kite credentials missing"):
            handler_module._kite_quote(["INFY"])


def test_kite_quote_empty_symbol_list_returns_empty(handler_module):
    """Should never call Kite for an empty list (saves an API hit)."""
    with patch.object(handler_module, "_kite_secret") as m:
        out = handler_module._kite_quote([])
    assert out == {}
    m.assert_not_called()


def test_kite_quote_propagates_failure_status(handler_module):
    payload = {"status": "error", "message": "invalid token"}
    with patch.object(handler_module, "_kite_secret",
                      return_value={"api_key": "k", "access_token": "t"}), \
         patch.object(handler_module.urllib.request, "urlopen",
                      return_value=_fake_response(payload)):
        with pytest.raises(RuntimeError, match="invalid token"):
            handler_module._kite_quote(["INFY"])


def test_kite_quote_skips_null_quote_entries(handler_module):
    """When Kite returns a null body for a symbol (e.g. delisted), skip it."""
    payload = {
        "status": "success",
        "data": {
            "NSE:GOOD": {
                "last_price": 100.0,
                "ohlc": {"open": 99, "high": 101, "low": 98, "close": 99},
            },
            "NSE:DEAD": None,
        }
    }
    with patch.object(handler_module, "_kite_secret",
                      return_value={"api_key": "k", "access_token": "t"}), \
         patch.object(handler_module.urllib.request, "urlopen",
                      return_value=_fake_response(payload)):
        out = handler_module._kite_quote(["GOOD", "DEAD"])
    assert "GOOD" in out
    assert "DEAD" not in out
