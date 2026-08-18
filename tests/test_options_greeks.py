import math

import pytest

from options.greeks import bs_price, bs_delta, implied_volatility


# Pinned reference values, hand-derivable with r=0:
# ATM call, S=K=100, T=1y, sigma=0.20, r=0  ->  price 7.9656, delta 0.5398
def test_bs_price_atm_call_zero_rate_reference():
    assert bs_price(100.0, 100.0, 1.0, 0.20, rate=0.0, option_kind="CE") == pytest.approx(7.9656, abs=1e-3)


def test_bs_delta_atm_call_zero_rate_reference():
    assert bs_delta(100.0, 100.0, 1.0, 0.20, rate=0.0, option_kind="CE") == pytest.approx(0.5398, abs=1e-3)


def test_put_call_parity_holds():
    # C - P = S - K*exp(-rT) must hold for any inputs
    spot, strike, years, vol, rate = 950.0, 1000.0, 0.25, 0.35, 0.07
    call = bs_price(spot, strike, years, vol, rate, "CE")
    put = bs_price(spot, strike, years, vol, rate, "PE")
    assert call - put == pytest.approx(spot - strike * math.exp(-rate * years), abs=1e-6)


@pytest.mark.parametrize("volatility", [0.08, 0.20, 0.45, 0.90])
@pytest.mark.parametrize("moneyness", [0.85, 1.0, 1.15])
def test_implied_volatility_roundtrip(volatility, moneyness):
    spot, years, rate = 500.0, 30 / 365, 0.07
    strike = spot * moneyness
    for option_kind in ("CE", "PE"):
        price = bs_price(spot, strike, years, volatility, rate, option_kind)
        recovered = implied_volatility(price, spot, strike, years, rate, option_kind)
        assert recovered == pytest.approx(volatility, abs=1e-4)


def test_implied_volatility_returns_none_for_impossible_price():
    # A call can never cost more than spot; inversion must refuse, not guess.
    assert implied_volatility(600.0, 500.0, 500.0, 0.1, 0.07, "CE") is None
    # Price below intrinsic is equally impossible.
    assert implied_volatility(1.0, 500.0, 400.0, 0.1, 0.07, "CE") is None


def test_pe_delta_is_negative():
    assert -1.0 < bs_delta(500.0, 450.0, 30 / 365, 0.3, 0.07, "PE") < 0.0
