"""SPAN-proxy margin for short strangles (spec §6 documented approximation).

Per short leg: lot × max(20% of spot − OTM amount, 10% of spot). Strangle =
worst leg + a 5%-of-spot exposure add-on for the second leg (exchanges give
netting benefit on the paired position — charging both full legs would
overstate). Calibrate against Kite's margin API in Phase 2 before any paper
sizing decisions depend on it.
"""
from __future__ import annotations


def _leg_margin(spot: float, otm_amount: float, lot_size: int) -> float:
    return lot_size * max(0.20 * spot - otm_amount, 0.10 * spot)


def strangle_margin(spot: float, call_strike: float, put_strike: float,
                    lot_size: int) -> float:
    call_leg = _leg_margin(spot, max(0.0, call_strike - spot), lot_size)
    put_leg = _leg_margin(spot, max(0.0, spot - put_strike), lot_size)
    second_leg_addon = 0.05 * spot * lot_size
    return max(call_leg, put_leg) + second_leg_addon


def lot_size_estimate(known_lot: int | None, spot: float) -> int:
    """UDiFF-era lots pass through; legacy era uses a Rs7.5L-notional
    heuristic rounded to a 25-multiple (NSE's typical granularity)."""
    if known_lot:
        return known_lot
    return max(1, round(750_000.0 / spot / 25.0)) * 25
