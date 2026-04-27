#!/usr/bin/env python3
"""Shadow execution layer — Tier 1 of the Kite read-only stack.

For every BUY / SELL pick in today's decision file, fetch the real Kite
order book and compute the fill price you would have actually achieved if
you'd traded those shares at quote time. Writes a parallel
`outputs/shadow_trade_log.csv` alongside the paper log so we can compare
yfinance-EOD assumptions against real-market microstructure.

This script never calls `place_order()`. It is read-only by design —
gated behind the 90-day-paper rule (CLAUDE.md absolute rule #1).

Usage:
    python examples/nse_shadow_execute.py
    python examples/nse_shadow_execute.py --decision outputs/decisions/2026-04-25.json
    python examples/nse_shadow_execute.py --skip-if-missing   # cron-friendly

Output schema (outputs/shadow_trade_log.csv):
    date, action, symbol, shares, model_price, fill_price,
    slippage_bps, levels_consumed, fully_filled, kite_last_price,
    quote_taken_at

Exit codes mirror nse_kite_check.py:
    0  shadow log written (or skipped because no token / no decision)
    2  Kite token configured but rejected — alertable from cron
    1  any other unexpected error
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


# ---------------------------------------------------------------------------
# Pure helpers — small, testable, no I/O
# ---------------------------------------------------------------------------

def kite_symbol(model_symbol: str, exchange: str = "NSE") -> str:
    """Map a model-side symbol (e.g. 'INFY') to a Kite quote key
    (e.g. 'NSE:INFY'). If the caller already passed a prefix, return as-is."""
    if ":" in model_symbol:
        return model_symbol
    return f"{exchange}:{model_symbol}"


def walk_book(levels: list[dict], shares: int) -> dict:
    """Walk a depth ladder filling `shares`. Each level: {'price': float,
    'quantity': int}. Returns the VWAP fill, how many price levels we
    consumed, and whether the order was fully filled.

    Raises ValueError on malformed input (negative qty, missing keys).
    """
    if shares <= 0:
        raise ValueError(f"shares must be positive, got {shares}")
    if not levels:
        return {
            "fill_price": float("nan"),
            "levels_consumed": 0,
            "fully_filled": False,
            "available_qty": 0,
        }

    remaining = shares
    weighted_cost = 0.0
    consumed = 0
    available = 0

    for level in levels:
        price = float(level["price"])
        qty = int(level["quantity"])
        if price < 0 or qty < 0:
            raise ValueError(f"malformed level {level!r}")
        # Kite returns 5 depth slots per side; unused slots are zero-padded
        # ({'price': 0, 'quantity': 0}). Treat them as "no order present".
        if price == 0 or qty == 0:
            continue
        available += qty
        if remaining <= 0:
            break
        take = min(remaining, qty)
        weighted_cost += take * price
        remaining -= take
        if take > 0:
            consumed += 1

    filled = shares - remaining
    if filled == 0:
        return {
            "fill_price": float("nan"),
            "levels_consumed": 0,
            "fully_filled": False,
            "available_qty": available,
        }
    return {
        "fill_price": weighted_cost / filled,
        "levels_consumed": consumed,
        "fully_filled": remaining == 0,
        "available_qty": available,
    }


def compute_slippage_bps(model_price: float, fill_price: float, action: str) -> float:
    """Slippage in basis points. Positive = unfavorable (paid up on buy,
    sold under on sell)."""
    if model_price <= 0 or fill_price != fill_price:  # NaN check
        return float("nan")
    raw = (fill_price / model_price - 1.0) * 1e4
    if action.upper() == "SELL":
        return -raw  # selling lower than model = positive slippage
    return raw


def merge_decision_with_fills(
    decision: dict,
    paper_trades: list[dict],
) -> list[dict]:
    """Pair each BUY / SELL action with the share count the paper trader
    actually filled (from trade_log.csv rows for the same date). Returns
    one row per fill, ready for the shadow execution loop.

    Pure function — no I/O. Tests pin its behaviour.
    """
    as_of = decision.get("as_of") or decision.get("date")
    if not as_of:
        return []

    by_sym = {}
    for trade in paper_trades:
        if str(trade.get("date")) != str(as_of):
            continue
        if trade.get("action") not in ("BUY", "SELL"):
            continue
        try:
            shares = int(float(trade["shares"]))
            price = float(trade["price"])
        except (KeyError, ValueError, TypeError):
            continue
        if shares <= 0:
            continue
        by_sym.setdefault(trade["symbol"], []).append({
            "action": trade["action"],
            "shares": shares,
            "model_price": price,
        })

    out: list[dict] = []
    for action_key in ("BUY", "SELL"):
        for pick in decision.get("actions", {}).get(action_key, []):
            sym = pick["symbol"]
            for fill in by_sym.get(sym, []):
                if fill["action"] != action_key:
                    continue
                out.append({
                    "date": as_of,
                    "action": action_key,
                    "symbol": sym,
                    "shares": fill["shares"],
                    "model_price": fill["model_price"],
                })
    return out


# ---------------------------------------------------------------------------
# I/O glue — Kite quote fetcher, decision loader, CSV writer
# ---------------------------------------------------------------------------

def _load_creds(secret_name: str) -> dict:
    try:
        import boto3
        sm = boto3.client("secretsmanager")
        raw = sm.get_secret_value(SecretId=secret_name)["SecretString"]
        return json.loads(raw)
    except Exception:
        return {}


def _latest_decision_path(decisions_dir: Path) -> Path | None:
    candidates = sorted(decisions_dir.glob("*.json"))
    return candidates[-1] if candidates else None


def _load_paper_trades(trade_log_path: Path) -> list[dict]:
    if not trade_log_path.exists():
        return []
    with trade_log_path.open() as f:
        return list(csv.DictReader(f))


def fetch_quotes_via_kite(kite, kite_symbols: Iterable[str]) -> dict:
    """Wrapper so tests can stub it. Returns the raw kite.quote() dict."""
    syms = list(kite_symbols)
    if not syms:
        return {}
    return kite.quote(syms)


def shadow_fill(quote_for_symbol: dict, action: str, shares: int) -> dict:
    """Take a single-symbol quote dict from Kite and synthesise a fill.

    Quote shape (subset we use):
        {
            'last_price': float,
            'depth': {
                'buy':  [{'price': ..., 'quantity': ...}, ...],   # bids
                'sell': [{'price': ..., 'quantity': ...}, ...],   # asks
            },
            'timestamp': iso8601 string (optional)
        }
    """
    depth = (quote_for_symbol or {}).get("depth", {}) or {}
    book = depth.get("sell" if action.upper() == "BUY" else "buy", []) or []
    return walk_book(book, shares)


# ---------------------------------------------------------------------------
# Top-level run
# ---------------------------------------------------------------------------

def run_shadow_execution(
    decision_path: Path,
    trade_log_path: Path,
    output_path: Path,
    quote_fetcher,
    *,
    quote_taken_at: str | None = None,
) -> dict:
    """End-to-end runner. `quote_fetcher` is a callable taking
    list[str] -> dict[str, dict]; injected so tests can mock it.
    Returns a small summary dict."""
    decision = json.loads(decision_path.read_text())
    paper_trades = _load_paper_trades(trade_log_path)
    fills = merge_decision_with_fills(decision, paper_trades)
    if not fills:
        return {"rows": 0, "skipped": "no_paper_fills_for_decision_date"}

    kite_keys = [kite_symbol(f["symbol"]) for f in fills]
    quotes = quote_fetcher(kite_keys)
    quote_taken_at = quote_taken_at or datetime.now(timezone.utc).isoformat()

    rows = []
    for fill in fills:
        key = kite_symbol(fill["symbol"])
        quote = quotes.get(key) or {}
        result = shadow_fill(quote, fill["action"], fill["shares"])
        slippage = compute_slippage_bps(
            fill["model_price"], result["fill_price"], fill["action"]
        )
        rows.append({
            "date": fill["date"],
            "action": fill["action"],
            "symbol": fill["symbol"],
            "shares": fill["shares"],
            "model_price": round(fill["model_price"], 4),
            "fill_price": (
                round(result["fill_price"], 4)
                if result["fill_price"] == result["fill_price"]   # not NaN
                else ""
            ),
            "slippage_bps": (
                round(slippage, 2) if slippage == slippage else ""
            ),
            "levels_consumed": result["levels_consumed"],
            "fully_filled": result["fully_filled"],
            "kite_last_price": quote.get("last_price", ""),
            "quote_taken_at": quote_taken_at,
        })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = output_path.exists()
    with output_path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)

    fully = sum(1 for r in rows if r["fully_filled"])
    return {
        "rows": len(rows),
        "fully_filled": fully,
        "partial_or_missing": len(rows) - fully,
        "output": str(output_path),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--decision", help="Path to decision JSON (defaults to latest in --decisions-dir)")
    p.add_argument("--decisions-dir", default="outputs/decisions")
    p.add_argument("--trade-log", default="outputs/trade_log.csv")
    p.add_argument("--output", default="outputs/shadow_trade_log.csv")
    p.add_argument("--secret", default="nse-quant/kite")
    p.add_argument(
        "--skip-if-missing",
        action="store_true",
        help="exit 0 if no token / SDK / decision is configured (cron-friendly)",
    )
    args = p.parse_args()

    decision_path = (
        Path(args.decision) if args.decision
        else _latest_decision_path(Path(args.decisions_dir))
    )
    if decision_path is None or not decision_path.exists():
        msg = f"[shadow] no decision file found in {args.decisions_dir}"
        if args.skip_if_missing:
            print(msg + " — skipping")
            return
        sys.exit(msg)

    creds = _load_creds(args.secret)
    api_key = creds.get("api_key")
    access_token = creds.get("access_token")
    if not api_key or not access_token:
        if args.skip_if_missing:
            print("[shadow] no Kite token configured — skipping")
            return
        sys.exit("[shadow] kite credentials missing — log in via /kite-login first")

    try:
        from kiteconnect import KiteConnect
    except ImportError:
        if args.skip_if_missing:
            print("[shadow] kiteconnect SDK not installed — skipping")
            return
        sys.exit("[shadow] kiteconnect not installed. Run: pip install kiteconnect")

    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(access_token)

    def fetcher(keys):
        try:
            return fetch_quotes_via_kite(kite, keys)
        except Exception as exc:
            print(f"[shadow] kite.quote() failed: {exc}")
            sys.exit(2)

    summary = run_shadow_execution(
        decision_path=decision_path,
        trade_log_path=Path(args.trade_log),
        output_path=Path(args.output),
        quote_fetcher=fetcher,
    )
    print("[shadow]", json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
