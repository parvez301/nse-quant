import datetime
import pathlib

from options.filters import (in_blackout, in_earnings_window, load_blackouts,
                             rsi_regime)

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_rsi_regime_boundaries():
    assert rsi_regime(55.1) == "bullish"
    assert rsi_regime(44.9) == "bearish"
    assert rsi_regime(45.0) == "neutral"
    assert rsi_regime(55.0) == "neutral"
    assert rsi_regime(None) == "neutral"


def test_earnings_window_hits_mid_april_cycle():
    # Q4 (Mar 31) results window = Apr 7 .. May 15
    assert in_earnings_window(datetime.date(2024, 4, 5), datetime.date(2024, 4, 30)) is True


def test_earnings_window_clear_for_late_feb_march():
    assert in_earnings_window(datetime.date(2024, 2, 16), datetime.date(2024, 3, 26)) is False


def test_blackouts_load_and_overlap():
    blackout_ranges = load_blackouts(REPO_ROOT / "data" / "options_blackouts.yaml")
    assert blackout_ranges, "blackout calendar should not be empty"
    # 2024 general election window
    assert in_blackout(datetime.date(2024, 5, 1), datetime.date(2024, 5, 28),
                       blackout_ranges) is True
    assert in_blackout(datetime.date(2023, 8, 1), datetime.date(2023, 8, 28),
                       blackout_ranges) is False
