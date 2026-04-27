"""Tests for the analytics Lambda handler (boto3 + pyarrow flavor).

Routing + input-validation are unit-tested with S3 stubbed.
End-to-end query path is smoke-tested against local Parquet (skipped if absent).
"""
import io
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

# Set env BEFORE importing handler (it reads STATE_BUCKET at import time)
os.environ["STATE_BUCKET"] = "test-bucket"
os.environ["ANALYTICS_PREFIX"] = "outputs/analytics"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "analytics_lambda"))

import handler as mod


def _evt(path: str, qs: dict | None = None, method: str = "GET"):
    return {
        "requestContext": {"http": {"method": method, "path": path}},
        "queryStringParameters": qs or {},
    }


def _reset_caches():
    mod._LIST_CACHE.clear()
    mod._TABLE_CACHE.clear()
    mod._SYMBOLS_CACHE = None
    mod._CACHE_VERSION = None
    mod._FEATURES_TODAY_CACHE = None
    mod._MODEL_CACHE = None


# -----------------------------------------------------------------------------
# Validation helpers
# -----------------------------------------------------------------------------

def test_safe_symbol_accepts_normal_tickers():
    assert mod._safe_symbol("INFY") == "INFY"
    assert mod._safe_symbol("M&M") == "M&M"
    assert mod._safe_symbol("BAJAJ-AUTO") == "BAJAJ-AUTO"
    assert mod._safe_symbol("3MINDIA") == "3MINDIA"


def test_safe_symbol_rejects_injection():
    assert mod._safe_symbol("INFY' OR 1=1") is None
    assert mod._safe_symbol("INFY;DROP TABLE") is None
    assert mod._safe_symbol("") is None
    assert mod._safe_symbol(None) is None
    assert mod._safe_symbol("X" * 100) is None


def test_safe_date_validates_format():
    assert mod._safe_date("2024-01-15") == "2024-01-15"
    assert mod._safe_date("not-a-date") is None
    assert mod._safe_date("2024/01/15") is None
    assert mod._safe_date(None) is None


def test_year_from_key_extracts_partition():
    assert mod._year_from_key("outputs/analytics/prices/year=2024/data.parquet") == 2024
    assert mod._year_from_key("no-year-here.parquet") is None


def test_years_in_range_filters_correctly():
    keys = [
        "outputs/analytics/prices/year=2020/data.parquet",
        "outputs/analytics/prices/year=2024/data.parquet",
        "outputs/analytics/prices/year=2025/data.parquet",
    ]
    assert mod._years_in_range(keys, "2024-06-01", "2025-06-01") == keys[1:]
    assert mod._years_in_range(keys, None, None) == keys
    assert mod._years_in_range(keys, "2026-01-01", None) == []


# -----------------------------------------------------------------------------
# Routing
# -----------------------------------------------------------------------------

def test_handler_rejects_non_get():
    out = mod.handler(_evt("/api/analytics/symbols", method="POST"), None)
    assert out["statusCode"] == 405


def test_handler_unknown_path_returns_404():
    out = mod.handler(_evt("/api/analytics/nope"), None)
    assert out["statusCode"] == 404


def test_handler_timeseries_missing_symbol_400():
    out = mod.handler(_evt("/api/analytics/timeseries", qs={}), None)
    assert out["statusCode"] == 400


def test_handler_attribution_missing_symbol_400():
    out = mod.handler(_evt("/api/analytics/attribution", qs={}), None)
    assert out["statusCode"] == 400


def test_handler_attribution_invalid_symbol_400():
    out = mod.handler(_evt("/api/analytics/attribution",
                           qs={"symbol": "X' OR 1=1"}), None)
    assert out["statusCode"] == 400


def test_handler_attribution_clamps_top_n():
    """top_n must be coerced into [1, 50]."""
    captured = {}
    def fake(symbol, top_n):
        captured["top_n"] = top_n
        return {"symbol": symbol, "top_contributors": []}
    with patch.object(mod, "attribution", side_effect=fake):
        mod.handler(_evt("/api/analytics/attribution",
                         qs={"symbol": "INFY", "top_n": "9999"}), None)
        assert captured["top_n"] == 50
        mod.handler(_evt("/api/analytics/attribution",
                         qs={"symbol": "INFY", "top_n": "0"}), None)
        assert captured["top_n"] == 1
        mod.handler(_evt("/api/analytics/attribution",
                         qs={"symbol": "INFY", "top_n": "garbage"}), None)
        assert captured["top_n"] == 10  # default fallback


def test_handler_timeseries_invalid_symbol_400():
    out = mod.handler(_evt("/api/analytics/timeseries", qs={"symbol": "X' OR 1=1"}), None)
    assert out["statusCode"] == 400


