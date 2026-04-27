#!/usr/bin/env python3
"""90-day paper-trade clock.

CLAUDE.md absolute rule #1 says "don't push live trading code without 90
days clean paper-trade." Today that's aspirational — there's no concrete
counter, no reset-on-breach behavior, no date you can point at. This
script makes it material.

Each daily cron run we read outputs/paper_equity.csv, classify each day
as clean/dirty using a small set of rules, and emit
`outputs/paper_trade_progress.json` showing:

    {
      "as_of": "2026-04-27",
      "consecutive_clean_days": 8,
      "target_days": 90,
      "progress_pct": 8.9,
      "last_reset_date": "2026-04-19",
      "last_reset_reason": "daily loss -6.20% <= limit -5.00%",
      "today_metrics": {...},
      "current_state": "clean" | "dirty"
    }

A day is "dirty" if any of:
  * daily return below DAILY_LOSS_LIMIT (-5%)
  * drawdown from peak below DRAWDOWN_LIMIT (-20%)
  * portfolio has zero positions (paper system was paused / reset)
  * total_equity is NaN / missing
  * outputs/HALT was set on that date (we look for ALERT_LOG events)

Streak resets to zero on any dirty day. The dashboard reads the JSON
directly via /api/paper_trade_clock to render a "Day N of 90" tile.

Pure functions live up top so the math is testable without I/O.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

# Mirror nse_safety.py's limits so the clock and the kill switch agree on
# what counts as "dirty." Pull-in via import would couple us to qlib —
# better to keep this script pure-stdlib and document the duplication.
DAILY_LOSS_LIMIT = -0.05
DRAWDOWN_LIMIT = -0.20
TARGET_CLEAN_DAYS = 90


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def _to_float(v) -> float | None:
    if v is None or v == "" or v == "nan":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def compute_daily_metrics(rows: list[dict]) -> list[dict]:
    """Annotate equity-history rows with daily_return, peak_equity, drawdown.
    Pure: returns a NEW list, leaves input untouched."""
    out: list[dict] = []
    peak = 0.0
    prev_eq: float | None = None
    for row in rows:
        eq = _to_float(row.get("total_equity"))
        if eq is None:
            out.append({
                **row,
                "_eq": None,
                "_daily_return": None,
                "_peak": peak if peak > 0 else None,
                "_drawdown": None,
            })
            continue
        peak = max(peak, eq)
        daily_return = None if prev_eq in (None, 0) else eq / prev_eq - 1.0
        drawdown = eq / peak - 1.0 if peak > 0 else None
        prev_eq = eq
        out.append({
            **row,
            "_eq": eq,
            "_daily_return": daily_return,
            "_peak": peak,
            "_drawdown": drawdown,
        })
    return out


def classify_day(annotated: dict, *,
                 daily_loss_limit: float = DAILY_LOSS_LIMIT,
                 drawdown_limit: float = DRAWDOWN_LIMIT) -> dict:
    """Return {clean: bool, reason: str | None} for a single annotated row.
    First-day rows (no daily_return) are clean by default — no breach yet."""
    if annotated.get("_eq") is None:
        return {"clean": False, "reason": "missing total_equity"}

    n_positions = _to_float(annotated.get("n_positions"))
    if n_positions is None or n_positions <= 0:
        return {"clean": False, "reason": "no open positions"}

    daily = annotated.get("_daily_return")
    if daily is not None and daily <= daily_loss_limit:
        return {
            "clean": False,
            "reason": (f"daily loss {daily:+.2%} <= limit "
                       f"{daily_loss_limit:+.2%}"),
        }

    drawdown = annotated.get("_drawdown")
    if drawdown is not None and drawdown <= drawdown_limit:
        return {
            "clean": False,
            "reason": (f"drawdown {drawdown:+.2%} <= limit "
                       f"{drawdown_limit:+.2%}"),
        }

    return {"clean": True, "reason": None}


def count_clean_streak(annotated: list[dict],
                       *,
                       halt_dates: set[str] | None = None,
                       daily_loss_limit: float = DAILY_LOSS_LIMIT,
                       drawdown_limit: float = DRAWDOWN_LIMIT) -> dict:
    """Walk backwards from the last row to find the longest consecutive
    clean tail. Halt dates are treated as dirty regardless of metrics."""
    halt_dates = halt_dates or set()
    if not annotated:
        return {
            "consecutive_clean_days": 0,
            "last_reset_date": None,
            "last_reset_reason": None,
            "clean_streak_started": None,
            "current_state": "no_data",
        }

    streak = 0
    streak_started = None
    last_reset_date = None
    last_reset_reason = None

    for row in reversed(annotated):
        date_str = str(row.get("date") or "")
        if date_str in halt_dates:
            verdict = {"clean": False, "reason": "HALT flag fired"}
        else:
            verdict = classify_day(
                row,
                daily_loss_limit=daily_loss_limit,
                drawdown_limit=drawdown_limit,
            )
        if verdict["clean"]:
            streak += 1
            streak_started = date_str  # earliest clean day seen so far
            continue
        # First dirty day encountered while walking back is the most recent reset.
        last_reset_date = date_str
        last_reset_reason = verdict["reason"]
        break

    today_state = "clean" if streak > 0 and last_reset_date != str(annotated[-1].get("date")) else \
        ("dirty" if last_reset_date == str(annotated[-1].get("date")) else "clean")

    return {
        "consecutive_clean_days": streak,
        "last_reset_date": last_reset_date,
        "last_reset_reason": last_reset_reason,
        "clean_streak_started": streak_started,
        "current_state": today_state,
    }


def build_progress(rows: list[dict],
                   *,
                   halt_dates: set[str] | None = None,
                   target_days: int = TARGET_CLEAN_DAYS,
                   daily_loss_limit: float = DAILY_LOSS_LIMIT,
                   drawdown_limit: float = DRAWDOWN_LIMIT,
                   as_of: str | None = None) -> dict:
    """End-to-end builder. Returns the JSON-friendly progress report."""
    annotated = compute_daily_metrics(rows)
    streak = count_clean_streak(
        annotated,
        halt_dates=halt_dates,
        daily_loss_limit=daily_loss_limit,
        drawdown_limit=drawdown_limit,
    )

    today_metrics = None
    if annotated:
        last = annotated[-1]
        today_metrics = {
            "date": last.get("date"),
            "total_equity": last.get("_eq"),
            "daily_return_pct": (
                round(last["_daily_return"] * 100, 4)
                if last.get("_daily_return") is not None else None
            ),
            "drawdown_from_peak_pct": (
                round(last["_drawdown"] * 100, 4)
                if last.get("_drawdown") is not None else None
            ),
            "n_positions": _to_float(last.get("n_positions")),
        }

    n = streak["consecutive_clean_days"]
    return {
        "as_of": as_of or datetime.now(timezone.utc).isoformat(),
        "total_paper_days": len(rows),
        "consecutive_clean_days": n,
        "target_days": target_days,
        "progress_pct": round(n / target_days * 100, 2) if target_days else 0,
        "remaining_days": max(0, target_days - n),
        "last_reset_date": streak["last_reset_date"],
        "last_reset_reason": streak["last_reset_reason"],
        "clean_streak_started": streak["clean_streak_started"],
        "current_state": streak["current_state"],
        "today_metrics": today_metrics,
        "thresholds": {
            "daily_loss_limit_pct": daily_loss_limit * 100,
            "drawdown_limit_pct": drawdown_limit * 100,
            "target_days": target_days,
        },
    }


def parse_halt_dates_from_alerts(alerts_text: str) -> set[str]:
    """Scan outputs/alerts.log for HALT events and extract their dates.
    Format produced by nse_safety.py:
        [2026-04-23T08:15:23] ⛔ Kronos HALTED — daily loss ...
    """
    halts: set[str] = set()
    for line in alerts_text.splitlines():
        if "HALT" not in line:
            continue
        # Look for ISO date prefix [YYYY-MM-DDT...]
        if not line.startswith("["):
            continue
        end = line.find("]")
        if end <= 0:
            continue
        ts = line[1:end]
        date = ts.split("T", 1)[0]
        if len(date) == 10:
            halts.add(date)
    return halts


# ---------------------------------------------------------------------------
# I/O glue
# ---------------------------------------------------------------------------

def _read_csv_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open() as f:
        return list(csv.DictReader(f))


def _read_alerts(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--equity-log", default="outputs/paper_equity.csv")
    p.add_argument("--alerts-log", default="outputs/alerts.log")
    p.add_argument("--output", default="outputs/paper_trade_progress.json")
    p.add_argument("--target-days", type=int, default=TARGET_CLEAN_DAYS)
    args = p.parse_args()

    equity_rows = _read_csv_rows(Path(args.equity_log))
    halt_dates = parse_halt_dates_from_alerts(_read_alerts(Path(args.alerts_log)))

    progress = build_progress(
        equity_rows,
        halt_dates=halt_dates,
        target_days=args.target_days,
    )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(progress, indent=2))

    print(
        f"[clock] day {progress['consecutive_clean_days']} of "
        f"{progress['target_days']} ({progress['progress_pct']}%)  "
        f"state={progress['current_state']}  "
        f"last_reset={progress['last_reset_date'] or 'never'}"
    )


if __name__ == "__main__":
    main()
