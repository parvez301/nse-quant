import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "examples"))
from nse_options_backtest import evaluate_criteria

PASSING_STATS = {"cagr": 0.15, "sharpe": 1.4, "max_drawdown": 0.12,
                 "t_stat_excess": 2.7, "n_months": 42}


def test_all_criteria_pass():
    verdict = evaluate_criteria(PASSING_STATS, covid_floor_fraction=0.85,
                                nifty_sharpe=0.9)
    assert verdict["verdict"] == "PASS"
    assert all(c["passed"] for c in verdict["criteria"].values())


def test_single_failure_fails_the_judge():
    stats = dict(PASSING_STATS, max_drawdown=0.45)
    verdict = evaluate_criteria(stats, covid_floor_fraction=0.85, nifty_sharpe=0.9)
    assert verdict["verdict"] == "FAIL"
    assert verdict["criteria"]["max_drawdown_below_30pct"]["passed"] is False


def test_covid_floor_breach_fails():
    verdict = evaluate_criteria(PASSING_STATS, covid_floor_fraction=0.55,
                                nifty_sharpe=0.9)
    assert verdict["verdict"] == "FAIL"


def test_missing_nifty_marks_criterion_unavailable_not_pass():
    verdict = evaluate_criteria(PASSING_STATS, covid_floor_fraction=0.85,
                                nifty_sharpe=None)
    assert verdict["criteria"]["sharpe_beats_nifty"]["passed"] == "unavailable"
    assert verdict["verdict"] == "FAIL"  # unavailable evidence can never PASS


def test_thin_judged_window_is_error():
    stats = dict(PASSING_STATS, n_months=8)
    verdict = evaluate_criteria(stats, covid_floor_fraction=0.85, nifty_sharpe=0.9)
    assert verdict["verdict"] == "ERROR"