def test_handler_strips_either_prefix():
    """/api/analytics/symbols and /api/symbols both reach the same handler."""
    with patch.object(mod, "list_symbols", return_value=[{"symbol": "AAA"}]):
        a = mod.handler(_evt("/api/analytics/symbols"), None)
        b = mod.handler(_evt("/api/symbols"), None)
    assert a["statusCode"] == 200
    assert json.loads(a["body"]) == json.loads(b["body"])


def test_handler_500_on_internal_error():
    with patch.object(mod, "list_symbols", side_effect=RuntimeError("boom")):
        out = mod.handler(_evt("/api/analytics/symbols"), None)
    assert out["statusCode"] == 500
    assert "boom" in json.loads(out["body"])["detail"]


# -----------------------------------------------------------------------------
# Real local-Parquet smoke test (skipped if ETL hasn't been run)
# -----------------------------------------------------------------------------

class _FakeS3:
    """Minimal S3 client that reads from local files."""
    def __init__(self, root: Path):
        self.root = root
        self.exceptions = MagicMock()

    def get_object(self, Bucket, Key):
        path = self.root / Key
        return {"Body": io.BytesIO(path.read_bytes())}

    def get_paginator(self, _):
        keys = sorted(
            str(p.relative_to(self.root))
            for p in self.root.rglob("*.parquet")
        )

        class _Pager:
            def paginate(self, Bucket, Prefix):
                yield {"Contents": [{"Key": k} for k in keys if k.startswith(Prefix)]}
        return _Pager()


def test_real_query_against_local_parquet(tmp_path: Path):
    """Use the real Parquet exports (if present) end-to-end."""
    repo_root = Path(__file__).resolve().parent.parent
    pq_root = repo_root  # S3 keys are prefixed with `outputs/`, so root = repo
    if not (repo_root / "outputs" / "analytics" / "prices").exists():
        return  # ETL hasn't run yet — skip silently

    _reset_caches()
    fake = _FakeS3(pq_root)
    with patch.object(mod, "_S3", fake):
        symbols = mod.list_symbols()
        assert len(symbols) > 100
        assert all({"symbol", "first_date", "last_date", "n_bars"} <= set(s.keys())
                   for s in symbols)

        target = symbols[0]["symbol"]
        out = mod.timeseries(target, "2024-01-01", "2024-06-30")
        assert out["symbol"] == target
        assert out["n_bars"] > 0
        first = out["rows"][0]
        assert {"date", "open", "high", "low", "close", "volume",
                "adv20", "score"} == set(first.keys())


def test_timeseries_returns_empty_for_unknown_symbol(tmp_path: Path):
    """If the symbol doesn't exist in any partition, return n_bars=0."""
    repo_root = Path(__file__).resolve().parent.parent
    pq_root = repo_root  # S3 keys are prefixed with `outputs/`, so root = repo
    if not (repo_root / "outputs" / "analytics" / "prices").exists():
        return
    _reset_caches()
    fake = _FakeS3(pq_root)
    with patch.object(mod, "_S3", fake):
        out = mod.timeseries("NOSUCH-SYM", "2024-01-01", "2024-12-31")
    assert out == {"symbol": "NOSUCH-SYM", "n_bars": 0, "rows": []}


def test_list_symbols_uses_precomputed_index(tmp_path: Path):
    """If symbols.json exists, list_symbols should read it and skip the scan."""
    idx_path = tmp_path / "outputs/analytics/symbols.json"
    idx_path.parent.mkdir(parents=True, exist_ok=True)
    idx = [
        {"symbol": "ZZZ", "first_date": "2020-01-01",
         "last_date": "2024-01-01", "n_bars": 1000},
    ]
    import json as _json
    idx_path.write_text(_json.dumps(idx))

    _reset_caches()
    fake = _FakeS3(tmp_path)
    with patch.object(mod, "_S3", fake):
        out = mod.list_symbols()
    assert out == idx  # exact passthrough — no partition scan needed


