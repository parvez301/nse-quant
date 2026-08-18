#!/usr/bin/env python3
"""Regenerate ui_lambda/v2/options-data.js — the embedded dataset behind the
OPTIONS tab's per-stock simulation explorer and doc audit.

Reruns the judged window (2023 -> present, no-stop variant, earnings filter
ON — identical to the committed verdict) with the enriched trade log, plus
cycle-level counts of how many entry opportunities each doc rule removed.
"""
from __future__ import annotations

import datetime
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from options.backtest import (build_cycles, monthly_expiry_dates, run_backtest,  # noqa: E402
                              summary_stats, _archive_days)
from options.config import JUDGE_CAPITAL  # noqa: E402
from options.filters import in_blackout, in_earnings_window, load_blackouts  # noqa: E402
from options.underlying import AdjustedCloseStore  # noqa: E402

JUDGED_START, JUDGED_END = "2023-01-01", "2026-08-18"

# The 13 large caps from the friend's follow-up spreadsheet
# (S7hwts2HCevZtLC1-_TBE.xlsx), with his measured "months inside ±12% of
# month-open" win counts over 79 months — his own numbers, quoted verbatim.
SHEET_STOCKS = {
    "TCS":        {"win": 66, "loose": 13},
    "RELIANCE":   {"win": 62, "loose": 17},
    "SBICARD":    {"win": 39, "loose": 26},
    "MARUTI":     {"win": 62, "loose": 17},
    "TATACONSUM": {"win": 58, "loose": 21},
    "HINDUNILVR": {"win": 68, "loose": 11},
    "ULTRACEMCO": {"win": 61, "loose": 18},
    "AMBUJACEM":  {"win": 53, "loose": 26},
    "BAJFINANCE": {"win": 54, "loose": 25},
    "ASIANPAINT": {"win": 61, "loose": 18},
    "ITC":        {"win": 65, "loose": 14},
    "TATASTEEL":  {"win": 45, "loose": 34},
    "GRASIM":     {"win": 58, "loose": 21},
}


def cycle_filter_counts(archive_root: pathlib.Path) -> dict:
    trading_days = _archive_days(archive_root, JUDGED_START, JUDGED_END)
    expiries = monthly_expiry_dates(archive_root, JUDGED_START, JUDGED_END)
    cycles = build_cycles(expiries, trading_days)
    blackout_ranges = load_blackouts(REPO_ROOT / "data" / "options_blackouts.yaml")
    blackout_hits, earnings_hits, clean = 0, 0, 0
    for cycle in cycles:
        entry = datetime.date.fromisoformat(cycle["entry_date"])
        expiry = datetime.date.fromisoformat(cycle["expiry"])
        if in_blackout(entry, expiry, blackout_ranges):
            blackout_hits += 1
        elif in_earnings_window(entry, expiry):
            earnings_hits += 1
        else:
            clean += 1
    return {"total_cycles": len(cycles), "blackout_cycles": blackout_hits,
            "earnings_cycles": earnings_hits, "tradeable_cycles": clean}


