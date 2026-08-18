#!/usr/bin/env python3
"""Clean-26 live tracker — recomputed on a 4-hour schedule in the cloud.

Simulates the DSRD short-strangle strategy on the 26 large caps (top-20 by
market cap + the 13 from the shared spreadsheet) over the TRAILING 24
months, with the EXTENDED macro-event calendar (wars, pandemics, shocks,
budgets, elections) plus quarterly-results exclusion. Capital Rs10,00,000.

Writes outputs/options/clean_tracker.json for the dashboard's live card.
Note: NSE publishes F&O settle data once per evening — intra-day runs
refresh the timestamp; numbers change when a new trading day lands.
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
from options.filters import in_blackout, in_earnings_window, load_blackouts  # noqa: E402
from options.underlying import AdjustedCloseStore  # noqa: E402

UNION26 = sorted({"RELIANCE", "HDFCBANK", "TCS", "BHARTIARTL", "ICICIBANK",
                  "SBIN", "INFY", "HINDUNILVR", "ITC", "LT", "BAJFINANCE",
                  "MARUTI", "HCLTECH", "SUNPHARMA", "KOTAKBANK", "AXISBANK",
                  "ULTRACEMCO", "NTPC", "TITAN", "TATAMOTORS", "SBICARD",
                  "TATACONSUM", "AMBUJACEM", "ASIANPAINT", "TATASTEEL",
                  "GRASIM"})
CAPITAL = 1_000_000.0


def main() -> int:
    archive_root = REPO_ROOT / "data" / "fo_bhavcopy"
    blackouts_path = REPO_ROOT / "data" / "options_blackouts_extended.yaml"
    today = datetime.date.today()
    start_date = today.replace(day=1) - datetime.timedelta(days=730)
    start_iso, end_iso = start_date.isoformat(), today.isoformat()

    trading_days = _archive_days(archive_root, start_iso, end_iso)
    if not trading_days:
        print("no archive data in window — aborting")
        return 1
    expiries = monthly_expiry_dates(archive_root, start_iso, end_iso)
    cycles = build_cycles(expiries, trading_days)
    blackout_ranges = load_blackouts(blackouts_path)
    counts = {"total": len(cycles), "macro": 0, "earnings": 0, "clean": 0}
    for cycle in cycles:
        entry = datetime.date.fromisoformat(cycle["entry_date"])
        expiry = datetime.date.fromisoformat(cycle["expiry"])
        if in_blackout(entry, expiry, blackout_ranges):
            counts["macro"] += 1
        elif in_earnings_window(entry, expiry):
            counts["earnings"] += 1
        else:
            counts["clean"] += 1

    close_store = AdjustedCloseStore(REPO_ROOT / "data" / "qlib_data" / "in_data")
    common = dict(archive_root=archive_root, close_store=close_store,
                  start_iso=start_iso, end_iso=end_iso, stop_key="none",
                  use_earnings_filter=True, blackouts_path=blackouts_path,
                  universe=set(UNION26), capital=CAPITAL)
    rules_result = run_backtest(**common)
    fill_result = run_backtest(score_floor=0.0, max_positions=len(UNION26), **common)

    per_stock = []
    fill_by_symbol: dict[str, list[dict]] = {}
    for trade in sorted(fill_result["trades"], key=lambda t: t["entry_date"]):
        rounded_trade = {key: (round(value, 4) if isinstance(value, float) else value)
                         for key, value in trade.items()}
        fill_by_symbol.setdefault(trade["symbol"], []).append(rounded_trade)
    for symbol in UNION26:
        trades = fill_by_symbol.get(symbol, [])
        wins = [t for t in trades if t["net_pnl"] > 0]
        per_stock.append({
            "symbol": symbol, "trades": len(trades), "wins": len(wins),
            "net_pnl": round(sum(t["net_pnl"] for t in trades)),
            "breaches": sum(1 for t in trades if t["breached"]),
            "last_exit": trades[-1]["exit_date"] if trades else None,
        })

    def rounded_stats(result: dict) -> dict:
        return {key: (round(value, 4) if isinstance(value, float) else value)
                for key, value in summary_stats(result).items()}

    import yaml
    calendar = yaml.safe_load(blackouts_path.read_text())["blackouts"]
    window_events = []
    for entry in calendar:
        event_start = datetime.date.fromisoformat(str(entry["start"]))
        event_end = datetime.date.fromisoformat(str(entry["end"]))
        window_events.append({"start": event_start.isoformat(),
                              "end": event_end.isoformat(),
                              "reason": entry["reason"],
                              "in_window": event_end >= start_date})

    payload = {
        "generated_at_utc": datetime.datetime.now(datetime.timezone.utc)
                            .strftime("%Y-%m-%d %H:%M UTC"),
        "window": {"start": start_iso, "end": end_iso},
        "capital": CAPITAL,
        "universe": UNION26,
        "excluded_events": window_events,
        "cycles": counts,
        "rules_stats": rounded_stats(rules_result),
        "fill_stats": rounded_stats(fill_result),
        "fill_final_equity": round(fill_result["equity_curve"][-1][1])
                             if fill_result["equity_curve"] else CAPITAL,
        "rules_final_equity": round(rules_result["equity_curve"][-1][1])
                              if rules_result["equity_curve"] else CAPITAL,
        "per_stock": per_stock,
        "trades_by_symbol": fill_by_symbol,
        "last_archive_day": trading_days[-1],
    }
    out_path = REPO_ROOT / "outputs" / "options" / "clean_tracker.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=1))
    print(f"wrote {out_path} · window {start_iso}->{end_iso} · cycles {counts} · "
          f"rules ₹{payload['rules_final_equity']:,} · fill ₹{payload['fill_final_equity']:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
