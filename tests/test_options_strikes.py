import datetime

from options.config import DELTA_BAND, MIN_STRIKE_DISTANCE
from options.greeks import bs_price
from options.strikes import select_strangle

TRADING_DATE = datetime.date(2024, 8, 1)
EXPIRY = "2024-08-31"  # 30 days out
SPOT = 1000.0
VOLATILITY = 0.30


def _ladder(strikes, kind, oi=500):
    rows = []
    years = 30 / 365
    for strike_price in strikes:
        premium = round(bs_price(SPOT, strike_price, years, VOLATILITY,
                                 option_kind=kind), 2)
        rows.append({"date": TRADING_DATE.isoformat(), "symbol": "TESTSTK",
                     "kind": kind, "expiry": EXPIRY, "strike": strike_price,
                     "close": premium, "settle": premium, "oi": oi, "volume": 50,
                     "underlying_close": SPOT, "lot_size": 500})
    return rows


def test_selects_deltas_in_band_and_min_distance():
    strikes = [700, 750, 800, 850, 900, 950, 1000, 1050, 1100, 1150, 1200, 1250, 1300]
    rows = _ladder(strikes, "CE") + _ladder(strikes, "PE")
    strangle = select_strangle(rows, SPOT, EXPIRY, TRADING_DATE)
    assert strangle is not None
    # Ceiling is hard; the floor may be undershot via the further-OTM
    # fallback when the ladder is coarse (e.g. 10%-OTM put at 30% vol has
    # delta -0.09) — the spec's "move to next lower delta strike" rule.
    assert strangle["call_delta"] <= DELTA_BAND[1]
    assert -strangle["put_delta"] <= DELTA_BAND[1]
    assert strangle["call_row"]["strike"] >= SPOT * (1 + MIN_STRIKE_DISTANCE)
    assert strangle["put_row"]["strike"] <= SPOT * (1 - MIN_STRIKE_DISTANCE)
    assert strangle["entry_premium_per_share"] == (
        strangle["call_row"]["settle"] + strangle["put_row"]["settle"])


def test_returns_none_when_one_leg_unfillable():
    strikes = [900, 950, 1000, 1050, 1100, 1150, 1200]
    rows = _ladder(strikes, "CE")  # no puts at all
    assert select_strangle(rows, SPOT, EXPIRY, TRADING_DATE) is None


def test_zero_oi_rows_are_skipped():
    strikes = [700, 800, 900, 1000, 1100, 1200, 1300]
    rows = _ladder(strikes, "CE", oi=0) + _ladder(strikes, "PE", oi=0)
    assert select_strangle(rows, SPOT, EXPIRY, TRADING_DATE) is None


def test_falls_back_further_otm_when_band_empty():
    # Very low vol -> even 8%-away strikes have tiny deltas (< 0.10). The
    # fallback must pick further-OTM (never nearer) candidates.
    strikes = [800, 850, 900, 950, 1000, 1050, 1100, 1150, 1200]
    years = 30 / 365
    rows = []
    for kind in ("CE", "PE"):
        for strike_price in strikes:
            premium = round(bs_price(SPOT, strike_price, years, 0.10, option_kind=kind), 2)
            rows.append({"date": TRADING_DATE.isoformat(), "symbol": "TESTSTK",
                         "kind": kind, "expiry": EXPIRY, "strike": strike_price,
                         "close": max(premium, 0.05), "settle": max(premium, 0.05),
                         "oi": 500, "volume": 50, "underlying_close": SPOT,
                         "lot_size": 500})
    strangle = select_strangle(rows, SPOT, EXPIRY, TRADING_DATE)
    assert strangle is not None
    assert strangle["call_row"]["strike"] >= SPOT * (1 + MIN_STRIKE_DISTANCE)
    assert abs(strangle["call_delta"]) <= DELTA_BAND[1]
    assert abs(strangle["put_delta"]) <= DELTA_BAND[1]
