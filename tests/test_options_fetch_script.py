import datetime
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "examples"))
from nse_options_fetch import run_fetch


def test_run_fetch_iterates_weekdays_and_tallies(tmp_path):
    seen_dates = []

    def fake_fetch_day(trading_date, archive_root):
        seen_dates.append(trading_date)
        return "no_file" if trading_date.weekday() == 4 else "written"

    summary = run_fetch(datetime.date(2024, 8, 5), datetime.date(2024, 8, 11),
                        tmp_path, sleep_seconds=0, fetch_day_fn=fake_fetch_day)
    assert seen_dates == [datetime.date(2024, 8, 5 + offset) for offset in range(5)]  # Mon..Fri only
    assert summary == {"written": 4, "cached": 0, "no_file": 1, "error": 0}
