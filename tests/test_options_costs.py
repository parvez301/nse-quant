import pytest

from options.costs import (leg_transaction_costs, strangle_entry_costs,
                           strangle_exit_costs)
from options.margin import lot_size_estimate, strangle_margin


def test_sell_leg_itemized_breakdown_pinned():
    # premium_value 10,000 (20/share x 500), sell, calm market
    breakdown = leg_transaction_costs(premium_value=10_000.0, is_sell=True,
                                      stressed=False, premium_per_share=20.0,
                                      lot_size=500)
    assert breakdown["brokerage"] == pytest.approx(20.0)
    assert breakdown["stt"] == pytest.approx(10.0)          # 0.1% sell premium
    assert breakdown["exchange"] == pytest.approx(5.30)     # 0.053%
    assert breakdown["gst"] == pytest.approx(4.554)         # 18% of (brok+exch)
    assert breakdown["sebi"] == pytest.approx(0.01)         # Rs10/crore
    assert breakdown["stamp"] == pytest.approx(0.0)         # buys only
    assert breakdown["slippage"] == pytest.approx(150.0)    # 0.015*20/share * 500
    assert breakdown["total"] == pytest.approx(189.864)


def test_buy_leg_swaps_stt_for_stamp():
    breakdown = leg_transaction_costs(10_000.0, is_sell=False, stressed=False,
                                      premium_per_share=20.0, lot_size=500)
    assert breakdown["stt"] == pytest.approx(0.0)
    assert breakdown["stamp"] == pytest.approx(0.30)  # 0.003%


def test_stressed_exit_doubles_slippage():
    calm = leg_transaction_costs(10_000.0, False, False, 20.0, 500)
    stressed = leg_transaction_costs(10_000.0, False, True, 20.0, 500)
    assert stressed["slippage"] == pytest.approx(2 * calm["slippage"])


def test_slippage_floor_applies_to_tiny_premiums():
    breakdown = leg_transaction_costs(500.0, True, False, premium_per_share=1.0,
                                      lot_size=500)
    assert breakdown["slippage"] == pytest.approx(0.05 * 500)


def test_strangle_wrappers_sum_two_legs():
    entry_total = strangle_entry_costs(10_000.0, 8_000.0, 20.0, 16.0, 500)
    single_call = leg_transaction_costs(10_000.0, True, False, 20.0, 500)["total"]
    single_put = leg_transaction_costs(8_000.0, True, False, 16.0, 500)["total"]
    assert entry_total == pytest.approx(single_call + single_put)
    exit_total = strangle_exit_costs(5_000.0, 4_000.0, 10.0, 8.0, 500, stressed=True)
    assert exit_total > 0


def test_strangle_margin_pinned():
    # spot 1000, strikes 1100/900, lot 500:
    # each leg: 500 * max(0.20*1000 - 100, 0.10*1000) = 500*100 = 50,000
    # strangle = max legs + 0.05*1000*500 = 50,000 + 25,000 = 75,000
    assert strangle_margin(1000.0, 1100.0, 900.0, 500) == pytest.approx(75_000.0)


def test_margin_floor_engages_deep_otm():
    # strikes 40% away: 0.20*spot - 400 < 0 -> floor 0.10*spot rules
    assert strangle_margin(1000.0, 1400.0, 600.0, 500) == pytest.approx(
        500 * 100.0 + 25_000.0)


def test_lot_size_estimate():
    assert lot_size_estimate(250, 3000.0) == 250            # known passes through
    assert lot_size_estimate(None, 1000.0) == 750           # 7.5L/1000 -> 750
    assert lot_size_estimate(None, 30_000.0) == 25          # rounds to 25-multiple