def main() -> int:
    archive_root = REPO_ROOT / "data" / "fo_bhavcopy"
    close_store = AdjustedCloseStore(REPO_ROOT / "data" / "qlib_data" / "in_data")
    result = run_backtest(archive_root, close_store, JUDGED_START, JUDGED_END,
                          stop_key="none", use_earnings_filter=True,
                          capital=JUDGE_CAPITAL,
                          blackouts_path=REPO_ROOT / "data" / "options_blackouts.yaml")
    stats = summary_stats(result)
    trades = result["trades"]

    trades_by_symbol: dict[str, list[dict]] = {}
    for trade in sorted(trades, key=lambda t: t["entry_date"]):
        rounded = {key: (round(value, 4) if isinstance(value, float) else value)
                   for key, value in trade.items()}
        trades_by_symbol.setdefault(trade["symbol"], []).append(rounded)

    exit_reasons = {"target": 0, "time": 0, "stop": 0}
    for trade in trades:
        exit_reasons[trade["exit_reason"]] += 1

    # ── The friend's 13 sheet stocks, simulated two ways ────────────
    # (a) "his rules": identical protocol to the judged verdict, universe
    #     restricted to the 13; (b) "every tradeable month": score floor and
    #     position cap lifted (capital raised so margin never blocks entry)
    #     so EVERY sheet stock trades each non-excluded cycle — a per-stock
    #     exhibit, not a portfolio claim.
    sheet_universe = set(SHEET_STOCKS)
    sheet_rules = run_backtest(archive_root, close_store, JUDGED_START, JUDGED_END,
                               stop_key="none", use_earnings_filter=True,
                               capital=JUDGE_CAPITAL,
                               blackouts_path=REPO_ROOT / "data" / "options_blackouts.yaml",
                               universe=sheet_universe)
    sheet_forced = run_backtest(archive_root, close_store, JUDGED_START, JUDGED_END,
                                stop_key="none", use_earnings_filter=True,
                                capital=3_000_000.0,
                                blackouts_path=REPO_ROOT / "data" / "options_blackouts.yaml",
                                universe=sheet_universe, score_floor=0.0,
                                max_positions=len(sheet_universe))
    sheet_trades_by_symbol: dict[str, list[dict]] = {}
    for trade in sorted(sheet_forced["trades"], key=lambda t: t["entry_date"]):
        rounded = {key: (round(value, 4) if isinstance(value, float) else value)
                   for key, value in trade.items()}
        sheet_trades_by_symbol.setdefault(trade["symbol"], []).append(rounded)
    per_stock_rows = []
    for symbol, claim in sorted(SHEET_STOCKS.items()):
        symbol_trades = sheet_trades_by_symbol.get(symbol, [])
        symbol_wins = [t for t in symbol_trades if t["net_pnl"] > 0]
        per_stock_rows.append({
            "symbol": symbol,
            "sheet_win_pct": round(claim["win"] / (claim["win"] + claim["loose"]), 3),
            "sim_trades": len(symbol_trades),
            "sim_win_pct": (round(len(symbol_wins) / len(symbol_trades), 3)
                            if symbol_trades else None),
            "sim_net_pnl": round(sum(t["net_pnl"] for t in symbol_trades)),
        })

    # ── The 20 largest F&O names, every tradeable month ─────────────
    # Same forced protocol as the sheet study, so SBIN/ICICIBANK/TCS etc.
    # are all browsable in the explorer with full walkthroughs.
    top20_universe = {"RELIANCE", "HDFCBANK", "TCS", "BHARTIARTL", "ICICIBANK",
                      "SBIN", "INFY", "HINDUNILVR", "ITC", "LT", "BAJFINANCE",
                      "MARUTI", "HCLTECH", "SUNPHARMA", "KOTAKBANK", "AXISBANK",
                      "ULTRACEMCO", "NTPC", "TITAN", "TATAMOTORS"}
    top20_forced = run_backtest(archive_root, close_store, JUDGED_START, JUDGED_END,
                                stop_key="none", use_earnings_filter=True,
                                capital=5_000_000.0,
                                blackouts_path=REPO_ROOT / "data" / "options_blackouts.yaml",
                                universe=top20_universe, score_floor=0.0,
                                max_positions=len(top20_universe))
    top20_trades_by_symbol: dict[str, list[dict]] = {}
    for trade in sorted(top20_forced["trades"], key=lambda t: t["entry_date"]):
        rounded = {key: (round(value, 4) if isinstance(value, float) else value)
                   for key, value in trade.items()}
        top20_trades_by_symbol.setdefault(trade["symbol"], []).append(rounded)

    # ── The union cross-test: top-20 ∪ his 13 (26 large caps) ──────
    # The "cleanest possible version": strictly large-cap, macro blackouts
    # and earnings months excluded (as everywhere). Two modes as usual.
    union_universe = top20_universe | sheet_universe
    union_rules = run_backtest(archive_root, close_store, JUDGED_START, JUDGED_END,
                               stop_key="none", use_earnings_filter=True,
                               capital=JUDGE_CAPITAL,
                               blackouts_path=REPO_ROOT / "data" / "options_blackouts.yaml",
                               universe=union_universe)
    union_forced = run_backtest(archive_root, close_store, JUDGED_START, JUDGED_END,
                                stop_key="none", use_earnings_filter=True,
                                capital=6_000_000.0,
                                blackouts_path=REPO_ROOT / "data" / "options_blackouts.yaml",
                                universe=union_universe, score_floor=0.0,
                                max_positions=len(union_universe))
    union_trades_by_symbol: dict[str, list[dict]] = {}
    for trade in sorted(union_forced["trades"], key=lambda t: t["entry_date"]):
        rounded = {key: (round(value, 4) if isinstance(value, float) else value)
                   for key, value in trade.items()}
        union_trades_by_symbol.setdefault(trade["symbol"], []).append(rounded)

    payload = {
        "union_study": {
            "n_symbols": len(union_universe),
            "rules_stats": {key: (round(value, 4) if isinstance(value, float) else value)
                            for key, value in summary_stats(union_rules).items()},
            "forced_stats": {key: (round(value, 4) if isinstance(value, float) else value)
                             for key, value in summary_stats(union_forced).items()},
            "per_symbol_net": {symbol: round(sum(t["net_pnl"] for t in trades))
                               for symbol, trades in sorted(union_trades_by_symbol.items())},
            "trades_by_symbol": union_trades_by_symbol,
        },
        "top20_study": {
            "stats": {key: (round(value, 4) if isinstance(value, float) else value)
                      for key, value in summary_stats(top20_forced).items()},
            "trades_by_symbol": top20_trades_by_symbol,
        },
        "sheet_study": {
            "rules_stats": {key: (round(value, 4) if isinstance(value, float) else value)
                            for key, value in summary_stats(sheet_rules).items()},
            "forced_stats": {key: (round(value, 4) if isinstance(value, float) else value)
                             for key, value in summary_stats(sheet_forced).items()},
            "per_stock": per_stock_rows,
            "trades_by_symbol": sheet_trades_by_symbol,
        },
        "generated_at": datetime.date.today().isoformat(),
        "window": {"start": JUDGED_START, "end": JUDGED_END},
        "stats": {key: (round(value, 4) if isinstance(value, float) else value)
                  for key, value in stats.items()},
        "exit_reasons": exit_reasons,
        "breached_trades": sum(1 for t in trades if t["breached"]),
        "cycle_filters": cycle_filter_counts(archive_root),
        "trades_by_symbol": trades_by_symbol,
    }
    out_path = REPO_ROOT / "ui_lambda" / "v2" / "options-data.js"
    out_path.write_text("/* Generated by examples/nse_options_export_ui_data.py"
                        " — do not hand-edit. */\n"
                        "window.OPTIONS_DATA = "
                        + json.dumps(payload, indent=1) + ";\n")
    print(f"wrote {out_path} · {len(trades)} trades · "
          f"{len(trades_by_symbol)} symbols · exits {exit_reasons} · "
          f"cycles {payload['cycle_filters']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
