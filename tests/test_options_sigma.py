import pytest

from options.sigma import classify_strangle, expected_move, sigma_bands


def test_expected_move_one_year_reference():
    assert expected_move(1000.0, 0.25, 365) == pytest.approx(250.0)


def test_sigma_bands_symmetry():
    bands = sigma_bands(1000.0, 0.30, 30)
    one_sigma_move = expected_move(1000.0, 0.30, 30)
    assert bands["upper_1s"] == pytest.approx(1000.0 + one_sigma_move)
    assert bands["lower_1s"] == pytest.approx(1000.0 - one_sigma_move)
    assert bands["upper_2s"] == pytest.approx(1000.0 + 2 * one_sigma_move)
    assert bands["lower_2s"] == pytest.approx(1000.0 - 2 * one_sigma_move)


def test_classify_all_grades():
    bands = {"lower_1s": 950.0, "upper_1s": 1050.0, "lower_2s": 900.0, "upper_2s": 1100.0}
    assert classify_strangle(bands, call_strike=1150.0, put_strike=850.0) == "A+"
    assert classify_strangle(bands, call_strike=1080.0, put_strike=920.0) == "A"
    assert classify_strangle(bands, call_strike=1080.0, put_strike=980.0) == "B"
    assert classify_strangle(bands, call_strike=1020.0, put_strike=980.0) == "reject"
