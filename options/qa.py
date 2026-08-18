"""Phase 0 QA gate: archive coverage + spot-check sampled (stock, day) cells.

Pass criteria (spec §5): >= 95% of calendar trading days present per year;
sampled cells show a contiguous strike ladder, OI near ATM, and an ATM IV
inside [8%, 120%].
"""
from __future__ import annotations

import collections
import datetime
import pathlib

from options.fo_archive import load_day
from options.greeks import implied_volatility

_IV_SANE_RANGE = (0.08, 1.20)


def coverage_report(archive_root: pathlib.Path,
                    calendar_dates: list[datetime.date]) -> dict:
    report: dict = {}
    for calendar_date in calendar_dates:
        year_bucket = report.setdefault(calendar_date.year, {"expected": 0, "present": 0})
        year_bucket["expected"] += 1
        day_file = archive_root / f"{calendar_date:%Y}" / f"{calendar_date:%Y%m%d}.csv.gz"
        if day_file.exists():
            year_bucket["present"] += 1
    for year_bucket in report.values():
        year_bucket["coverage"] = year_bucket["present"] / year_bucket["expected"]
    return report


def sample_cell_checks(archive_root: pathlib.Path, trading_date: datetime.date,
                       symbol: str) -> dict:
    rows = [row for row in load_day(trading_date, archive_root) if row["symbol"] == symbol]
    future_rows = [row for row in rows if row["kind"] == "FUT"]
    spot_estimate = next((row["underlying_close"] for row in rows if row["underlying_close"]),
                         future_rows[0]["settle"] if future_rows else None)
    call_rows = [row for row in rows if row["kind"] == "CE"]
    nearest_expiry = min(row["expiry"] for row in call_rows)
    ladder_rows = [row for row in call_rows if row["expiry"] == nearest_expiry]
    strikes = sorted({row["strike"] for row in ladder_rows})
    atm_strike = min(strikes, key=lambda strike: abs(strike - spot_estimate))
    near_atm_strikes = [s for s in strikes if abs(s - spot_estimate) <= 0.15 * spot_estimate]
    gaps = [b - a for a, b in zip(near_atm_strikes, near_atm_strikes[1:])]
    modal_gap = collections.Counter(gaps).most_common(1)[0][0] if gaps else 0
    atm_row = next(row for row in ladder_rows if row["strike"] == atm_strike)
    days_to_expiry = (datetime.date.fromisoformat(nearest_expiry) - trading_date).days
    atm_iv = implied_volatility(atm_row["settle"], spot_estimate, atm_strike,
                                max(days_to_expiry, 1) / 365.0)
    return {
        "strikes_contiguous": bool(gaps) and max(gaps) <= 2 * modal_gap,
        "atm_oi_positive": atm_row["oi"] > 0,
        "atm_iv": atm_iv,
        "atm_iv_sane": atm_iv is not None and _IV_SANE_RANGE[0] <= atm_iv <= _IV_SANE_RANGE[1],
    }
