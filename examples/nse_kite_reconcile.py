#!/usr/bin/env python3
"""Margin & holdings reconciliation — Tier 2 of the Kite read-only stack.

Two cheap defensive checks run from the daily cron:

  1. MARGIN GATE
     Compare today's paper-portfolio gross value (cash + positions) against
     the available cash Kite reports via `margins()`. If the model's intent
     to hold ₹X far exceeds the broker-reported funds you actually have,
     log a warning. When you eventually flip --live, this is the difference
     between executing and getting half your orders rejected at the broker.

  2. HOLDINGS DIFF
     Read paper `current_portfolio.csv`. Read Kite `holdings()`. Compute
     {paper_only, kite_only, qty_mismatch} symbol sets. Today this is purely
     informational — your paper holdings != your real holdings (you haven't
     traded). The day you go live, the diff should converge to empty; any
     divergence is a bug. Build the plumbing now, flip the alert later.

Outputs (overwritten daily):
    outputs/kite_reconcile.json
    {
      "as_of": "2026-04-27T...",
      "margin": {
          "kite_available_cash": 482912.0,
          "paper_gross_value":   1014523.0,
          "ratio":               2.10,
          "verdict":             "exceeds_margin"   # or "ok" | "no_paper_state"
      },
      "holdings": {
          "paper_count": 20,
          "kite_count":  3,
          "paper_only":  ["APARINDS", "BLUESTARCO", ...],
          "kite_only":   ["GOLDBEES", "JUNIORBEES", "NIFTYBEES"],
          "qty_mismatch": []
      }
    }

Exit codes mirror the rest of the Kite tools:
    0   reconcile written (or skipped because no token)
    2   token rejected by Kite — alertable from cron
    1   unexpected error
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Pure helpers — no I/O, fully testable
# ---------------------------------------------------------------------------

# When the model's gross intent is more than this multiple of available cash,
# flag it. 1.5x means "you'd need 50% leverage to actually execute" — already
# bad for retail equity (no MTF on most names).
MARGIN_RATIO_LIMIT = 1.5


def kite_available_cash(margins: dict) -> float:
    """Extract the equity-segment available cash from Kite's margins() dict.

    Kite shape:  {'equity': {'available': {'cash': N, ...}, ...}, 'commodity': ...}
    Returns 0.0 if the path is missing — the caller decides what that means.
    """
    if not isinstance(margins, dict):
        return 0.0
    equity = margins.get("equity")
    if not isinstance(equity, dict):
        return 0.0
    available = equity.get("available")
    if not isinstance(available, dict):
        return 0.0
    cash = available.get("cash") or available.get("live_balance") or 0.0
    try:
        return float(cash)
    except (TypeError, ValueError):
        return 0.0


def paper_gross_value(portfolio_rows: list[dict], cash: float) -> float:
    """Sum of (shares * mark) + cash. Works on the enriched CSV (which has
    'last_price') as well as the raw form (uses 'avg_price' as the fallback).
    """
    positions = 0.0
    for row in portfolio_rows:
        try:
            shares = float(row.get("shares", 0))
            mark = (
                float(row.get("last_price"))
                if row.get("last_price") not in (None, "", "nan")
                else float(row.get("avg_price", 0) or 0)
            )
        except (TypeError, ValueError):
            continue
        positions += shares * mark
    return positions + max(cash, 0.0)


def margin_verdict(kite_cash: float, paper_gross: float,
                   ratio_limit: float = MARGIN_RATIO_LIMIT) -> dict:
    """Compare paper gross to Kite's reported available cash."""
    if paper_gross <= 0:
        return {
            "kite_available_cash": kite_cash,
            "paper_gross_value": paper_gross,
            "ratio": 0.0,
            "verdict": "no_paper_state",
        }
    if kite_cash <= 0:
        return {
            "kite_available_cash": kite_cash,
            "paper_gross_value": paper_gross,
            # JSON has no native infinity; downstream consumers should treat
            # null as "ratio undefined / unbounded".
            "ratio": None,
            "verdict": "no_kite_funds",
        }
    ratio = paper_gross / kite_cash
    return {
        "kite_available_cash": round(kite_cash, 2),
        "paper_gross_value": round(paper_gross, 2),
        "ratio": round(ratio, 3),
        "verdict": "exceeds_margin" if ratio > ratio_limit else "ok",
    }


