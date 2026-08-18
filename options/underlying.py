"""Spot resolution and price-series indicators for the strangle engine.

Spot in rupees ALWAYS comes from the F&O archive itself (UndrlygPric in the
UDiFF era, near-month futures settle before that) — the qlib store's closes
are back-adjusted (splits/bonuses/dividends) and must never be compared to
option strikes. qlib closes feed only scale-invariant indicators: RSI(14)
and historical volatility.
"""
from __future__ import annotations

import math
import pathlib

import numpy as np


def spot_for_symbol(day_rows: list[dict]) -> float | None:
    """Rows must already be filtered to one symbol on one trading day."""
    for row in day_rows:
        if row.get("underlying_close"):
            return row["underlying_close"]
    future_rows = [row for row in day_rows if row["kind"] == "FUT" and row["settle"]]
    if not future_rows:
        return None
    nearest_future = min(future_rows, key=lambda row: row["expiry"])
    return nearest_future["settle"]


class AdjustedCloseStore:
    """Reads qlib's binary close series (calendar-aligned float32)."""

    def __init__(self, qlib_root: pathlib.Path):
        self._features_dir = pathlib.Path(qlib_root) / "features"
        calendar_path = pathlib.Path(qlib_root) / "calendars" / "day.txt"
        self._calendar = [line.strip() for line in calendar_path.read_text().splitlines()
                          if line.strip()]

    def closes_upto(self, symbol: str, iso_date: str) -> list[float]:
        close_path = self._features_dir / symbol.lower() / "close.day.bin"
        if not close_path.exists():
            return []
        raw = np.fromfile(close_path, dtype="<f4")
        if raw.size < 2:
            return []
        start_index = int(raw[0])
        values = raw[1:]
        closes: list[float] = []
        for offset, value in enumerate(values):
            calendar_index = start_index + offset
            if calendar_index >= len(self._calendar) or self._calendar[calendar_index] > iso_date:
                break
            if not math.isnan(value):
                closes.append(float(value))
        return closes


def rsi14(closes: list[float]) -> float | None:
    """Wilder-smoothed 14-period RSI over the full series."""
    period = 14
    if len(closes) < period + 1:
        return None
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]
    average_gain = sum(gains[:period]) / period
    average_loss = sum(losses[:period]) / period
    for gain, loss in zip(gains[period:], losses[period:]):
        average_gain = (average_gain * (period - 1) + gain) / period
        average_loss = (average_loss * (period - 1) + loss) / period
    if average_loss == 0:
        return 100.0
    relative_strength = average_gain / average_loss
    return 100.0 - 100.0 / (1.0 + relative_strength)


def historical_volatility(closes: list[float], window: int = 20) -> float | None:
    """Annualized std-dev of log returns over the trailing `window` returns."""
    if len(closes) < window + 1:
        return None
    recent_closes = closes[-(window + 1):]
    log_returns = [math.log(later / earlier)
                   for earlier, later in zip(recent_closes, recent_closes[1:])
                   if earlier > 0 and later > 0]
    if len(log_returns) < window:
        return None
    mean_return = sum(log_returns) / len(log_returns)
    variance = sum((value - mean_return) ** 2 for value in log_returns) / (len(log_returns) - 1)
    return math.sqrt(variance) * math.sqrt(252.0)
