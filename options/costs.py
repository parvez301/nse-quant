"""Zerodha-retail cost model for option legs (spec §6).

Rates: brokerage flat Rs20/order; STT 0.1% of premium on SELLS (time-exits
avoid the 0.125%-of-intrinsic exercise STT by construction); NSE transaction
charge 0.053% of premium; GST 18% on (brokerage + exchange); SEBI Rs10/crore;
stamp duty 0.003% on BUYS. Slippage: half the modeled bid-ask spread —
max(Rs0.05, 1.5% of premium)/share — doubled on stressed (stop-loss) exits,
where books are one-sided.
"""
from __future__ import annotations

_BROKERAGE_PER_ORDER = 20.0
_STT_SELL_RATE = 0.001
_EXCHANGE_RATE = 0.00053
_GST_RATE = 0.18
_SEBI_RATE = 10.0 / 1e7
_STAMP_BUY_RATE = 0.00003
_HALF_SPREAD_FRACTION = 0.015
_HALF_SPREAD_FLOOR = 0.05


def leg_transaction_costs(premium_value: float, is_sell: bool, stressed: bool,
                          premium_per_share: float, lot_size: int) -> dict:
    brokerage = _BROKERAGE_PER_ORDER
    stt = _STT_SELL_RATE * premium_value if is_sell else 0.0
    exchange = _EXCHANGE_RATE * premium_value
    gst = _GST_RATE * (brokerage + exchange)
    sebi = _SEBI_RATE * premium_value
    stamp = 0.0 if is_sell else _STAMP_BUY_RATE * premium_value
    half_spread_per_share = max(_HALF_SPREAD_FLOOR,
                                _HALF_SPREAD_FRACTION * premium_per_share)
    slippage = half_spread_per_share * lot_size * (2.0 if stressed else 1.0)
    total = brokerage + stt + exchange + gst + sebi + stamp + slippage
    return {"brokerage": brokerage, "stt": stt, "exchange": exchange,
            "gst": gst, "sebi": sebi, "stamp": stamp, "slippage": slippage,
            "total": total}


def strangle_entry_costs(call_value: float, put_value: float,
                         call_per_share: float, put_per_share: float,
                         lot_size: int) -> float:
    call_costs = leg_transaction_costs(call_value, True, False, call_per_share, lot_size)
    put_costs = leg_transaction_costs(put_value, True, False, put_per_share, lot_size)
    return call_costs["total"] + put_costs["total"]


def strangle_exit_costs(call_value: float, put_value: float,
                        call_per_share: float, put_per_share: float,
                        lot_size: int, stressed: bool = False) -> float:
    call_costs = leg_transaction_costs(call_value, False, stressed, call_per_share, lot_size)
    put_costs = leg_transaction_costs(put_value, False, stressed, put_per_share, lot_size)
    return call_costs["total"] + put_costs["total"]
