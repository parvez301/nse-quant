import pytest

from options.score import trade_score


def test_perfect_inputs_score_100():
    score = trade_score(liquidity_rank=1.0, rsi_value=50.0, call_delta=0.15,
                        put_delta=-0.15, sigma_grade="A+", earnings_clear=True)
    assert score == pytest.approx(100.0)


def test_reject_grade_and_earnings_window_cap_score():
    score = trade_score(liquidity_rank=1.0, rsi_value=50.0, call_delta=0.15,
                        put_delta=-0.15, sigma_grade="reject", earnings_clear=False)
    assert score <= 70.0  # loses all 15 sigma + all 15 earnings points


def test_extreme_rsi_earns_nothing_for_trend():
    calm = trade_score(0.5, 50.0, 0.15, -0.15, "A", True)
    trending = trade_score(0.5, 78.0, 0.15, -0.15, "A", True)
    assert calm - trending == pytest.approx(20.0)


def test_delta_drift_is_penalized():
    ideal = trade_score(0.5, 50.0, 0.15, -0.15, "A", True)
    drifted = trade_score(0.5, 50.0, 0.20, -0.10, "A", True)
    assert ideal > drifted
    assert ideal - drifted == pytest.approx(10.0)


def test_none_rsi_gets_half_trend_points():
    with_rsi = trade_score(0.5, 50.0, 0.15, -0.15, "A", True)
    without_rsi = trade_score(0.5, None, 0.15, -0.15, "A", True)
    assert with_rsi - without_rsi == pytest.approx(10.0)