def test_cache_version_invalidates_on_manifest_change(tmp_path: Path):
    """Bumping the manifest version must clear the symbols + table caches."""
    idx_path = tmp_path / "outputs/analytics/symbols.json"
    idx_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = tmp_path / "outputs/analytics/manifest.json"

    import json as _json
    idx_path.write_text(_json.dumps([{"symbol": "AAA", "first_date": "2020-01-01",
                                      "last_date": "2024-01-01", "n_bars": 5}]))
    manifest_path.write_text(_json.dumps({"generated_at": "2026-01-01T00:00:00Z",
                                          "prices_last_date": "2026-01-01"}))

    _reset_caches()
    fake = _FakeS3(tmp_path)
    with patch.object(mod, "_S3", fake):
        # First call populates the cache + version
        first = mod.handler(_evt("/api/analytics/symbols"), None)
        assert mod._SYMBOLS_CACHE is not None
        assert mod._CACHE_VERSION and "2026-01-01T00:00:00Z" in mod._CACHE_VERSION

        # Second call with same manifest → cache survives
        cached_ref = mod._SYMBOLS_CACHE
        mod.handler(_evt("/api/analytics/symbols"), None)
        assert mod._SYMBOLS_CACHE is cached_ref

        # Bump manifest → cache clears on next request
        manifest_path.write_text(_json.dumps({"generated_at": "2026-01-02T00:00:00Z",
                                              "prices_last_date": "2026-01-02"}))
        idx_path.write_text(_json.dumps([{"symbol": "BBB", "first_date": "2021-01-01",
                                          "last_date": "2026-01-02", "n_bars": 9}]))
        out = mod.handler(_evt("/api/analytics/symbols"), None)
        assert _json.loads(out["body"])[0]["symbol"] == "BBB"
        assert "2026-01-02T00:00:00Z" in mod._CACHE_VERSION


def test_attribution_returns_top_contributors_against_real_artefacts(tmp_path: Path):
    """End-to-end SHAP attribution using the real features_today.parquet +
    model_booster.txt produced by the local ETL."""
    repo_root = Path(__file__).resolve().parent.parent
    if not (repo_root / "outputs" / "analytics" / "features_today.parquet").exists():
        return
    if not (repo_root / "outputs" / "analytics" / "model_booster.txt").exists():
        return
    try:
        import lightgbm  # noqa: F401
    except ImportError:
        return

    _reset_caches()
    fake = _FakeS3(repo_root)
    with patch.object(mod, "_S3", fake):
        # Pick the first symbol present in the features parquet
        features = mod._load_features_today()
        sym = features.column("symbol").to_pylist()[0]
        out = mod.attribution(sym, top_n=5)

    assert out["symbol"] == sym
    assert "top_contributors" in out
    assert len(out["top_contributors"]) == 5
    # Each contributor has the expected shape
    for c in out["top_contributors"]:
        assert {"feature", "value", "contribution"} == set(c.keys())
    # Contributors are sorted by absolute contribution descending
    contribs = [abs(c["contribution"]) for c in out["top_contributors"]]
    assert contribs == sorted(contribs, reverse=True)


def test_attribution_unknown_symbol_returns_explainable_error(tmp_path: Path):
    repo_root = Path(__file__).resolve().parent.parent
    if not (repo_root / "outputs" / "analytics" / "features_today.parquet").exists():
        return
    _reset_caches()
    fake = _FakeS3(repo_root)
    with patch.object(mod, "_S3", fake):
        out = mod.attribution("NOSUCH", top_n=5)
    assert out["symbol"] == "NOSUCH"
    assert "not in today's BUY/HOLD/SELL universe" in out["error"]


def test_timeseries_synthetic_partition(tmp_path: Path):
    """End-to-end with a tiny in-memory synthetic Parquet — no real ETL needed."""
    # Build a one-year, two-symbol prices parquet
    prices = pd.DataFrame({
        "symbol": ["AAA", "AAA", "BBB"],
        "date": pd.to_datetime(["2024-06-01", "2024-06-02", "2024-06-01"]),
        "open": [1.0, 2.0, 3.0],
        "high": [1.5, 2.5, 3.5],
        "low": [0.5, 1.5, 2.5],
        "close": [1.2, 2.2, 3.2],
        "volume": [100.0, 200.0, 300.0],
        "factor": [1.0, 1.0, 1.0],
        "adv20": [1000.0, 1100.0, None],
    })
    scores = pd.DataFrame({
        "symbol": ["AAA"],
        "date": pd.to_datetime(["2024-06-01"]),
        "score": [0.42],
    })

    px_path = tmp_path / "outputs/analytics/prices/year=2024/data.parquet"
    sc_path = tmp_path / "outputs/analytics/scores/year=2024/data.parquet"
    px_path.parent.mkdir(parents=True, exist_ok=True)
    sc_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pandas(prices), px_path)
    pq.write_table(pa.Table.from_pandas(scores), sc_path)

    _reset_caches()
    fake = _FakeS3(tmp_path)
    with patch.object(mod, "_S3", fake):
        symbols = mod.list_symbols()
        sym_set = {s["symbol"] for s in symbols}
        assert sym_set == {"AAA", "BBB"}

        out = mod.timeseries("AAA", "2024-01-01", "2024-12-31")
        assert out["n_bars"] == 2
        # First row: score joins; second row: no score in pred → null
        assert out["rows"][0]["score"] == 0.42
        assert out["rows"][1]["score"] is None
        assert out["rows"][0]["close"] == 1.2
