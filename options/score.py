"""0-100 trade score (prompts doc "Trade Scoring System"): liquidity 25,
RSI trend 20, delta quality 25, sigma distance 15, earnings distance 15.
Only trades scoring >= SCORE_FLOOR (75) are entered."""
from __future__ import annotations

from options.config import IDEAL_DELTA

_SIGMA_GRADE_POINTS = {"A+": 15.0, "A": 10.0, "B": 5.0, "reject": 0.0}


def trade_score(liquidity_rank: float, rsi_value: float | None,
                call_delta: float, put_delta: float, sigma_grade: str,
                earnings_clear: bool) -> float:
    liquidity_points = 25.0 * max(0.0, min(1.0, liquidity_rank))
    if rsi_value is None:
        trend_points = 10.0
    else:
        trend_points = max(0.0, 20.0 - 0.8 * abs(rsi_value - 50.0))
    delta_points = sum(max(0.0, 12.5 - 100.0 * abs(abs(leg_delta) - IDEAL_DELTA))
                       for leg_delta in (call_delta, put_delta))
    sigma_points = _SIGMA_GRADE_POINTS.get(sigma_grade, 0.0)
    earnings_points = 15.0 if earnings_clear else 0.0
    return liquidity_points + trend_points + delta_points + sigma_points + earnings_points
