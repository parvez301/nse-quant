"""Intraday mark-to-market Lambda — refreshes the paper portfolio's MTM
every 15 minutes during NSE market hours by pulling live last-prices from
Kite Connect.

Output: outputs/intraday_mtm.json (single small file, ~5 KB) with:

  {
    "as_of_ist":              "2026-04-29 11:32 IST",
    "as_of_utc":              "2026-04-29T06:02:00+00:00",
    "source":                 "kite_live" | "prior_close",
    "kite_unavailable":       false,
    "kite_unavailable_reason": null,
    "n_positions":            20,
    "n_priced":               20,
    "n_missing":              0,
    "missing_symbols":        [],
    "total_position_value":   952341.18,
    "prior_close_total_equity": 1007036.35,
    "cash":                   60079.27,
    "intraday_total_equity":  1012420.45,
    "intraday_pnl_abs":       5384.10,
    "intraday_pnl_pct":       0.5346,
    "positions":              [{symbol, shares, avg_price, ref_close,
                                last_price, position_value,
                                unrealized_pnl_intraday}, ...]
  }

Triggered by EventBridge every 15 min Mon-Fri 03:45-09:45 UTC
(= 09:15-15:15 IST), plus one fire at 10:00 UTC for the 15:30 IST close
print. ~26 fires/day, well under free tier.

If the Kite token is missing or rejected, the Lambda still writes the file
with `source="prior_close"` + `kite_unavailable=true` so the dashboard can
render a "token expired — re-login" pill instead of going dark. Same
graceful-skip pattern as nse_live_ic / nse_shadow_execute.
"""

import csv
import datetime
import io
import json
import os
from typing import Any

import boto3


STATE_BUCKET = os.environ["STATE_BUCKET"]
KITE_SECRET_NAME = os.environ["KITE_SECRET_NAME"]
PORTFOLIO_KEY = os.environ.get("PORTFOLIO_KEY", "outputs/current_portfolio.csv")
EQUITY_KEY = os.environ.get("EQUITY_KEY", "outputs/paper_equity.csv")
OUTPUT_KEY = os.environ.get("OUTPUT_KEY", "outputs/intraday_mtm.json")

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


# ---------------------------------------------------------------------------
# Pure helpers — unit-testable without AWS / Kite
# ---------------------------------------------------------------------------

def parse_portfolio(csv_bytes: bytes) -> list[dict]:
    """Parse current_portfolio.csv into a list of position dicts.

    Required columns: symbol, shares, avg_price.
    Optional columns: last_price (used as ref_close fallback),
    position_value, unrealized_pnl, bought_on, marked_on.
    """
    reader = csv.DictReader(io.StringIO(csv_bytes.decode("utf-8")))
    positions = []
    for row in reader:
        sym = (row.get("symbol") or "").strip()
        if not sym:
            continue
        try:
            shares = float(row["shares"])
            avg_price = float(row["avg_price"])
        except (KeyError, ValueError, TypeError):
            continue
        ref_close = _parse_optional_float(row.get("last_price"))
        positions.append({
            "symbol": sym,
            "shares": shares,
            "avg_price": avg_price,
            "ref_close": ref_close,
        })
    return positions


def _parse_optional_float(s: Any) -> float | None:
    if s is None or s == "":
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def parse_prior_equity(csv_bytes: bytes) -> tuple[float | None, float | None, str | None]:
    """Pull (cash, total_equity, date) from the LAST row of paper_equity.csv.

    Returns (None, None, None) if the file is empty or malformed.
    """
    reader = csv.DictReader(io.StringIO(csv_bytes.decode("utf-8")))
    last = None
    for row in reader:
        last = row
    if last is None:
        return (None, None, None)
    return (
        _parse_optional_float(last.get("cash")),
        _parse_optional_float(last.get("total_equity")),
        (last.get("date") or "").strip() or None,
    )


def compute_intraday_mtm(
    positions: list[dict],
    last_prices: dict[str, float],
    prior_close_total_equity: float | None,
    cash: float | None,
    *,
    source: str,
    kite_unavailable: bool,
    kite_unavailable_reason: str | None,
    now_ist: datetime.datetime,
) -> dict:
    """Build the intraday_mtm.json payload.

    For symbols missing from last_prices we fall back to ref_close (yesterday's
    close from the portfolio CSV) — those positions contribute zero intraday
    P&L but still show up in n_positions so the dashboard math stays
    consistent with the paper portfolio it's mirroring.
    """
    rows = []
    missing = []
    total_position_value = 0.0
    n_priced = 0

    for p in positions:
        sym = p["symbol"]
        live = last_prices.get(sym)
        ref = p.get("ref_close")
        if live is not None:
            n_priced += 1
            mark = live
        elif ref is not None:
            missing.append(sym)
            mark = ref
        else:
            missing.append(sym)
            mark = p["avg_price"]  # last-resort: cost basis

        position_value = mark * p["shares"]
        intraday_pnl = (
            (mark - ref) * p["shares"] if ref is not None and live is not None else 0.0
        )
        total_position_value += position_value
        rows.append({
            "symbol": sym,
            "shares": p["shares"],
            "avg_price": p["avg_price"],
            "ref_close": ref,
            "last_price": live,
            "position_value": round(position_value, 2),
            "unrealized_pnl_intraday": round(intraday_pnl, 2),
        })

    intraday_total_equity = (
        total_position_value + cash if cash is not None else None
    )
    intraday_pnl_abs = (
        intraday_total_equity - prior_close_total_equity
        if intraday_total_equity is not None and prior_close_total_equity
        else None
    )
    intraday_pnl_pct = (
        (intraday_pnl_abs / prior_close_total_equity) * 100
        if intraday_pnl_abs is not None and prior_close_total_equity
        else None
    )

    return {
        "as_of_ist": now_ist.strftime("%Y-%m-%d %H:%M IST"),
        "as_of_utc": now_ist.astimezone(datetime.timezone.utc).isoformat(),
        "source": source,
        "kite_unavailable": kite_unavailable,
        "kite_unavailable_reason": kite_unavailable_reason,
        "n_positions": len(positions),
        "n_priced": n_priced,
        "n_missing": len(missing),
        "missing_symbols": missing,
        "total_position_value": round(total_position_value, 2),
        "prior_close_total_equity": (
            round(prior_close_total_equity, 2) if prior_close_total_equity else None
        ),
        "cash": round(cash, 2) if cash is not None else None,
        "intraday_total_equity": (
            round(intraday_total_equity, 2) if intraday_total_equity is not None else None
        ),
        "intraday_pnl_abs": (
            round(intraday_pnl_abs, 2) if intraday_pnl_abs is not None else None
        ),
        "intraday_pnl_pct": (
            round(intraday_pnl_pct, 4) if intraday_pnl_pct is not None else None
        ),
        "positions": rows,
    }