def diff_holdings(paper_rows: list[dict], kite_rows: list[dict]) -> dict:
    """Compute the symbol-level diff between the paper portfolio and Kite's
    real holdings.

    Returns:
        {
          "paper_count": int,
          "kite_count": int,
          "paper_only": [str, ...],     # in paper but not on Kite
          "kite_only": [str, ...],      # on Kite but not in paper
          "qty_mismatch": [
              {"symbol": str, "paper_qty": float, "kite_qty": float}, ...
          ],
        }
    """
    def _qty(row, *keys):
        for k in keys:
            v = row.get(k)
            if v not in (None, "", "nan"):
                try:
                    return float(v)
                except (TypeError, ValueError):
                    continue
        return 0.0

    paper = {row["symbol"]: _qty(row, "shares") for row in paper_rows if row.get("symbol")}
    kite = {row.get("tradingsymbol"): _qty(row, "quantity")
            for row in kite_rows if row.get("tradingsymbol")}

    paper_syms = set(paper) - {None, ""}
    kite_syms = set(kite) - {None, ""}

    qty_mismatch = []
    for sym in paper_syms & kite_syms:
        if abs(paper[sym] - kite[sym]) > 1e-6:
            qty_mismatch.append({
                "symbol": sym,
                "paper_qty": paper[sym],
                "kite_qty": kite[sym],
            })

    return {
        "paper_count": len(paper_syms),
        "kite_count": len(kite_syms),
        "paper_only": sorted(paper_syms - kite_syms),
        "kite_only": sorted(kite_syms - paper_syms),
        "qty_mismatch": qty_mismatch,
    }


def build_reconcile_report(
    margins: dict,
    holdings: list[dict],
    paper_portfolio: list[dict],
    last_equity_row: dict | None,
    *,
    as_of: str | None = None,
    ratio_limit: float = MARGIN_RATIO_LIMIT,
) -> dict:
    """Stitch the three signals into a single JSON-friendly report."""
    cash = 0.0
    if last_equity_row:
        try:
            cash = float(last_equity_row.get("cash", 0) or 0)
        except (TypeError, ValueError):
            cash = 0.0
    paper_gross = paper_gross_value(paper_portfolio, cash)
    return {
        "as_of": as_of or datetime.now(timezone.utc).isoformat(),
        "margin": margin_verdict(
            kite_available_cash(margins), paper_gross, ratio_limit=ratio_limit
        ),
        "holdings": diff_holdings(paper_portfolio, holdings),
    }


# ---------------------------------------------------------------------------
# I/O glue
# ---------------------------------------------------------------------------

def _load_creds(secret_name: str) -> dict:
    try:
        import boto3
        sm = boto3.client("secretsmanager")
        raw = sm.get_secret_value(SecretId=secret_name)["SecretString"]
        return json.loads(raw)
    except Exception:
        return {}


def _read_csv_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open() as f:
        return list(csv.DictReader(f))


def _last_row(rows: list[dict]) -> dict | None:
    return rows[-1] if rows else None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--portfolio", default="outputs/current_portfolio.csv")
    p.add_argument("--equity-log", default="outputs/paper_equity.csv")
    p.add_argument("--output", default="outputs/kite_reconcile.json")
    p.add_argument("--secret", default="nse-quant/kite")
    p.add_argument(
        "--ratio-limit", type=float, default=MARGIN_RATIO_LIMIT,
        help="paper_gross / kite_cash ratio above which we flag 'exceeds_margin'",
    )
    p.add_argument(
        "--skip-if-missing", action="store_true",
        help="exit 0 if no token / SDK is configured (cron-friendly)",
    )
    args = p.parse_args()

    creds = _load_creds(args.secret)
    api_key = creds.get("api_key")
    access_token = creds.get("access_token")
    if not api_key or not access_token:
        if args.skip_if_missing:
            print("[reconcile] no Kite token configured — skipping")
            return
        sys.exit("[reconcile] kite credentials missing — log in via /kite-login first")

    try:
        from kiteconnect import KiteConnect
    except ImportError:
        if args.skip_if_missing:
            print("[reconcile] kiteconnect SDK not installed — skipping")
            return
        sys.exit("[reconcile] kiteconnect not installed. Run: pip install kiteconnect")

    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(access_token)
    try:
        margins = kite.margins()
        holdings = kite.holdings()
    except Exception as exc:
        print(f"[reconcile] kite call rejected: {exc}")
        sys.exit(2)

    report = build_reconcile_report(
        margins=margins or {},
        holdings=holdings or [],
        paper_portfolio=_read_csv_rows(Path(args.portfolio)),
        last_equity_row=_last_row(_read_csv_rows(Path(args.equity_log))),
        ratio_limit=args.ratio_limit,
    )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2))

    # Compact stdout summary so the cron log is informative without being noisy
    m = report["margin"]
    h = report["holdings"]
    print(
        f"[reconcile] margin verdict={m['verdict']} "
        f"ratio={m['ratio']} (paper ₹{m['paper_gross_value']:,} / "
        f"kite ₹{m['kite_available_cash']:,})"
    )
    print(
        f"[reconcile] holdings paper={h['paper_count']} kite={h['kite_count']} "
        f"paper_only={len(h['paper_only'])} kite_only={len(h['kite_only'])} "
        f"qty_mismatch={len(h['qty_mismatch'])}"
    )


if __name__ == "__main__":
    main()
