#!/usr/bin/env python3
"""Paper-trading logger + rolling performance tracker.

Daily workflow (manual, 5 min):
  1. Morning: `python examples/nse_daily_decision.py` emits outputs/decisions/YYYY-MM-DD.json
  2. You eyeball the BUY/SELL list in outputs/decisions/YYYY-MM-DD.txt
  3. Paper trade it: call `python examples/nse_paper_trade.py execute YYYY-MM-DD`
     to "fill" the trades at that day's close price (purely simulated, no broker).
  4. Next morning: `python examples/nse_paper_trade.py mark` to update P&L to latest close.
  5. Weekly: `python examples/nse_paper_trade.py report` prints rolling IC, Sharpe,
     drawdown, and compares your simulated portfolio to NIFTY 50 buy-and-hold.

Files maintained:
  outputs/current_portfolio.csv     <- current holdings (editable by hand)
  outputs/trade_log.csv             <- every simulated fill, audit trail
  outputs/paper_equity.csv          <- daily marked-to-market equity curve
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd


def qlib_init(provider_uri: str):
    import qlib
    qlib.init(provider_uri=os.path.expanduser(provider_uri), region="cn")


def next_trading_day(provider_uri: str, date_str: str, lag_days: int = 1) -> str:
    """Return the trading day that is `lag_days` calendar-respected sessions
    after `date_str`. Uses the qlib calendar so weekends/holidays are skipped.
    """
    qlib_init(provider_uri)
    from qlib.data import D
    cal = D.calendar(start_time=date_str)
    if len(cal) <= lag_days:
        # Fall back to a naive 1-business-day if the calendar is short
        return (pd.Timestamp(date_str) + pd.tseries.offsets.BDay(lag_days)).strftime("%Y-%m-%d")
    return cal[lag_days].strftime("%Y-%m-%d")


def release_matured_settlements(pending: pd.DataFrame, as_of: str) -> tuple[pd.DataFrame, float]:
    """Split a pending-settlement frame into (still_pending, released_cash).
    Pure function — no I/O, easy to test."""
    if pending is None or pending.empty:
        return pd.DataFrame(columns=["settlement_date", "amount"]), 0.0
    matured = pending[pending["settlement_date"] <= as_of]
    still_pending = pending[pending["settlement_date"] > as_of].reset_index(drop=True)
    released = float(matured["amount"].sum()) if not matured.empty else 0.0
    return still_pending, released


def close_price(symbols, date: str, provider_uri: str) -> pd.Series:
    """Return close price per symbol on `date`. NaN if unavailable."""
    qlib_init(provider_uri)
    from qlib.data import D
    df = D.features(list(symbols), ["$close"], start_time=date, end_time=date)
    if df.empty:
        return pd.Series(dtype=float, name="close")
    # df is indexed by (instrument, datetime) — pick the one date
    s = df["$close"].droplevel("datetime") if "datetime" in df.index.names else df["$close"]
    s.name = "close"
    return s


# ---------------------------------------------------------------------------
# execute: apply a decision JSON as simulated fills at close price
# ---------------------------------------------------------------------------

def cmd_execute(args):
    decision_path = Path(args.decisions_dir) / f"{args.date}.json"
    if not decision_path.exists():
        sys.exit(f"[abort] no decision for {args.date} at {decision_path}")

    with open(decision_path) as f:
        decision = json.load(f)

    portfolio_path = Path(args.portfolio)
    if portfolio_path.exists():
        portfolio = pd.read_csv(portfolio_path)
    else:
        portfolio = pd.DataFrame(columns=["symbol", "shares", "avg_price", "bought_on"])

    log_path = Path(args.trade_log)
    if log_path.exists():
        log = pd.read_csv(log_path)
    else:
        log = pd.DataFrame(columns=["date", "action", "symbol", "shares", "price", "amount", "reason"])

    buys = [a["symbol"] for a in decision["actions"]["BUY"]]
    sells = [a["symbol"] for a in decision["actions"]["SELL"]]

    universe = list(set(buys) | set(sells))
    if not universe:
        print("[info] nothing to do for", args.date)
        return

    prices = close_price(universe, args.date, args.qlib_provider)
    print(f"[prices] {len(prices.dropna())} / {len(universe)} symbols priced on {args.date}")

    # ---- T+N settlement bookkeeping ----------------------------------------
    pending_path = Path(args.pending_settlement)
    if pending_path.exists():
        pending = pd.read_csv(pending_path, dtype={"settlement_date": str})
    else:
        pending = pd.DataFrame(columns=["settlement_date", "amount"])

    # Determine cash available — start from last equity row's cash
    equity_path = Path(args.equity_log)
    if equity_path.exists():
        eq = pd.read_csv(equity_path)
        current_cash = float(eq["cash"].iloc[-1]) if len(eq) else args.starting_cash
    else:
        current_cash = args.starting_cash

    # Release any sell proceeds whose settlement date has now arrived
    pending, released = release_matured_settlements(pending, args.date)
    if released > 0:
        print(f"[settlement] released ₹{released:,.2f} from prior sells")
        current_cash += released

    # Compute the settlement date for sells executed today (T+N trading days)
    if sells:
        sell_settlement_date = next_trading_day(
            args.qlib_provider, args.date, lag_days=args.settlement_lag_days
        )
    else:
        sell_settlement_date = args.date

    # SELL first — proceeds go to PENDING, not directly to cash
    new_rows = []
    new_pending_rows: list[dict] = []
    for sym in sells:
        if sym not in prices or pd.isna(prices[sym]):
            print(f"  SELL skipped: {sym} — no close price on {args.date}")
            continue
        held = portfolio[portfolio["symbol"] == sym]
        if held.empty:
            print(f"  SELL skipped: {sym} — not in portfolio")
            continue
        sh = float(held["shares"].iloc[0])
        px = float(prices[sym])
        proceeds = sh * px * (1 - args.sell_cost)
        new_rows.append({
            "date": args.date, "action": "SELL", "symbol": sym,
            "shares": sh, "price": px, "amount": proceeds,
            "reason": f"strategy drop (settles {sell_settlement_date})",
        })
        new_pending_rows.append({
            "settlement_date": sell_settlement_date,
            "amount": proceeds,
        })
        portfolio = portfolio[portfolio["symbol"] != sym]

    if new_pending_rows:
        pending = pd.concat([pending, pd.DataFrame(new_pending_rows)], ignore_index=True)
        print(f"[settlement] queued ₹{sum(r['amount'] for r in new_pending_rows):,.2f} "
              f"to settle on {sell_settlement_date}")

    # BUY: allocate equal capital per BUY symbol
    eligible_buys = [s for s in buys if s in prices.index and not pd.isna(prices[s])]
    if eligible_buys:
        # target position count = current holdings after sells + buys (cap at topk)
        n_after_sells = len(portfolio) + len(eligible_buys)
        # Use 95% of cash, equal weight across buys
        cash_to_deploy = current_cash * 0.95
        per_buy = cash_to_deploy / len(eligible_buys)
        for sym in eligible_buys:
            px = float(prices[sym])
            shares = int(per_buy / (px * (1 + args.buy_cost)))
            if shares < 1:
                print(f"  BUY skipped: {sym} — per-buy budget ₹{per_buy:.0f} < 1 share @ ₹{px:.2f}")
                continue
            cost = shares * px * (1 + args.buy_cost)
            current_cash -= cost
            new_rows.append({
                "date": args.date, "action": "BUY", "symbol": sym,
                "shares": shares, "price": px, "amount": cost,
                "reason": f"rank {next((a['rank'] for a in decision['actions']['BUY'] if a['symbol'] == sym), '?')}",
            })
            portfolio = pd.concat([portfolio, pd.DataFrame([{
                "symbol": sym, "shares": shares, "avg_price": px, "bought_on": args.date,
            }])], ignore_index=True)

    # Persist
    log = pd.concat([log, pd.DataFrame(new_rows)], ignore_index=True)
    log.to_csv(log_path, index=False)
    portfolio.to_csv(portfolio_path, index=False)
    pending_path.parent.mkdir(parents=True, exist_ok=True)
    pending.to_csv(pending_path, index=False)

    # Persist settled cash and unsettled pending separately so a future
    # execute() can read back cash without also adding matured pending again.
    pending_value = float(pending["amount"].sum()) if not pending.empty else 0.0
    mark_portfolio_and_log(portfolio, current_cash, args.date,
                           args.qlib_provider, equity_path,
                           pending_value=pending_value)

    print(f"\n[done] {len(new_rows)} trades simulated, {len(portfolio)} holdings, "
          f"cash ₹{current_cash:,.0f}, unsettled ₹{pending_value:,.0f}")


# ---------------------------------------------------------------------------
# mark: mark-to-market current portfolio to latest close
# ---------------------------------------------------------------------------

def mark_portfolio_and_log(portfolio: pd.DataFrame, cash: float, as_of: str,
                           qlib_provider: str, equity_path: Path,
                           portfolio_path: Path | None = None,
                           pending_value: float = 0.0):
    """Persist a marked equity row.

    `cash` is SETTLED cash (spendable today). `pending_value` is unsettled
    sell receivables tracked separately. Total equity rolls all three
    components together. Splitting them prevents the row's `cash` column
    from being read back next day AND `pending` rows from being released
    on top of it — the historical double-count bug.
    """
    if portfolio.empty:
        positions_value = 0.0
        unrealized = 0.0
    else:
        prices = close_price(portfolio["symbol"].tolist(), as_of, qlib_provider)
        portfolio = portfolio.copy()
        portfolio["mark"] = portfolio["symbol"].map(prices)
        portfolio["mark"] = portfolio["mark"].fillna(portfolio["avg_price"])
        positions_value = float((portfolio["shares"] * portfolio["mark"]).sum())
        unrealized = float(((portfolio["mark"] - portfolio["avg_price"]) * portfolio["shares"]).sum())

        # Persist the mark back to the portfolio CSV so the dashboard can show
        # per-position P&L. Adds three columns; existing columns preserved.
        if portfolio_path is not None:
            enriched = portfolio.copy()
            enriched["last_price"] = enriched["mark"].round(4)
            enriched["position_value"] = (enriched["shares"] * enriched["mark"]).round(2)
            enriched["unrealized_pnl"] = ((enriched["mark"] - enriched["avg_price"]) * enriched["shares"]).round(2)
            enriched["marked_on"] = as_of
            enriched = enriched.drop(columns=["mark"])
            enriched.to_csv(portfolio_path, index=False)

    total = cash + pending_value + positions_value

    try:
        nifty = close_price(["NIFTY50"], as_of, qlib_provider)
        nifty_close = float(nifty.iloc[0]) if not nifty.empty and not pd.isna(nifty.iloc[0]) else np.nan
    except Exception:
        nifty_close = np.nan

    row = {
        "date": as_of,
        "cash": round(cash, 2),
        "pending_settlement": round(pending_value, 2),
        "positions_value": round(positions_value, 2),
        "total_equity": round(total, 2),
        "n_positions": len(portfolio),
        "unrealized_pnl": round(unrealized, 2),
        "nifty50_close": round(nifty_close, 2) if not pd.isna(nifty_close) else "",
    }

    if equity_path.exists():
        eq = pd.read_csv(equity_path)
        # Replace today's row if already present
        eq = eq[eq["date"] != as_of]
        eq = pd.concat([eq, pd.DataFrame([row])], ignore_index=True)
    else:
        eq = pd.DataFrame([row])
    eq = eq.sort_values("date").reset_index(drop=True)
    eq.to_csv(equity_path, index=False)


def cmd_mark(args):
    portfolio_path = Path(args.portfolio)
    if not portfolio_path.exists():
        sys.exit(f"[abort] no portfolio at {portfolio_path}")
    portfolio = pd.read_csv(portfolio_path)

    equity_path = Path(args.equity_log)
    cash = args.starting_cash
    if equity_path.exists():
        eq = pd.read_csv(equity_path)
        if len(eq):
            cash = float(eq["cash"].iloc[-1])

    pending_path = Path(args.pending_settlement)
    if pending_path.exists():
        pending = pd.read_csv(pending_path)
        pending_value = float(pending["amount"].sum()) if not pending.empty else 0.0
    else:
        pending_value = 0.0

    qlib_init(args.qlib_provider)
    from qlib.data import D
    cal = D.calendar(start_time="2024-01-01")
    as_of = cal[-1].strftime("%Y-%m-%d")

    mark_portfolio_and_log(portfolio, cash, as_of, args.qlib_provider, equity_path,
                           portfolio_path=portfolio_path,
                           pending_value=pending_value)
    print(f"[mark] equity curve updated to {as_of}")
    eq = pd.read_csv(equity_path)
    print(eq.tail().to_string(index=False))


# ---------------------------------------------------------------------------
# report: rolling Sharpe, drawdown, alpha vs NIFTY50
# ---------------------------------------------------------------------------

def cmd_report(args):
    equity_path = Path(args.equity_log)
    if not equity_path.exists() or pd.read_csv(equity_path).empty:
        sys.exit(f"[abort] no equity history at {equity_path}")
    eq = pd.read_csv(equity_path).sort_values("date").reset_index(drop=True)
    if len(eq) < 5:
        print(f"[info] only {len(eq)} days of history — come back after a week")
        print(eq.to_string(index=False))
        return

    eq["date"] = pd.to_datetime(eq["date"])
    eq["strategy_ret"] = eq["total_equity"].pct_change()
    eq["nifty_ret"] = pd.to_numeric(eq["nifty50_close"], errors="coerce").pct_change()
    eq["excess_ret"] = eq["strategy_ret"] - eq["nifty_ret"]

    n = len(eq)
    strat_ret = eq["strategy_ret"].dropna()
    excess = eq["excess_ret"].dropna()

    ann = 252.0
    def _safe(v):
        return v if pd.notna(v) else 0.0

    metrics = {
        "days_of_history": n,
        "start_date": str(eq["date"].iloc[0].date()),
        "end_date": str(eq["date"].iloc[-1].date()),
        "total_return_strategy": _safe(eq["total_equity"].iloc[-1] / eq["total_equity"].iloc[0] - 1),
        "total_return_nifty": _safe(
            pd.to_numeric(eq["nifty50_close"], errors="coerce").iloc[-1]
            / pd.to_numeric(eq["nifty50_close"], errors="coerce").iloc[0] - 1
        ) if eq["nifty50_close"].notna().any() else None,
        "annualised_ret": _safe((1 + strat_ret.mean()) ** ann - 1) if len(strat_ret) else None,
        "annualised_sharpe": _safe(strat_ret.mean() / strat_ret.std() * np.sqrt(ann)) if len(strat_ret) > 1 and strat_ret.std() > 0 else None,
        "annualised_excess_sharpe": _safe(excess.mean() / excess.std() * np.sqrt(ann)) if len(excess) > 1 and excess.std() > 0 else None,
        "max_drawdown": _safe(((eq["total_equity"] / eq["total_equity"].cummax()) - 1).min()),
        "best_day": _safe(strat_ret.max()),
        "worst_day": _safe(strat_ret.min()),
        "up_days": int((strat_ret > 0).sum()),
        "down_days": int((strat_ret < 0).sum()),
    }

    print("=" * 60)
    print(f"  PAPER TRADING REPORT  —  {metrics['start_date']} → {metrics['end_date']}")
    print(f"  {metrics['days_of_history']} days of history")
    print("=" * 60)
    for k, v in metrics.items():
        if v is None:
            print(f"  {k:30s}  n/a")
        elif isinstance(v, float):
            if "ret" in k or "draw" in k or "day" in k.split("_")[-1]:
                print(f"  {k:30s}  {v:+.2%}")
            else:
                print(f"  {k:30s}  {v:+.3f}")
        else:
            print(f"  {k:30s}  {v}")
    print("=" * 60)

    # Guard against known trap
    if metrics["annualised_sharpe"] is not None and metrics["days_of_history"] < 60:
        print("\n  ⚠  Under 60 days of paper trading. These numbers are statistical noise.")
        print("     Wait at least 3 months before drawing conclusions about the strategy.")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    common_args = {
        "portfolio":      ("outputs/current_portfolio.csv", "holdings CSV"),
        "trade_log":      ("outputs/trade_log.csv", "per-trade audit log"),
        "equity_log":     ("outputs/paper_equity.csv", "daily marked equity curve"),
        "decisions_dir":  ("outputs/decisions", "dir of decision JSONs"),
        "qlib_provider":  ("data/qlib_data/in_data", "Qlib binary data root"),
        "pending_settlement": ("outputs/pending_settlement.csv",
                               "T+N unsettled sell proceeds"),
    }

    p_exec = sub.add_parser("execute", help="simulate fills from a decision JSON at that day's close")
    p_exec.add_argument("date", help="YYYY-MM-DD of the decision to execute")
    for key, (default, help_) in common_args.items():
        p_exec.add_argument(f"--{key}", default=default, help=help_)
    p_exec.add_argument("--starting_cash", type=float, default=1_000_000,
                        help="starting paper capital in INR (first run only)")
    p_exec.add_argument("--buy_cost", type=float, default=0.0015)
    p_exec.add_argument("--sell_cost", type=float, default=0.0025)
    p_exec.add_argument("--settlement_lag_days", type=int, default=1,
                        help="trading days until SELL proceeds become available "
                             "as cash (NSE = T+1 since 2023)")

    p_mark = sub.add_parser("mark", help="mark portfolio to latest close, append to equity curve")
    for key, (default, help_) in common_args.items():
        p_mark.add_argument(f"--{key}", default=default, help=help_)
    p_mark.add_argument("--starting_cash", type=float, default=1_000_000)

    p_rep = sub.add_parser("report", help="rolling performance vs NIFTY 50")
    for key, (default, help_) in common_args.items():
        p_rep.add_argument(f"--{key}", default=default, help=help_)

    args = p.parse_args()

    if args.cmd == "execute":
        cmd_execute(args)
    elif args.cmd == "mark":
        cmd_mark(args)
    elif args.cmd == "report":
        cmd_report(args)


if __name__ == "__main__":
    main()
