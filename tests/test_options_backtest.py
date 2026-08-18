import datetime
import gzip
import pathlib

import pytest

from options.backtest import (build_cycles, monthly_expiry_dates, run_backtest,
                              summary_stats)

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
BLACKOUTS = REPO_ROOT / "data" / "options_blackouts.yaml"

CANONICAL_HEADER = "date,symbol,kind,expiry,strike,close,settle,oi,volume,underlying_close,lot_size\n"

# Cycle: expiry 2024-08-29, previous expiry 2024-07-25.
# Entry = first Friday after Jul 25 with a file = Aug 2. Deadline = last
# Tuesday before Aug 29 = Aug 27.
EXPIRIES = ["2024-07-25", "2024-08-29"]
DAYS = ["2024-08-02", "2024-08-09", "2024-08-27"]


def _write_day(archive_root, iso_date, rows):
    day_dir = archive_root / iso_date[:4]
    day_dir.mkdir(parents=True, exist_ok=True)
    path = day_dir / f"{iso_date.replace('-', '')}.csv.gz"
    with gzip.open(path, "wt") as gz_file:
        gz_file.write(CANONICAL_HEADER)
        for row in rows:
            gz_file.write(",".join(str(v) if v is not None else "" for v in row) + "\n")


def _contract(iso_date, symbol, kind, strike, settle, spot, oi=5000):
    return (iso_date, symbol, kind, "2024-08-29", strike, settle, settle,
            oi, 100, spot, 500)


class _NoCloses:
    def closes_upto(self, symbol, iso_date):
        return []


def _build_archive(tmp_path):
    archive_root = tmp_path / "archive"
    # Entry legs at 5.0 (IV ~30% -> strikes outside 1-sigma, grade A, deltas
    # in band). FLAT: legs decay 5 -> 0.9 (combined 1.8/10 = 18% <= 20%
    # target). JUMPY: spot gaps to 1200 on Aug 9; its 1100 call explodes to
    # 110 (stop at 110.9/10 = 11x >= 2x).
    for iso_date, flat_leg, jumpy_spot, jumpy_call, jumpy_put in [
        ("2024-08-02", 5.0, 1000.0, 5.0, 5.0),
        ("2024-08-09", 0.9, 1200.0, 110.0, 0.9),
        ("2024-08-27", 0.9, 1200.0, 105.0, 0.5),
    ]:
        rows = []
        for symbol, spot, call_settle, put_settle in [
            ("FLAT", 1000.0, flat_leg, flat_leg),
            ("JUMPY", jumpy_spot, jumpy_call, jumpy_put),
        ]:
            rows.append(_contract(iso_date, symbol, "FUT", 0.0, spot, spot))
            rows.append(_contract(iso_date, symbol, "CE", 1100.0, call_settle, spot))
            rows.append(_contract(iso_date, symbol, "PE", 900.0, put_settle, spot))
        _write_day(archive_root, iso_date, rows)
    return archive_root


def _run(tmp_path, stop_key="1:1"):
    archive_root = _build_archive(tmp_path)
    return run_backtest(archive_root, _NoCloses(), "2024-08-01", "2024-08-31",
                        stop_key=stop_key, use_earnings_filter=False,
                        capital=500_000.0, blackouts_path=BLACKOUTS,
                        expiry_dates=EXPIRIES, score_floor=0.0)


def test_build_cycles_picks_friday_entry_and_tuesday_deadline():
    cycles = build_cycles(EXPIRIES, DAYS)
    assert cycles == [{"entry_date": "2024-08-02", "deadline_date": "2024-08-27",
                       "expiry": "2024-08-29"}]


def test_flat_symbol_exits_at_target_with_exact_pnl(tmp_path):
    result = _run(tmp_path)
    flat_trades = [t for t in result["trades"] if t["symbol"] == "FLAT"]
    assert len(flat_trades) == 1
    trade = flat_trades[0]
    assert trade["exit_reason"] == "target"          # 1.8/10 = 18% <= 20% remaining
    assert trade["exit_date"] == "2024-08-09"
    assert trade["breached"] is False
    # gross: (10 - 1.8) * 500 = 4,100; net = gross - entry costs - exit costs
    assert trade["gross_pnl"] == pytest.approx(4_100.0)
    assert trade["net_pnl"] < trade["gross_pnl"]
    assert trade["net_pnl"] > 3_500.0


def test_jumpy_symbol_stops_out_stressed_and_flags_breach(tmp_path):
    result = _run(tmp_path)
    jumpy_trades = [t for t in result["trades"] if t["symbol"] == "JUMPY"]
    assert len(jumpy_trades) == 1
    trade = jumpy_trades[0]
    assert trade["exit_reason"] == "stop"            # 110.9/10 = 11x >= 2.0x
    assert trade["breached"] is True                 # spot 1200 > 1100 strike
    assert trade["gross_pnl"] == pytest.approx((10.0 - 110.9) * 500)
    assert trade["net_pnl"] < trade["gross_pnl"]


def test_no_stop_variant_rides_to_time_exit(tmp_path):
    result = _run(tmp_path, stop_key="none")
    jumpy_trade = next(t for t in result["trades"] if t["symbol"] == "JUMPY")
    assert jumpy_trade["exit_reason"] == "time"
    assert jumpy_trade["exit_date"] == "2024-08-27"
    assert jumpy_trade["gross_pnl"] == pytest.approx((10.0 - 105.5) * 500)


def test_equity_curve_ends_at_capital_plus_net_pnl(tmp_path):
    result = _run(tmp_path)
    total_net = sum(t["net_pnl"] for t in result["trades"])
    assert result["equity_curve"][-1][1] == pytest.approx(500_000.0 + total_net)


def test_summary_stats_shape(tmp_path):
    stats = summary_stats(_run(tmp_path))
    assert stats["n_trades"] == 2
    assert 0.0 <= stats["win_rate"] <= 1.0
    assert stats["max_drawdown"] >= 0.0
    assert stats["breach_rate"] == pytest.approx(0.5)


def test_monthly_expiry_detection_ignores_thin_expiries(tmp_path):
    archive_root = _build_archive(tmp_path)  # only 2 symbols share the expiry
    detected = monthly_expiry_dates(archive_root, "2024-08-01", "2024-08-31",
                                    min_shared_symbols=2, sample_stride_days=1)
    assert detected == ["2024-08-29"]
    assert monthly_expiry_dates(archive_root, "2024-08-01", "2024-08-31",
                                min_shared_symbols=50) == []
