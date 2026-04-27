"""Analytics Lambda — boto3 (runtime) + pyarrow on partitioned Parquet.

Reads `s3://$STATE_BUCKET/outputs/analytics/{prices,scores}/year=YYYY/data.parquet`
and serves JSON for the Symbol Explorer UI.

Routes (mounted at `/api/analytics/*` via CloudFront in front of the Function URL):
  GET /api/analytics/symbols                                -> list of symbols + bar counts
  GET /api/analytics/timeseries?symbol=X&start=YYYY-MM-DD&end=YYYY-MM-DD
       -> per-date OHLCV + score for one symbol

We deliberately do NOT bundle pandas or boto3:
  * boto3 ships with the Lambda Python 3.12 runtime (~free)
  * pandas would push the package over the 250 MB unzipped limit; pyarrow
    alone covers the filter/join we need
"""
from __future__ import annotations

import io
import json
import os
import re
from typing import Any

# Install the scipy.sparse stub BEFORE anything imports lightgbm — saves us
# the 113 MB real scipy dependency. See scipy_stub.py for the rationale.
import scipy_stub
scipy_stub.install()

import boto3
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq


STATE_BUCKET = os.environ["STATE_BUCKET"]
ANALYTICS_PREFIX = os.environ.get("ANALYTICS_PREFIX", "outputs/analytics")
BOOSTER_KEY = os.environ.get("BOOSTER_KEY", f"{ANALYTICS_PREFIX}/model_booster.txt")
FEATURES_TODAY_KEY = f"{ANALYTICS_PREFIX}/features_today.parquet"

