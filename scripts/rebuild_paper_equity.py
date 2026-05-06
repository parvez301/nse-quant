#!/usr/bin/env python3
"""Re-execute every historical decision from a clean ₹1M ledger.

Why this exists: nse_paper_trade.cmd_execute used to write the equity row's
`cash` column as settled+pending, then on the next run read that combined
value AND released the matured pending again — receivables double-counted on
every rebalance. Equity ratcheted ₹1M → ₹5.5M over Apr 23 → May 5.

Replaying the recorded trade_log literally is invalid: those fills were sized
against the inflated cash, so a literal replay drives cash to ₹-4M+. Instead
we throw away the broken trade history and replay the *decisions* (which
were correct — they're just the model's BUY/HOLD/SELL list) against the now-
fixed cmd_execute. End state is the equity curve we *would* have had with
honest accounting from day one.

Run from repo root after the fix has landed:
  ./.venv/bin/python scripts/rebuild_paper_equity.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "examples"))

import nse_paper_trade as ptm  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--starting-cash", type=float, default=1_000_000.0)
    p.add_argument("--decisions-dir", default="outputs/decisions")
    p.add_argument("--equity-out", default="outputs/paper_equity.csv")
    p.add_argument("--portfolio-out", default="outputs/current_portfolio.csv")
    p.add_argument("--pending-out", default="outputs/pending_settlement.csv")
    p.add_argument("--trade-log-out", default="outputs/trade_log.csv")
    p.add_argument("--qlib-provider", default="data/qlib_data/in_data")
    p.add_argument("--buy-cost", type=float, default=0.0015)
    p.add_argument("--sell-cost", type=float, default=0.0025)
    p.add_argument("--settlement-lag-days", type=int, default=1)
    args = p.parse_args()

    # Wipe rebuilt artefacts (we re-derive them).
    for path in (args.equity_out, args.portfolio_out,
                 args.pending_out, args.trade_log_out):
        f = REPO / path
        if f.exists():
            f.unlink()
            print(f"[reset] removed {path}")

    decision_files = sorted((REPO / args.decisions_dir).glob("*.json"))
    if not decision_files:
        sys.exit(f"[abort] no decisions in {args.decisions_dir}")

    print(f"[plan] re-executing {len(decision_files)} decisions from cash ₹{args.starting_cash:,.0f}")

    for i, dec_path in enumerate(decision_files):
        date = dec_path.stem
        common = {
            "date": date,
            "decisions_dir": str(REPO / args.decisions_dir),
            "portfolio": str(REPO / args.portfolio_out),
            "trade_log": str(REPO / args.trade_log_out),
            "equity_log": str(REPO / args.equity_out),
            "pending_settlement": str(REPO / args.pending_out),
            "qlib_provider": str(REPO / args.qlib_provider),
            "starting_cash": args.starting_cash if i == 0 else 0.0,
            "buy_cost": args.buy_cost,
            "sell_cost": args.sell_cost,
            "settlement_lag_days": args.settlement_lag_days,
        }
        print(f"\n[exec {i+1}/{len(decision_files)}] {date} ...")
        ptm.cmd_execute(SimpleNamespace(**common))

    # Final summary.
    eq = pd.read_csv(REPO / args.equity_out)
    final = eq.iloc[-1]
    pct = (final["total_equity"] / args.starting_cash - 1) * 100
    print(f"\n[done] {len(eq)} equity rows rebuilt")
    print(f"[done] start ₹{args.starting_cash:,.0f}  end ₹{final['total_equity']:,.0f}  ({pct:+.2f}%)")
    print(f"[done] cash ₹{final['cash']:,.0f}  pending ₹{final['pending_settlement']:,.0f}  "
          f"positions ₹{final['positions_value']:,.0f}  ({int(final['n_positions'])} symbols)")
    print("\n--- equity curve ---")
    print(eq[["date", "cash", "pending_settlement", "positions_value",
              "total_equity", "n_positions"]].to_string(index=False))


if __name__ == "__main__":
    main()
