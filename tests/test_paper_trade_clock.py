"""Tests for nse_paper_trade_clock — the 90-day clock that enforces
CLAUDE.md absolute rule #1.

The pure helpers carry the contract: walk equity history, classify each
day, count the consecutive clean tail, reset on breach.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "examples"))

import nse_paper_trade_clock as mod


# -----------------------------------------------------------------------------
# compute_daily_metrics
# -----------------------------------------------------------------------------

def test_metrics_first_day_has_no_daily_return():
    rows = [{"date": "2026-04-23", "total_equity": "1000000", "n_positions": "5"}]
    out = mod.compute_daily_metrics(rows)
    assert out[0]["_eq"] == 1_000_000.0
    assert out[0]["_daily_return"] is None
    assert out[0]["_peak"] == 1_000_000.0
    assert out[0]["_drawdown"] == 0.0


def test_metrics_tracks_peak_and_drawdown():
    rows = [
        {"date": "2026-04-23", "total_equity": "1000000", "n_positions": "20"},
        {"date": "2026-04-24", "total_equity": "1100000", "n_positions": "20"},
        {"date": "2026-04-25", "total_equity":  "990000", "n_positions": "20"},
    ]
    out = mod.compute_daily_metrics(rows)
    assert out[1]["_peak"] == 1_100_000.0
    assert out[1]["_drawdown"] == 0.0
    # Day 3: 990000 / 1100000 - 1 = -0.10
    assert abs(out[2]["_drawdown"] - (-0.10)) < 1e-9
    assert abs(out[2]["_daily_return"] - (-0.10)) < 1e-9


def test_metrics_skips_nan_rows_gracefully():
    rows = [
        {"date": "2026-04-23", "total_equity": "1000000", "n_positions": "20"},
        {"date": "2026-04-24", "total_equity": "",        "n_positions": "20"},
    ]
    out = mod.compute_daily_metrics(rows)
    assert out[1]["_eq"] is None


# -----------------------------------------------------------------------------
# classify_day
# -----------------------------------------------------------------------------

def test_classify_clean_day():
    row = {"_eq": 100, "_daily_return": -0.01, "_drawdown": -0.01,
           "n_positions": "20"}
    out = mod.classify_day(row)
    assert out == {"clean": True, "reason": None}


def test_classify_dirty_when_daily_loss_breach():
    row = {"_eq": 100, "_daily_return": -0.06, "_drawdown": -0.06,
           "n_positions": "20"}
    out = mod.classify_day(row)
    assert out["clean"] is False
    assert "daily loss" in out["reason"]


def test_classify_dirty_when_drawdown_breach():
    row = {"_eq": 100, "_daily_return": -0.02, "_drawdown": -0.25,
           "n_positions": "20"}
    out = mod.classify_day(row)
    assert out["clean"] is False
    assert "drawdown" in out["reason"]


def test_classify_dirty_when_no_positions():
    row = {"_eq": 100, "_daily_return": -0.01, "_drawdown": -0.01,
           "n_positions": "0"}
    out = mod.classify_day(row)
    assert out["clean"] is False
    assert "positions" in out["reason"]


def test_classify_dirty_when_equity_missing():
    row = {"_eq": None, "n_positions": "20"}
    out = mod.classify_day(row)
    assert out["clean"] is False


def test_classify_first_day_with_no_daily_return_is_clean():
    """Initial day in the equity log has no prior day to compare against;
    it should be clean by default if positions are open and equity is real."""
    row = {"_eq": 1_000_000, "_daily_return": None, "_drawdown": 0.0,
           "n_positions": "20"}
    out = mod.classify_day(row)
    assert out["clean"] is True


# -----------------------------------------------------------------------------
# count_clean_streak
# -----------------------------------------------------------------------------

def _annotate(rows):
    return mod.compute_daily_metrics(rows)


def test_streak_three_clean_in_a_row():
    rows = [
        {"date": "2026-04-21", "total_equity": "1000000", "n_positions": "20"},
        {"date": "2026-04-22", "total_equity": "1010000", "n_positions": "20"},
        {"date": "2026-04-23", "total_equity": "1020000", "n_positions": "20"},
    ]
    streak = mod.count_clean_streak(_annotate(rows))
    assert streak["consecutive_clean_days"] == 3
    assert streak["last_reset_date"] is None
    assert streak["clean_streak_started"] == "2026-04-21"
    assert streak["current_state"] == "clean"


def test_streak_resets_on_breach_then_resumes():
    """5 days; day 3 has -6% loss; streak walks back to 2 clean days."""
    rows = [
        {"date": "2026-04-21", "total_equity": "1000000", "n_positions": "20"},
        {"date": "2026-04-22", "total_equity": "1010000", "n_positions": "20"},
        {"date": "2026-04-23", "total_equity":  "949400", "n_positions": "20"},  # -6% loss
        {"date": "2026-04-24", "total_equity":  "959400", "n_positions": "20"},
        {"date": "2026-04-25", "total_equity":  "969400", "n_positions": "20"},
    ]
    streak = mod.count_clean_streak(_annotate(rows))
    assert streak["consecutive_clean_days"] == 2
    assert streak["last_reset_date"] == "2026-04-23"
    assert "daily loss" in streak["last_reset_reason"]
    assert streak["clean_streak_started"] == "2026-04-24"


def test_streak_today_is_dirty_marks_state_dirty():
    rows = [
        {"date": "2026-04-23", "total_equity": "1000000", "n_positions": "20"},
        {"date": "2026-04-24", "total_equity":  "940000", "n_positions": "20"},  # -6%
    ]
    streak = mod.count_clean_streak(_annotate(rows))
    assert streak["consecutive_clean_days"] == 0
    assert streak["last_reset_date"] == "2026-04-24"
    assert streak["current_state"] == "dirty"


def test_streak_halt_dates_are_dirty_regardless_of_metrics():
    """Even if the equity row looks clean, a HALT event on that date breaks the streak."""
    rows = [
        {"date": "2026-04-23", "total_equity": "1000000", "n_positions": "20"},
        {"date": "2026-04-24", "total_equity": "1010000", "n_positions": "20"},
        {"date": "2026-04-25", "total_equity": "1020000", "n_positions": "20"},
    ]
    streak = mod.count_clean_streak(
        _annotate(rows), halt_dates={"2026-04-24"},
    )
    assert streak["consecutive_clean_days"] == 1
    assert streak["last_reset_date"] == "2026-04-24"
    assert "HALT" in streak["last_reset_reason"]


def test_streak_handles_empty_history():
    streak = mod.count_clean_streak([])
    assert streak["consecutive_clean_days"] == 0
    assert streak["current_state"] == "no_data"


# -----------------------------------------------------------------------------
# build_progress — the full report
# -----------------------------------------------------------------------------

def test_build_progress_emits_progress_pct_and_remaining():
    rows = [
        {"date": f"2026-04-{i:02d}", "total_equity": str(1_000_000 + i * 1000),
         "n_positions": "20"}
        for i in range(1, 11)  # 10 clean days
    ]
    report = mod.build_progress(rows, target_days=90, as_of="2026-04-27T00:00:00Z")
    assert report["consecutive_clean_days"] == 10
    assert report["progress_pct"] == round(10 / 90 * 100, 2)
    assert report["remaining_days"] == 80
    assert report["target_days"] == 90
    assert report["current_state"] == "clean"
    assert report["today_metrics"]["date"] == "2026-04-10"


def test_build_progress_thresholds_match_input_overrides():
    """Custom thresholds should propagate through to the report."""
    report = mod.build_progress([], daily_loss_limit=-0.10, drawdown_limit=-0.30)
    assert report["thresholds"]["daily_loss_limit_pct"] == -10
    assert report["thresholds"]["drawdown_limit_pct"] == -30


# -----------------------------------------------------------------------------
# parse_halt_dates_from_alerts
# -----------------------------------------------------------------------------

def test_parse_halt_dates_extracts_iso_dates():
    alerts = (
        "[2026-04-23T08:15:23] ⛔ Kronos HALTED — daily loss -6.20%\n"
        "[2026-04-24T08:00:01] [info] paper trade execute ok\n"
        "[2026-04-25T15:33:41] ⛔ Kronos HALTED — drawdown -22%\n"
    )
    out = mod.parse_halt_dates_from_alerts(alerts)
    assert out == {"2026-04-23", "2026-04-25"}


def test_parse_halt_dates_handles_empty_input():
    assert mod.parse_halt_dates_from_alerts("") == set()
    assert mod.parse_halt_dates_from_alerts("noise without ts\n") == set()