_S3 = boto3.client("s3")
_SYMBOL_RE = re.compile(r"^[A-Za-z0-9_.&-]{1,32}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# All caches are keyed by the manifest version so a new ETL run invalidates
# them on the very next request — no Lambda restart required.
_MANIFEST_KEY = f"{ANALYTICS_PREFIX}/manifest.json"
_SYMBOLS_KEY  = f"{ANALYTICS_PREFIX}/symbols.json"
_CACHE_VERSION: str | None = None
_LIST_CACHE: dict[str, list[str]] = {}
_TABLE_CACHE: dict[str, pa.Table] = {}
_SYMBOLS_CACHE: list[dict] | None = None
_MODEL_CACHE = None         # qlib LGBModel (lazily loaded)
_FEATURES_TODAY_CACHE = None  # pa.Table


def _current_manifest_version() -> str:
    """Return a stable version string for the analytics dataset.
    Cheap call (~1 ms): a single S3 GET of a few hundred bytes.
    """
    try:
        body = _S3.get_object(Bucket=STATE_BUCKET, Key=_MANIFEST_KEY)["Body"].read()
        m = json.loads(body)
        return f"{m.get('generated_at')}|{m.get('prices_last_date')}"
    except Exception:
        # If the manifest is missing (first deploy before ETL), fall back to
        # a constant — the cache will be live for the cold-start lifetime.
        return "no-manifest"


def _check_cache_version():
    """Clear all caches if the manifest version has changed since last call."""
    global _CACHE_VERSION, _LIST_CACHE, _TABLE_CACHE, _SYMBOLS_CACHE, _FEATURES_TODAY_CACHE
    v = _current_manifest_version()
    if v != _CACHE_VERSION:
        _LIST_CACHE = {}
        _TABLE_CACHE = {}
        _SYMBOLS_CACHE = None
        _FEATURES_TODAY_CACHE = None  # daily features change with each cron
        # The model itself is rarely retrained, so we DON'T clear _MODEL_CACHE.
        _CACHE_VERSION = v


def _list_partitions(kind: str) -> list[str]:
    if kind in _LIST_CACHE:
        return _LIST_CACHE[kind]
    keys: list[str] = []
    paginator = _S3.get_paginator("list_objects_v2")
    prefix = f"{ANALYTICS_PREFIX}/{kind}/"
    for page in paginator.paginate(Bucket=STATE_BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []) or []:
            if obj["Key"].endswith(".parquet"):
                keys.append(obj["Key"])
    keys.sort()
    _LIST_CACHE[kind] = keys
    return keys


def _year_from_key(key: str) -> int | None:
    m = re.search(r"year=(\d{4})", key)
    return int(m.group(1)) if m else None


def _read_partition(key: str) -> pa.Table:
    if key in _TABLE_CACHE:
        return _TABLE_CACHE[key]
    body = _S3.get_object(Bucket=STATE_BUCKET, Key=key)["Body"].read()
    table = pq.read_table(io.BytesIO(body))
    _TABLE_CACHE[key] = table
    return table


def _resp(status: int, body: Any, content_type: str = "application/json"):
    if isinstance(body, (dict, list)):
        body = json.dumps(body, default=str)
    return {
        "statusCode": status,
        "headers": {"content-type": content_type, "cache-control": "no-store"},
        "body": body,
    }


def _safe_symbol(s: str | None) -> str | None:
    if not s:
        return None
    return s if _SYMBOL_RE.match(s) else None


def _safe_date(d: str | None) -> str | None:
    if not d:
        return None
    return d if _DATE_RE.match(d) else None


def _years_in_range(keys: list[str], start: str | None, end: str | None) -> list[str]:
    if not start and not end:
        return keys
    s_yr = int(start[:4]) if start else 0
    e_yr = int(end[:4]) if end else 9999
    return [k for k in keys if (y := _year_from_key(k)) is not None and s_yr <= y <= e_yr]


def list_symbols() -> list[dict]:
    """Return per-symbol first/last bar + count.
    Reads the precomputed `symbols.json` index in one tiny S3 GET (~50 KB).
    Falls back to a full partition scan only if the index file is missing.
    """
    global _SYMBOLS_CACHE
    if _SYMBOLS_CACHE is not None:
        return _SYMBOLS_CACHE
    try:
        body = _S3.get_object(Bucket=STATE_BUCKET, Key=_SYMBOLS_KEY)["Body"].read()
        _SYMBOLS_CACHE = json.loads(body)
        return _SYMBOLS_CACHE
    except Exception as exc:
        # If the index file genuinely doesn't exist yet, fall back to the
        # full partition scan. Anything else is a real failure — re-raise.
        msg = str(exc)
        if "NoSuchKey" not in msg and "404" not in msg and "no such file" not in msg.lower():
            raise
    # ---- fallback: scan every prices partition (slow path) ------------------
    keys = _list_partitions("prices")
    if not keys:
        _SYMBOLS_CACHE = []
        return _SYMBOLS_CACHE
    agg: dict[str, dict] = {}
    for k in keys:
        table = _read_partition(k).select(["symbol", "date"])
        symbols = table.column("symbol").to_pylist()
        dates = table.column("date").to_pylist()
        for sym, d in zip(symbols, dates):
            entry = agg.setdefault(sym, {"first": None, "last": None, "n": 0})
            if entry["first"] is None or d < entry["first"]:
                entry["first"] = d
            if entry["last"] is None or d > entry["last"]:
                entry["last"] = d
            entry["n"] += 1
    _SYMBOLS_CACHE = [
        {
            "symbol": sym,
            "first_date": str(v["first"].date() if hasattr(v["first"], "date") else v["first"]),
            "last_date":  str(v["last"].date()  if hasattr(v["last"],  "date") else v["last"]),
            "n_bars": v["n"],
        }
        for sym, v in sorted(agg.items())
    ]
    return _SYMBOLS_CACHE


def _to_date_scalar(s: str, like_col: pa.ChunkedArray) -> pa.Scalar:
    """Cast YYYY-MM-DD string to a scalar of the same type as `like_col`."""
    target_type = like_col.type
    # pa.scalar(str, timestamp_type) is rejected; build via cast from string
    return pa.scalar(s).cast(target_type)


def _filter_table(table: pa.Table, symbol: str,
                  start: str | None, end: str | None) -> pa.Table:
    """Apply (symbol, date-range) filter using pyarrow.compute."""
    expr = pc.equal(table.column("symbol"), symbol)
    date_col = table.column("date")
    if start:
        expr = pc.and_(expr, pc.greater_equal(
            date_col, _to_date_scalar(start, date_col)
        ))
    if end:
        expr = pc.and_(expr, pc.less_equal(
            date_col, _to_date_scalar(end, date_col)
        ))
    return table.filter(expr)


def timeseries(symbol: str, start: str | None, end: str | None) -> dict:
    """Return per-date OHLCV + score for one symbol."""
    price_keys = _years_in_range(_list_partitions("prices"), start, end)
    score_keys = _years_in_range(_list_partitions("scores"), start, end)

    px_parts = []
    for k in price_keys:
        filt = _filter_table(_read_partition(k), symbol, start, end)
        if filt.num_rows:
            px_parts.append(filt)
    if not px_parts:
        return {"symbol": symbol, "n_bars": 0, "rows": []}
    px = pa.concat_tables(px_parts).sort_by("date")

    # Build a date -> score lookup from the score partitions (score data only
    # spans 2024+, so most early dates are intentionally null)
    score_by_date: dict = {}
    for k in score_keys:
        filt = _filter_table(_read_partition(k), symbol, start, end)
        for d, s in zip(filt.column("date").to_pylist(),
                        filt.column("score").to_pylist()):
            score_by_date[d] = s

    rows = []
    cols = {n: px.column(n).to_pylist() for n in px.column_names}
    n = px.num_rows
    for i in range(n):
        d = cols["date"][i]
        rows.append({
            "date": str(d.date() if hasattr(d, "date") else d),
            "open":  cols["open"][i],
            "high":  cols["high"][i],
            "low":   cols["low"][i],
            "close": cols["close"][i],
            "volume": cols["volume"][i],
            "adv20": cols.get("adv20", [None] * n)[i],
            "score": score_by_date.get(d),
        })
    return {"symbol": symbol, "n_bars": n, "rows": rows}


def _load_features_today() -> pa.Table | None:
    """Read the features_today.parquet snapshot (one row per symbol)."""
    global _FEATURES_TODAY_CACHE
    if _FEATURES_TODAY_CACHE is not None:
        return _FEATURES_TODAY_CACHE
    try:
        body = _S3.get_object(Bucket=STATE_BUCKET, Key=FEATURES_TODAY_KEY)["Body"].read()
        _FEATURES_TODAY_CACHE = pq.read_table(io.BytesIO(body))
        return _FEATURES_TODAY_CACHE
    except Exception as exc:
        if "NoSuchKey" not in str(exc) and "404" not in str(exc):
            raise
        return None


def _load_model():
    """Lazy-load the LightGBM Booster from its native text format.
    Stored as text so the Lambda doesn't need qlib to unpickle the wrapper.
    Cached across warm invocations.
    """
    global _MODEL_CACHE
    if _MODEL_CACHE is not None:
        return _MODEL_CACHE
    import lightgbm as lgb
    body = _S3.get_object(Bucket=STATE_BUCKET, Key=BOOSTER_KEY)["Body"].read()
    # lightgbm.Booster takes a model_file path; write to /tmp first
    path = "/tmp/model_booster.txt"
    with open(path, "wb") as f:
        f.write(body)
    _MODEL_CACHE = lgb.Booster(model_file=path)
    return _MODEL_CACHE


def attribution(symbol: str, top_n: int = 10) -> dict:
    """Return the top-N Alpha158 features pushing the model's score for
    `symbol` up or down on today's date, using LightGBM's pred_contrib SHAP.
    """
    table = _load_features_today()
    if table is None:
        return {"error": "features_today.parquet not yet generated"}
    # Filter to one row for this symbol
    expr = pc.equal(table.column("symbol"), symbol)
    row = table.filter(expr)
    if row.num_rows == 0:
        return {
            "symbol": symbol,
            "error": "symbol not in today's BUY/HOLD/SELL universe",
        }
    feature_cols = [c for c in row.column_names if c not in ("date", "symbol")]
    feat_values = [row.column(c).to_pylist()[0] for c in feature_cols]

    booster = _load_model()  # already a lightgbm.Booster (text-format load)

    import numpy as np
    X = np.array([feat_values], dtype=float)
    # pred_contrib returns shape (n_rows, n_features + 1) — last column is bias
    contrib = booster.predict(X, pred_contrib=True)[0]
    bias = float(contrib[-1])
    contribs = contrib[:-1]

    # Pair (feature_name, value, contribution); sort by absolute contribution
    pairs = [
        {
            "feature": feature_cols[i],
            "value": float(feat_values[i]) if feat_values[i] is not None else None,
            "contribution": float(contribs[i]),
        }
        for i in range(len(feature_cols))
    ]
    pairs.sort(key=lambda p: abs(p["contribution"]), reverse=True)
    top = pairs[:top_n]
    return {
        "symbol": symbol,
        "as_of": str(row.column("date").to_pylist()[0])[:10],
        "score": float(sum(contribs) + bias),
        "bias": bias,
        "top_contributors": top,
        "n_features_used": len(feature_cols),
    }


def handler(event, _context):
    request_context = event.get("requestContext", {})
    method = request_context.get("http", {}).get("method", "GET")
    path = request_context.get("http", {}).get("path", "/")
    qs = event.get("queryStringParameters") or {}

    if method != "GET":
        return _resp(405, {"error": "method not allowed"})

    # Cheap freshness check — clears caches if the ETL has run since the
    # last invocation. ~1 ms S3 GET against a few-hundred-byte object.
    try:
        _check_cache_version()
    except Exception:
        # If the freshness check itself fails (transient S3 hiccup), keep
        # serving stale rather than 500ing.
        pass

    sub = path
    for prefix in ("/api/analytics", "/api"):
        if sub.startswith(prefix):
            sub = sub[len(prefix):] or "/"
            break

    if sub in ("/", "/symbols"):
        try:
            return _resp(200, list_symbols())
        except Exception as exc:
            return _resp(500, {"error": "symbol list failed", "detail": str(exc)})

    if sub == "/timeseries":
        symbol = _safe_symbol(qs.get("symbol"))
        if not symbol:
            return _resp(400, {"error": "symbol required (alnum + _.&-, ≤32 chars)"})
        start = _safe_date(qs.get("start"))
        end = _safe_date(qs.get("end"))
        try:
            return _resp(200, timeseries(symbol, start, end))
        except Exception as exc:
            return _resp(500, {"error": "timeseries query failed", "detail": str(exc)})

    if sub == "/attribution":
        symbol = _safe_symbol(qs.get("symbol"))
        if not symbol:
            return _resp(400, {"error": "symbol required"})
        try:
            top_n = int(qs.get("top_n", "10"))
        except (TypeError, ValueError):
            top_n = 10
        top_n = max(1, min(top_n, 50))
        try:
            return _resp(200, attribution(symbol, top_n=top_n))
        except Exception as exc:
            return _resp(500, {"error": "attribution failed", "detail": str(exc)})

    return _resp(404, {"error": "not found", "path": path, "sub": sub})
