#!/usr/bin/env python3
"""Estimate the survivorship-bias penalty in our backtest universe.

We can't recover fully-delisted stocks (yfinance drops them), but we CAN see
stocks that stopped trading inside our window — names that had data once and
then went silent. That gives a *lower bound* on how much survivorship bias
inflates the backtest.

Method:
  1. For every ticker in the qlib data, find first_date and last_date.
  2. Bucket tickers by "exit year" (last_date.year if last_date < today - 90 days).
  3. Count "silent" tickers per year vs. "active" tickers.
  4. Estimate the upward bias on a backtest that only sees survivors using
     a rough literature-based scaling: each 1% of universe that exits per year
     adds ~0.4-0.6% to backtest annual return (cf. Brown/Goetzmann 1995, Carhart
     et al 2002 for US mutual funds; Indian markets show similar order of mag).

Output: outputs/survivorship_estimate.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path


def compute_from_qlib(provider_uri: str, today: datetime) -> dict:
    import qlib
    from qlib.data import D

    qlib.init(provider_uri=str(Path(provider_uri).expanduser()), region="cn")
    instruments = D.list_instruments(D.instruments(market="all"), as_list=True)
    instruments = [s for s in instruments if s not in ("NIFTY50", "SENSEX")]

    df = D.features(instruments, ["$close"], freq="day")
    if df.empty:
        raise SystemExit("[abort] empty features dataframe — qlib data not loaded")

    # Per-ticker first/last bar
    grouped = df.groupby(level="instrument")["$close"]
    bounds = grouped.agg(first_date="first", last_date="last")

    # Use the calendar's actual range so we don't penalise unfilled tickers
    cal = D.calendar(start_time="2005-01-01")
    universe_first = cal[0]
    universe_last = cal[-1]

    bounds["first_date"] = grouped.apply(lambda s: s.dropna().index.get_level_values("datetime").min())
    bounds["last_date"]  = grouped.apply(lambda s: s.dropna().index.get_level_values("datetime").max())

    # An "exit" = last bar more than 90 days before today's end-of-data.
    cutoff = universe_last - timedelta(days=90)
    bounds["exited"] = bounds["last_date"] < cutoff

    n_total = len(bounds)
    n_exited = int(bounds["exited"].sum())
    exit_rate = n_exited / n_total if n_total else 0.0

    # Per-year exit count (for visibility)
    exited_only = bounds[bounds["exited"]]
    by_year = (
        exited_only.assign(exit_year=lambda d: d["last_date"].dt.year)
                   .groupby("exit_year")
                   .size()
                   .sort_index()
    )

    # Years of universe coverage
    years = (universe_last - universe_first).days / 365.25

    # Annual exit rate
    annual_exit_rate = exit_rate / years if years > 0 else 0.0

    # Penalty range — academic literature anchors
    # Brown/Goetzmann 1995, Carhart 2002 for US: ~0.5%/yr from 1.5-2% annual exit rate
    # Indian markets: similar order, but our visible exit rate is a lower bound
    # because yfinance drops fully-delisted names entirely
    penalty_low_bps  = annual_exit_rate * 0.40 * 10000  # conservative scaling
    penalty_high_bps = annual_exit_rate * 0.80 * 10000  # aggressive scaling

    return {
        "method": "qlib-visible-exits",
        "n_universe_total": n_total,
        "n_exited_visible": n_exited,
        "exit_rate_observed": round(exit_rate, 4),
        "annual_exit_rate_observed": round(annual_exit_rate, 4),
        "years_of_coverage": round(years, 2),
        "exits_by_year": {int(k): int(v) for k, v in by_year.items()},
        "estimated_annual_penalty_bps": {
            "low":  round(penalty_low_bps, 1),
            "high": round(penalty_high_bps, 1),
        },
        "interpretation": (
            f"Of {n_total} visible tickers, {n_exited} ({exit_rate:.1%}) stopped trading "
            f"inside the {years:.1f}-year window — an annual exit rate of "
            f"{annual_exit_rate:.2%}. Applying literature-based scaling, the survivorship "
            f"penalty on the headline backtest is approximately "
            f"{penalty_low_bps:.0f}-{penalty_high_bps:.0f} bps/year. "
            "This is a LOWER bound — yfinance silently drops fully-delisted names, "
            "which we can't see at all. The true penalty is likely 1.5-3x this range."
        ),
        "caveats": [
            "yfinance drops fully-delisted tickers — we only count names that "
            "still appear in our universe but stopped reporting bars.",
            "Literature scaling (0.40-0.80x exit rate) is from US fund studies; "
            "Indian micro/small-cap delisting dynamics may differ.",
            "An exit could also be a name that merged (true delisting) vs. one "
            "that suspended trading temporarily. We don't differentiate here.",
        ],
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--provider_uri", default="data/qlib_data/in_data")
    p.add_argument("--out", default="outputs/survivorship_estimate.json")
    args = p.parse_args()

    result = compute_from_qlib(args.provider_uri, datetime.utcnow())
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=2, default=str))
    print(f"[survivorship] wrote {args.out}")
    print(f"[survivorship] {result['interpretation']}")


if __name__ == "__main__":
    main()
