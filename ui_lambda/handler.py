"""UI Lambda — serves an HTML page and JSON snapshots from the state bucket.

Routes (Function URL):
  GET /                    -> index.html
  GET /api/last_run        -> last_run.json
  GET /api/decisions       -> last 30 decision JSONs (newest first)
  GET /api/portfolio       -> current_portfolio.csv as JSON
  GET /api/equity          -> paper_equity.csv as JSON
  GET /api/halt            -> {halted: bool, reason: str|null}
  GET /api/alerts          -> tail of alerts.log
  GET /api/intraday_mtm    -> intraday_mtm.json (15-min Lambda refresh)
  GET /kite-login          -> 302 -> Zerodha OAuth login page
  GET /kite-callback       -> exchange ?request_token for an access_token,
                              persist into Secrets Manager, render success page
  GET /kite-status         -> {has_token, expires_at_ist, client_id} (no secrets)

Auth: the Function URL itself is the secret. The random subdomain
(~32 chars of entropy) gates access. Don't share or commit the URL.
"""

import csv
import datetime
import hashlib
import io
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import boto3


STATE_BUCKET = os.environ["STATE_BUCKET"]
KITE_SECRET_NAME = os.environ.get("KITE_SECRET_NAME", "nse-quant/kite")

s3 = boto3.client("s3")
secrets = boto3.client("secretsmanager")

INDEX_HTML = (Path(__file__).parent / "index.html").read_text()

# v2 redesign — separate file tree under ui_lambda/v2/. Loaded at module
# init so the Lambda doesn't read disk per request. Keys are URL paths
# without the /v2 prefix; values are (bytes, content_type).
_V2_DIR = Path(__file__).parent / "v2"
_V2_MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".jsx": "application/javascript; charset=utf-8",
}
V2_FILES: dict[str, tuple[bytes, str]] = {}
if _V2_DIR.is_dir():
    for _f in _V2_DIR.iterdir():
        if _f.is_file():
            V2_FILES[_f.name] = (
                _f.read_bytes(),
                _V2_MIME.get(_f.suffix.lower(), "application/octet-stream"),
            )


def _get_object(key: str) -> bytes | None:
    try:
        return s3.get_object(Bucket=STATE_BUCKET, Key=key)["Body"].read()
    except s3.exceptions.NoSuchKey:
        return None
    except s3.exceptions.ClientError as exc:
        if exc.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return None
        raise


def _list_keys(prefix: str) -> list[str]:
    keys: list[str] = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=STATE_BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []) or []:
            keys.append(obj["Key"])
    return keys


def _csv_to_rows(raw: bytes) -> list[dict]:
    text = raw.decode("utf-8")
    reader = csv.DictReader(io.StringIO(text))
    return list(reader)


def _resp(status: int, body, content_type: str = "application/json"):
    if isinstance(body, (dict, list)):
        body = json.dumps(body, default=str)
    return {
        "statusCode": status,
        "headers": {"content-type": content_type, "cache-control": "no-store"},
        "body": body,
    }


# ---------------------------------------------------------------------------
# Zerodha Kite Connect — OAuth callback + token storage
# ---------------------------------------------------------------------------

KITE_LOGIN_URL = "https://kite.zerodha.com/connect/login"
KITE_TOKEN_URL = "https://api.kite.trade/session/token"


def _kite_secret() -> dict:
    raw = secrets.get_secret_value(SecretId=KITE_SECRET_NAME)["SecretString"]
    return json.loads(raw)


def _kite_secret_put(payload: dict) -> None:
    secrets.put_secret_value(
        SecretId=KITE_SECRET_NAME,
        SecretString=json.dumps(payload),
    )


