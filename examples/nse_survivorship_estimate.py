#!/usr/bin/env python3
"""Estimate the survivorship-bias penalty in our backtest universe.

Two paths to a number:

A) VISIBLE EXITS (the default — runs on yfinance data we already have)
   For every ticker in the qlib data, find first_date and last_date.
   "Exited" = stopped reporting bars more than 90 days before end of data.
   Apply academic literature scaling to convert the observed annual exit
   rate into an estimated penalty (bps/yr) on the backtest's headline
   return. This is a STRICT LOWER BOUND — yfinance silently drops fully-
   delisted names, so we miss the worst cases.

B) NAMED DELISTINGS (--include-known-delisted)
   Layer in a curated JSON list (data/known_delisted_nse.json) of well-
   documented NSE collapses 2008-2024 that yfinance dropped entirely
   (DHFL, RCOM, RCAP, JET, PUNJLLOYD, ...). Each entry carries an
   approximate total return between first_active_year and last_active_year.
   Adds these as synthetic-zero exits to compute a slightly less-conservative
   penalty range.

For a TRULY corrected number, subscribe to a paid data feed (EOD Historical
Data ~$30/mo or Trendlyne) and use --eod-historical mode in
examples/nse_universe_pit.py to rebuild the universe with delisted tickers
included from source. See README "Honesty checklist" for the full path.

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


def load_known_delisted(path: str | Path) -> list[dict]:
    """Read a curated list of delisted-yet-historically-active NSE names."""
    p = Path(path)
    if not p.exists():
        return []
    payload = json.loads(p.read_text())
    return payload.get("delisted") or []


def named_delisted_penalty(
    known: list[dict],
    *,
    visible_universe_size: int,
    years: float,
) -> dict:
    """Compute the additional headline penalty implied by names yfinance
    dropped entirely. Each named-delisted entry contributes its
    approx_total_return_pct, distributed evenly across the years it was
    active. The penalty is the population-weighted average of the lost
    return that the headline backtest is silently NOT seeing.

    Pure function — easy to test."""
    if not known or visible_universe_size <= 0 or years <= 0:
        return {
            "n_named_delisted": 0,
            "average_total_return_pct": None,
            "annualised_drag_bps": None,
            "implied_extra_universe_pct": 0.0,
        }
    losses = []
    for entry in known:
        ret = entry.get("approx_total_return_pct")
        first = entry.get("first_active_year")
        last = entry.get("last_active_year")
        if ret is None or first is None or last is None or last <= first:
            continue
        active_years = max(1, last - first)
        # Convert peak-to-exit total return into an average annualised drag.
        # We treat the held position as carried for `active_years`, so
        # annualised return ≈ (1+ret/100)^(1/years) - 1.
        try:
            annual = (1 + ret / 100.0) ** (1 / active_years) - 1
        except (ValueError, ZeroDivisionError):
            continue
        losses.append({"ticker": entry.get("ticker"), "annual": annual})

    n = len(losses)
    if n == 0:
        return {
            "n_named_delisted": 0,
            "average_total_return_pct": None,
            "annualised_drag_bps": None,
            "implied_extra_universe_pct": 0.0,
        }

    # Each name "should have been" in the universe. Their absence biases
    # the headline upward by (universe_share * their_negative_annual_return).
    universe_share = n / (visible_universe_size + n)  # they'd be added on top
    avg_annual = sum(loss["annual"] for loss in losses) / n
    annualised_drag_bps = -universe_share * avg_annual * 1e4  # negative * negative = positive penalty
    avg_total_return = sum(
        ((1 + loss["annual"]) ** 1) - 1 for loss in losses
    ) / n  # not used directly, but useful for debug
    return {
        "n_named_delisted": n,
        "average_total_return_pct": round(
            sum(e.get("approx_total_return_pct", 0) for e in known if e.get("approx_total_return_pct") is not None) / n, 2
        ),
        "annualised_drag_bps": round(annualised_drag_bps, 1),
        "implied_extra_universe_pct": round(universe_share * 100, 2),
        "tickers": [loss["ticker"] for loss in losses],
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--provider_uri", default="data/qlib_data/in_data")
    p.add_argument("--out", default="outputs/survivorship_estimate.json")
    p.add_argument(
        "--include-known-delisted", action="store_true",
        help="Also account for hardcoded NSE delistings (DHFL/RCOM/JET/...) "
             "from data/known_delisted_nse.json",
    )
    p.add_argument(
        "--known-delisted-path", default="data/known_delisted_nse.json",
    )
    args = p.parse_args()

    result = compute_from_qlib(args.provider_uri, datetime.utcnow())

    if args.include_known_delisted:
        known = load_known_delisted(args.known_delisted_path)
        named = named_delisted_penalty(
            known,
            visible_universe_size=result["n_universe_total"],
            years=result["years_of_coverage"],
        )
        # Compose: visible-exits penalty range + named-delisted drag.
        visible_low = result["estimated_annual_penalty_bps"]["low"]
        visible_high = result["estimated_annual_penalty_bps"]["high"]
        extra = named.get("annualised_drag_bps") or 0.0
        result["named_delisted"] = named
        result["estimated_annual_penalty_bps_with_named"] = {
            "low": round(visible_low + extra, 1),
            "high": round(visible_high + extra, 1),
        }
        result["interpretation"] += (
            f"\n\nWith {named['n_named_delisted']} hardcoded named delistings "
            f"({', '.join(named.get('tickers', [])[:5])}…) added on top, the "
            f"penalty range widens to "
            f"{result['estimated_annual_penalty_bps_with_named']['low']:.0f}-"
            f"{result['estimated_annual_penalty_bps_with_named']['high']:.0f} bps/year. "
            "Still a lower bound — paid data (EOD Historical Data) would "
            "include all delistings, not just the famous ones."
        )

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=2, default=str))
    print(f"[survivorship] wrote {args.out}")
    print(f"[survivorship] {result['interpretation']}")


if __name__ == "__main__":
    main()
