"""Delta-based strangle strike selection (spec §6 / prompts doc "Delta-Based
Strike Selection").

Per leg: candidates need settle > 0, OI > 0, a converging IV, |delta| within
DELTA_BAND, and strike distance from spot >= MIN_STRIKE_DISTANCE; the winner
is the |delta| nearest IDEAL_DELTA. When the band yields nothing (calm
regimes push all 8%-away strikes below 0.10 delta), fall back to the
nearest-to-ideal candidate that is FURTHER out (|delta| < band floor) —
never nearer to the money than 8%.
"""
from __future__ import annotations

import datetime

from options.config import (DELTA_BAND, IDEAL_DELTA, MIN_STRIKE_DISTANCE,
                            RISK_FREE_RATE)
from options.greeks import bs_delta, implied_volatility


def _leg_candidates(rows: list[dict], kind: str, spot: float, expiry: str,
                    trading_date: datetime.date) -> list[dict]:
    days_to_expiry = (datetime.date.fromisoformat(expiry) - trading_date).days
    years_to_expiry = max(days_to_expiry, 1) / 365.0
    candidates = []
    for row in rows:
        if row["kind"] != kind or row["expiry"] != expiry:
            continue
        if not row["settle"] or row["settle"] <= 0 or row["oi"] <= 0:
            continue
        distance_fraction = ((row["strike"] - spot) / spot if kind == "CE"
                             else (spot - row["strike"]) / spot)
        if distance_fraction < MIN_STRIKE_DISTANCE:
            continue
        leg_iv = implied_volatility(row["settle"], spot, row["strike"],
                                    years_to_expiry, RISK_FREE_RATE, kind)
        if leg_iv is None:
            continue
        leg_delta = bs_delta(spot, row["strike"], years_to_expiry, leg_iv,
                             RISK_FREE_RATE, kind)
        candidates.append({"row": row, "delta": leg_delta, "iv": leg_iv})
    return candidates


def _pick_leg(candidates: list[dict]) -> dict | None:
    in_band = [c for c in candidates if DELTA_BAND[0] <= abs(c["delta"]) <= DELTA_BAND[1]]
    if in_band:
        return min(in_band, key=lambda c: abs(abs(c["delta"]) - IDEAL_DELTA))
    further_otm = [c for c in candidates if abs(c["delta"]) < DELTA_BAND[0]]
    if further_otm:
        return min(further_otm, key=lambda c: abs(abs(c["delta"]) - IDEAL_DELTA))
    return None


def select_strangle(symbol_day_rows: list[dict], spot: float, expiry: str,
                    trading_date: datetime.date) -> dict | None:
    call_leg = _pick_leg(_leg_candidates(symbol_day_rows, "CE", spot, expiry, trading_date))
    put_leg = _pick_leg(_leg_candidates(symbol_day_rows, "PE", spot, expiry, trading_date))
    if call_leg is None or put_leg is None:
        return None
    return {
        "call_row": call_leg["row"], "put_row": put_leg["row"],
        "call_delta": call_leg["delta"], "put_delta": put_leg["delta"],
        "call_iv": call_leg["iv"], "put_iv": put_leg["iv"],
        "entry_premium_per_share": call_leg["row"]["settle"] + put_leg["row"]["settle"],
    }