def _kite_exchange_token(api_key: str, api_secret: str, request_token: str) -> dict:
    """Trade `request_token` for an `access_token`. Per Kite Connect v3, the
    checksum is sha256(api_key + request_token + api_secret)."""
    checksum = hashlib.sha256(
        f"{api_key}{request_token}{api_secret}".encode("utf-8")
    ).hexdigest()
    body = urllib.parse.urlencode(
        {
            "api_key": api_key,
            "request_token": request_token,
            "checksum": checksum,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        KITE_TOKEN_URL,
        data=body,
        method="POST",
        headers={
            "X-Kite-Version": "3",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if payload.get("status") != "success":
        raise RuntimeError(f"Kite token exchange failed: {payload}")
    return payload["data"]


def _kite_quote(symbols: list[str]) -> dict:
    """Fetch live quotes from Kite Connect REST API directly (no SDK needed).

    Auth: `Authorization: token <api_key>:<access_token>`
    Doc: https://kite.trade/docs/connect/v3/market-quotes/

    Returns `{symbol: {last_price, ohlc, prev_close, change_pct, timestamp}}`.
    Symbols missing from the response are simply absent from the output.
    Caller is responsible for handling auth/network failures (raises on error).
    """
    if not symbols:
        return {}
    creds = _kite_secret()
    api_key = creds.get("api_key")
    access_token = creds.get("access_token")
    if not api_key or not access_token:
        raise RuntimeError("kite credentials missing")

    qs = urllib.parse.urlencode([("i", f"NSE:{s}") for s in symbols])
    url = f"https://api.kite.trade/quote?{qs}"
    req = urllib.request.Request(
        url,
        headers={
            "X-Kite-Version": "3",
            "Authorization": f"token {api_key}:{access_token}",
        },
    )
    with urllib.request.urlopen(req, timeout=8) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if payload.get("status") != "success":
        raise RuntimeError(f"kite quote failed: {payload.get('message') or payload}")

    out: dict = {}
    for key, q in (payload.get("data") or {}).items():
        sym = key.split(":", 1)[1] if ":" in key else key
        if not q:
            continue
        ohlc = q.get("ohlc") or {}
        prev_close = ohlc.get("close")
        last = q.get("last_price")
        change_pct = None
        if prev_close and last is not None:
            try:
                change_pct = (float(last) / float(prev_close) - 1) * 100.0
            except (TypeError, ValueError, ZeroDivisionError):
                change_pct = None
        out[sym] = {
            "last_price": last,
            "ohlc": {
                "open":  ohlc.get("open"),
                "high":  ohlc.get("high"),
                "low":   ohlc.get("low"),
                "close": ohlc.get("close"),  # this is prev close per Kite spec
            },
            "prev_close": prev_close,
            "change_pct": round(change_pct, 4) if change_pct is not None else None,
            "timestamp": q.get("timestamp"),
            "last_trade_time": q.get("last_trade_time"),
            "volume": q.get("volume"),
        }
    return out


def _kite_callback_html(client_id: str, set_at_ist: str, valid_until_ist: str) -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Kite token refreshed</title>
<style>
  body {{ font-family: ui-sans-serif, system-ui, -apple-system, sans-serif;
          background: #0c1418; color: #e2e8f0; margin: 0; padding: 60px 20px;
          display: flex; justify-content: center; }}
  .card {{ background: #111d22; border: 1px solid #1f2937; border-radius: 12px;
           padding: 32px; max-width: 520px; width: 100%; }}
  h1 {{ margin: 0 0 8px; font-size: 22px; color: #6ee7b7; }}
  .muted {{ color: #94a3b8; font-size: 13px; }}
  .row {{ margin: 14px 0; }}
  code {{ background: #0c1418; padding: 2px 6px; border-radius: 4px; }}
  a {{ color: #60a5fa; }}
</style>
</head><body><div class="card">
<h1>✓ Kite access token refreshed</h1>
<div class="muted">Token persisted to AWS Secrets Manager. Today's cron will use it.</div>
<div class="row">Client ID: <code>{client_id or '—'}</code></div>
<div class="row">Stored at: <code>{set_at_ist}</code></div>
<div class="row">Valid until: <code>{valid_until_ist}</code> (next 06:00 IST)</div>
<div class="row"><a href="/">← Back to dashboard</a></div>
</div></body></html>"""


def _next_kite_expiry_ist(now_utc: datetime.datetime) -> datetime.datetime:
    """Zerodha invalidates all access tokens at 06:00 IST every day."""
    ist = now_utc + datetime.timedelta(hours=5, minutes=30)
    expiry_ist = ist.replace(hour=6, minute=0, second=0, microsecond=0)
    if ist >= expiry_ist:
        expiry_ist += datetime.timedelta(days=1)
    return expiry_ist


def _parse_query(event) -> dict[str, str]:
    raw = event.get("rawQueryString") or ""
    return {
        k: v[0] if isinstance(v, list) else v
        for k, v in urllib.parse.parse_qs(raw).items()
    }


def _handle_kite_login() -> dict:
    creds = _kite_secret()
    api_key = creds.get("api_key", "").strip()
    if not api_key:
        return _resp(503, {"error": "kite api_key not configured in secret"})
    target = f"{KITE_LOGIN_URL}?api_key={urllib.parse.quote(api_key)}&v=3"
    return {
        "statusCode": 302,
        "headers": {"location": target, "cache-control": "no-store"},
        "body": "",
    }


def _handle_kite_callback(event) -> dict:
    qs = _parse_query(event)
    request_token = qs.get("request_token", "").strip()
    status = qs.get("status", "").strip()
    if status and status != "success":
        return _resp(400, {"error": f"login flow returned status={status!r}"})
    if not request_token:
        return _resp(400, {"error": "missing request_token query param"})

    creds = _kite_secret()
    api_key = creds.get("api_key", "").strip()
    api_secret = creds.get("api_secret", "").strip()
    if not api_key or not api_secret:
        return _resp(503, {"error": "kite api_key/api_secret not configured in secret"})

    try:
        data = _kite_exchange_token(api_key, api_secret, request_token)
    except Exception as exc:  # noqa: BLE001
        return _resp(502, {"error": f"token exchange failed: {exc}"})

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    set_at_ist = (now_utc + datetime.timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d %H:%M:%S IST")
    valid_until_ist = _next_kite_expiry_ist(now_utc).strftime("%Y-%m-%d %H:%M IST")

    payload = dict(creds)
    payload["access_token"] = data["access_token"]
    payload["public_token"] = data.get("public_token", "")
    payload["client_id"] = data.get("user_id") or creds.get("client_id", "")
    payload["access_token_set_at"] = now_utc.isoformat()
    payload["access_token_expires_at_ist"] = valid_until_ist
    _kite_secret_put(payload)

    return _resp(
        200,
        _kite_callback_html(payload["client_id"], set_at_ist, valid_until_ist),
        content_type="text/html; charset=utf-8",
    )


def _handle_kite_status() -> dict:
    creds = _kite_secret()
    has_token = bool(creds.get("access_token"))
    return _resp(
        200,
        {
            "has_token": has_token,
            "client_id": creds.get("client_id") or None,
            "access_token_set_at": creds.get("access_token_set_at") or None,
            "access_token_expires_at_ist": creds.get("access_token_expires_at_ist") or None,
            "api_key_configured": bool(creds.get("api_key")),
        },
    )


def handler(event, context):
    request_context = event.get("requestContext", {})
    method = request_context.get("http", {}).get("method", "GET")
    path = request_context.get("http", {}).get("path", "/")

    if method != "GET":
        return _resp(405, {"error": "method not allowed"})

    if path == "/" or path == "/index.html":
        return _resp(200, INDEX_HTML, content_type="text/html; charset=utf-8")

    # v2 redesign — opt-in URL. Real data only, fields not yet wired
    # render as small "wiring pending" chips rather than mocks.
    if path == "/v2" or path == "/v2/":
        rec = V2_FILES.get("index.html")
        if rec is None:
            return _resp(404, {"error": "v2 not deployed"})
        body, ctype = rec
        return _resp(200, body.decode("utf-8"), content_type=ctype)
    if path.startswith("/v2/"):
        fname = path[len("/v2/"):]
        rec = V2_FILES.get(fname)
        if rec is None:
            return _resp(404, {"error": f"v2 asset not found: {fname}"})
        body, ctype = rec
        return _resp(200, body.decode("utf-8"), content_type=ctype)

    if path == "/kite-login":
        return _handle_kite_login()
    if path == "/kite-callback":
        return _handle_kite_callback(event)
    if path == "/kite-status":
        return _handle_kite_status()

    if not path.startswith("/api/"):
        return _resp(404, {"error": "not found"})

    if path == "/api/last_run":
        raw = _get_object("outputs/last_run.json")
        if raw is None:
            return _resp(200, {"never_run": True})
        return _resp(200, json.loads(raw))

    if path == "/api/decisions":
        keys = sorted(
            (k for k in _list_keys("outputs/decisions/") if k.endswith(".json")),
            reverse=True,
        )[:30]
        out = []
        for key in keys:
            raw = _get_object(key)
            if raw is None:
                continue
            try:
                out.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
        return _resp(200, out)

    if path == "/api/portfolio":
        raw = _get_object("outputs/current_portfolio.csv")
        if raw is None:
            return _resp(200, [])
        return _resp(200, _csv_to_rows(raw))

    if path == "/api/equity":
        raw = _get_object("outputs/paper_equity.csv")
        if raw is None:
            return _resp(200, [])
        return _resp(200, _csv_to_rows(raw))

    if path == "/api/halt":
        raw = _get_object("outputs/HALT")
        if raw is None:
            return _resp(200, {"halted": False, "reason": None})
        return _resp(200, {"halted": True, "reason": raw.decode("utf-8").strip()})

    if path == "/api/paper_trade_clock":
        raw = _get_object("outputs/paper_trade_progress.json")
        if raw is None:
            return _resp(200, {"never_run": True})
        return _resp(200, json.loads(raw))

    if path == "/api/intraday_mtm":
        raw = _get_object("outputs/intraday_mtm.json")
        if raw is None:
            return _resp(200, {"never_run": True})
        return _resp(200, json.loads(raw))

    if path == "/api/alerts":
        raw = _get_object("outputs/alerts.log")
        if raw is None:
            return _resp(200, {"lines": []})
        lines = raw.decode("utf-8", errors="replace").splitlines()[-50:]
        return _resp(200, {"lines": lines})

    if path.startswith("/api/trades/"):
        sym = path[len("/api/trades/"):].strip().upper()
        if not sym:
            return _resp(400, {"error": "symbol required"})
        raw = _get_object("outputs/trade_log.csv")
        if raw is None:
            return _resp(200, [])
        rows = [r for r in _csv_to_rows(raw) if (r.get("symbol") or "").upper() == sym]
        return _resp(200, rows)

    if path == "/api/kite_quote":
        qs = _parse_query(event)
        raw_syms = (qs.get("symbols") or "").strip()
        if not raw_syms:
            return _resp(400, {"error": "symbols query param required, e.g. ?symbols=INFY,RELIANCE"})
        symbols = [s.strip().upper() for s in raw_syms.split(",") if s.strip()]
        if not symbols:
            return _resp(400, {"error": "no valid symbols"})
        if len(symbols) > 100:
            return _resp(400, {"error": "symbols limit is 100 per call"})
        try:
            quotes = _kite_quote(symbols)
        except urllib.error.HTTPError as exc:
            return _resp(502, {"error": "kite_http_error", "status": exc.code,
                               "detail": exc.reason})
        except Exception as exc:
            return _resp(502, {"error": "kite_quote_failed",
                               "detail": f"{type(exc).__name__}: {exc}"})
        return _resp(200, {
            "as_of": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "symbols": quotes,
            "missing": [s for s in symbols if s not in quotes],
        })

    if path.startswith("/api/rank_history/"):
        sym = path[len("/api/rank_history/"):].strip().upper()
        if not sym:
            return _resp(400, {"error": "symbol required"})
        raw = _get_object(f"outputs/rank_history/{sym}.json")
        if raw is None:
            return _resp(200, [])
        try:
            return _resp(200, json.loads(raw))
        except json.JSONDecodeError:
            return _resp(200, [])

    # ---- methodology / honest-caveat artefacts -----------------------------
    if path == "/api/stratified":
        raw = _get_object("outputs/stratified_stats.json")
        return _resp(200, json.loads(raw) if raw else {})

    if path == "/api/cost_sensitivity":
        raw = _get_object("outputs/cost_sensitivity.json")
        return _resp(200, json.loads(raw) if raw else {})

    if path == "/api/survivorship":
        raw = _get_object("outputs/survivorship_estimate.json")
        return _resp(200, json.loads(raw) if raw else {})

    if path == "/api/outage":
        raw = _get_object("outputs/outage_monte_carlo.json")
        return _resp(200, json.loads(raw) if raw else {})

    if path == "/api/regime":
        raw = _get_object("outputs/regime.json")
        return _resp(200, json.loads(raw) if raw else None)

    if path == "/api/shap_today":
        raw = _get_object("outputs/shap_today.json")
        return _resp(200, json.loads(raw) if raw else None)

    if path == "/api/peers_today":
        raw = _get_object("outputs/peers_today.json")
        return _resp(200, json.loads(raw) if raw else None)

    if path == "/api/hit_rates":
        raw = _get_object("outputs/hit_rates.json")
        return _resp(200, json.loads(raw) if raw else None)

    return _resp(404, {"error": "not found"})
