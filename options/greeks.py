"""Black-Scholes pricing, delta, and implied-volatility inversion.

Stdlib only. Used on EOD settle prices where NSE publishes no IV; spot is
the equity close (UndrlygPric where the UDiFF file carries it). r defaults
to 0.07 (approx. repo-rate regime average) per the Phase 0 spec — a
documented approximation, not a curve.
"""
from __future__ import annotations

import math

_MIN_VOLATILITY = 0.01
_MAX_VOLATILITY = 5.0


def _norm_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _d1_d2(spot, strike, years_to_expiry, volatility, rate):
    vol_sqrt_t = volatility * math.sqrt(years_to_expiry)
    d1 = (math.log(spot / strike) + (rate + 0.5 * volatility ** 2) * years_to_expiry) / vol_sqrt_t
    return d1, d1 - vol_sqrt_t


def bs_price(spot: float, strike: float, years_to_expiry: float,
             volatility: float, rate: float = 0.07, option_kind: str = "CE") -> float:
    d1, d2 = _d1_d2(spot, strike, years_to_expiry, volatility, rate)
    discounted_strike = strike * math.exp(-rate * years_to_expiry)
    if option_kind == "CE":
        return spot * _norm_cdf(d1) - discounted_strike * _norm_cdf(d2)
    return discounted_strike * _norm_cdf(-d2) - spot * _norm_cdf(-d1)


def bs_delta(spot: float, strike: float, years_to_expiry: float,
             volatility: float, rate: float = 0.07, option_kind: str = "CE") -> float:
    d1, _ = _d1_d2(spot, strike, years_to_expiry, volatility, rate)
    call_delta = _norm_cdf(d1)
    return call_delta if option_kind == "CE" else call_delta - 1.0


def implied_volatility(option_price: float, spot: float, strike: float,
                       years_to_expiry: float, rate: float = 0.07,
                       option_kind: str = "CE") -> float | None:
    """Bisection on [0.01, 5.0]. Returns None when the price is outside the
    range any such volatility can produce (spec: refuse, never guess)."""
    if option_price <= 0 or spot <= 0 or years_to_expiry <= 0:
        return None
    price_at_low = bs_price(spot, strike, years_to_expiry, _MIN_VOLATILITY, rate, option_kind)
    price_at_high = bs_price(spot, strike, years_to_expiry, _MAX_VOLATILITY, rate, option_kind)
    if not (price_at_low <= option_price <= price_at_high):
        return None
    low, high = _MIN_VOLATILITY, _MAX_VOLATILITY
    for _ in range(100):
        mid = 0.5 * (low + high)
        if bs_price(spot, strike, years_to_expiry, mid, rate, option_kind) < option_price:
            low = mid
        else:
            high = mid
    return 0.5 * (low + high)