def fetch_kite_last_prices(kite, symbols: list[str]) -> dict[str, float]:
    if not symbols:
        return {}
    keys = [f"NSE:{s}" for s in symbols]
    quotes = kite.quote(keys)
    out: dict[str, float] = {}
    for key, q in quotes.items():
        sym = key.split(":", 1)[1] if ":" in key else key
        last = (q or {}).get("last_price")
        if last is None:
            continue
        try:
            out[sym] = float(last)
        except (TypeError, ValueError):
            continue
    return out


# ---------------------------------------------------------------------------
# Lambda entrypoint
# ---------------------------------------------------------------------------

def handler(event, context):
    s3 = boto3.client("s3")
    sm = boto3.client("secretsmanager")
    now_ist = datetime.datetime.now(IST)

    # 1. Portfolio CSV — required. If absent, nothing to mark.
    try:
        portfolio_bytes = s3.get_object(Bucket=STATE_BUCKET, Key=PORTFOLIO_KEY)["Body"].read()
    except s3.exceptions.NoSuchKey:
        return {"skipped": True, "reason": "no_portfolio"}
    positions = parse_portfolio(portfolio_bytes)
    if not positions:
        return {"skipped": True, "reason": "empty_portfolio"}

    # 2. Prior-close equity (best-effort).
    cash, prior_close_total_equity, prior_close_date = (None, None, None)
    try:
        equity_bytes = s3.get_object(Bucket=STATE_BUCKET, Key=EQUITY_KEY)["Body"].read()
        cash, prior_close_total_equity, prior_close_date = parse_prior_equity(equity_bytes)
    except s3.exceptions.NoSuchKey:
        pass

    # 3. Kite credentials.
    creds = _load_creds(sm)
    api_key = creds.get("api_key")
    access_token = creds.get("access_token")
    if not api_key or not access_token:
        return _write_fallback(
            s3, positions, prior_close_total_equity, cash, now_ist,
            reason="missing_credentials",
        )

    try:
        from kiteconnect import KiteConnect
    except ImportError:
        return _write_fallback(
            s3, positions, prior_close_total_equity, cash, now_ist,
            reason="kiteconnect_not_installed",
        )

    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(access_token)
    try:
        last_prices = fetch_kite_last_prices(kite, [p["symbol"] for p in positions])
    except Exception as exc:
        return _write_fallback(
            s3, positions, prior_close_total_equity, cash, now_ist,
            reason=f"kite_quote_failed: {type(exc).__name__}: {exc}",
        )

    payload = compute_intraday_mtm(
        positions=positions,
        last_prices=last_prices,
        prior_close_total_equity=prior_close_total_equity,
        cash=cash,
        source="kite_live",
        kite_unavailable=False,
        kite_unavailable_reason=None,
        now_ist=now_ist,
    )
    if prior_close_date:
        payload["prior_close_date"] = prior_close_date
    _put_json(s3, OUTPUT_KEY, payload)
    return {
        "ok": True,
        "n_positions": payload["n_positions"],
        "n_priced": payload["n_priced"],
        "intraday_pnl_pct": payload["intraday_pnl_pct"],
    }


def _load_creds(sm) -> dict:
    try:
        raw = sm.get_secret_value(SecretId=KITE_SECRET_NAME)["SecretString"]
        return json.loads(raw)
    except Exception:
        return {}


def _write_fallback(
    s3, positions, prior_close_total_equity, cash, now_ist, *, reason: str
) -> dict:
    payload = compute_intraday_mtm(
        positions=positions,
        last_prices={},
        prior_close_total_equity=prior_close_total_equity,
        cash=cash,
        source="prior_close",
        kite_unavailable=True,
        kite_unavailable_reason=reason,
        now_ist=now_ist,
    )
    _put_json(s3, OUTPUT_KEY, payload)
    return {"ok": True, "kite_unavailable": True, "reason": reason}


def _put_json(s3, key: str, payload: dict) -> None:
    s3.put_object(
        Bucket=STATE_BUCKET,
        Key=key,
        Body=json.dumps(payload, default=str).encode("utf-8"),
        ContentType="application/json",
    )
