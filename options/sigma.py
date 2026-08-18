"""Expected-move bands and the spec's strangle quality grades.

Expected move = spot × IV × sqrt(DTE/365). Grades (spec quality filter):
A+ both strikes outside 2σ, A both outside 1σ, B one inside 1σ, reject both
inside 1σ.
"""
from __future__ import annotations

import math


def expected_move(spot: float, implied_vol: float, days_to_expiry: float) -> float:
    return spot * implied_vol * math.sqrt(days_to_expiry / 365.0)


def sigma_bands(spot: float, implied_vol: float, days_to_expiry: float) -> dict:
    one_sigma = expected_move(spot, implied_vol, days_to_expiry)
    return {
        "lower_1s": spot - one_sigma,
        "upper_1s": spot + one_sigma,
        "lower_2s": spot - 2 * one_sigma,
        "upper_2s": spot + 2 * one_sigma,
    }


def classify_strangle(bands: dict, call_strike: float, put_strike: float) -> str:
    call_outside_1s = call_strike >= bands["upper_1s"]
    put_outside_1s = put_strike <= bands["lower_1s"]
    if call_strike >= bands["upper_2s"] and put_strike <= bands["lower_2s"]:
        return "A+"
    if call_outside_1s and put_outside_1s:
        return "A"
    if call_outside_1s or put_outside_1s:
        return "B"
    return "reject"
