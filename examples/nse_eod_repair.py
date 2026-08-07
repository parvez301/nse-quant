#!/usr/bin/env python3
"""Patch the newest session's OHLCV from NSE's official Bhavcopy.

Why this exists
---------------
From 2026-07-07 the daily cron stalled for a month. Yahoo had begun publishing
the previous session's NSE bar with `volume` filled but open/high/low/close
null for ~36% of the universe at 08:00 IST, backfilling the prices only ~a day
later. Those NaN rows advanced the Qlib calendar to a date whose close was
NaN, so `nse_safety.check_data` saw ~64% coverage against its 80% floor and
refused to emit a decision — every weekday, for 20 of 23 runs.

The fix is two layers:

  Layer 1  `nse_data_loader._drop_unusable_bars` refuses to write a bar whose
           OHLC is incomplete. That alone unblocks the pipeline, but leaves the
           newest session absent, so decisions run one day stale.

  Layer 2  (this module) fills that session from NSE's own end-of-day file,
           which is complete and published the same evening.

Only holes are filled. A row that already carries valid prices is never
overwritten, because Yahoo's series is split/dividend-adjusted and Bhavcopy's
is raw — we must not interleave the two conventions inside one history. For
the newest session the distinction is moot (nothing has happened *after* it
yet, so its adjustment factor is 1.0), which is exactly why patching the tail
is safe while backfilling old gaps this way would not be.

If the Bhavcopy is unavailable — NSE blocks the request, the day is a holiday,
`jugaad-data` is not installed — this exits 0 and patches nothing. Layer 1
still guarantees the pipeline runs, one day behind. Degrade, never block.

Usage
-----
    # Patch the session dated 2026-08-06, fetching the Bhavcopy if not cached
    python examples/nse_eod_repair.py --date 2026-08-06

    # Infer the target date (latest weekday strictly before today, IST)
    python examples/nse_eod_repair.py

    # Work off an already-populated cache, never touch the network
    python examples/nse_eod_repair.py --date 2026-08-06 --no-fetch
"""
from __future__ import annotations

import argparse
import csv as _csv
import datetime
import sys
from pathlib import Path

import pandas as pd

# Cash-segment equity series. Mirrors NSEBhavcopyAdapter.KEEP_SERIES so both
# consumers of the archive agree on what counts as a tradeable equity line.
KEEP_SERIES = {"EQ", "BE", "BZ", "SM"}

OHLC_COLUMNS = ["open", "high", "low", "close"]
CSV_COLUMNS = ["date", "symbol", "open", "high", "low", "close", "volume", "factor"]

# Bhavcopy header aliases: canonical name -> (old-format column, new-format column)
_COLUMN_ALIASES = {
    "symbol": ("SYMBOL", "TCKRSYMB"),
    "series": ("SERIES", "SCTYSRS"),
    "open": ("OPEN", "OPNPRIC"),
    "high": ("HIGH", "HGHPRIC"),
    "low": ("LOW", "LWPRIC"),
    "close": ("CLOSE", "CLSPRIC"),
    "volume": ("TOTTRDQTY", "TTLTRADGVOL"),
}

_MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
           "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


# ---------------------------------------------------------------------------
# Bhavcopy parsing
# ---------------------------------------------------------------------------

def _resolve_columns(header: list[str]) -> dict[str, int] | None:
    """Map canonical field names to column indices, tolerating both archive
    eras. Returns None if the header is not a recognisable Bhavcopy."""
    cols = [c.strip().upper() for c in header]
    resolved: dict[str, int] = {}
    for canonical, aliases in _COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in cols:
                resolved[canonical] = cols.index(alias)
                break
        else:
            return None
    return resolved


def parse_bhavcopy_ohlc(csv_path: Path) -> dict[str, dict]:
    """Read one Bhavcopy CSV into {SYMBOL: {open, high, low, close, volume}}.

    Rows outside KEEP_SERIES, and rows whose prices are not parseable as
    floats (NSE writes "-" for non-traded lines), are skipped.
    """
    bars: dict[str, dict] = {}
    with csv_path.open(newline="") as handle:
        reader = _csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            return {}
        ix = _resolve_columns(header)
        if ix is None:
            return {}

        widest = max(ix.values())
        for row in reader:
            if not row or len(row) <= widest:
                continue
            if row[ix["series"]].strip().upper() not in KEEP_SERIES:
                continue
            symbol = row[ix["symbol"]].strip().upper()
            if not symbol:
                continue
            try:
                bar = {
                    field: float(row[ix[field]].strip())
                    for field in ("open", "high", "low", "close", "volume")
                }
            except (ValueError, IndexError):
                continue
            bars[symbol] = bar
    return bars


def find_cached_bhavcopy(cache_dir: Path, date_iso: str) -> Path | None:
    """Locate the cached Bhavcopy for `date_iso` under cache_dir/YYYY/.

    Matches both filename eras: `cm06AUG2026bhav.csv` and
    `BhavCopy_NSE_CM_0_0_0_20260806_F_0000.csv`.
    """
    try:
        day = datetime.date.fromisoformat(date_iso)
    except ValueError:
        return None

    year_dir = Path(cache_dir) / str(day.year)
    if not year_dir.is_dir():
        return None

    old_name = f"cm{day.day:02d}{_MONTHS[day.month - 1]}{day.year}bhav.csv".upper()
    compact = f"{day.year:04d}{day.month:02d}{day.day:02d}"

    for candidate in sorted(year_dir.iterdir()):
        if not candidate.is_file() or candidate.suffix.lower() != ".csv":
            continue
        name = candidate.name.upper()
        if name == old_name:
            return candidate
        if name.startswith("BHAVCOPY_NSE_CM") and compact in name:
            return candidate
    return None


def fetch_bhavcopy(cache_dir: Path, date_iso: str, *, verbose: bool = True) -> Path | None:
    """Download the Bhavcopy for one date into the cache. Returns the cached
    path, or None if the fetch failed for any reason (holiday, NSE block,
    `jugaad-data` absent). Never raises — this layer must degrade quietly."""
    day = datetime.date.fromisoformat(date_iso)
    try:
        import nse_bhavcopy_fetch  # noqa: PLC0415
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        try:
            import nse_bhavcopy_fetch  # noqa: PLC0415
        except ImportError:
            if verbose:
                print("[eod-repair] nse_bhavcopy_fetch not importable — skipping fetch")
            return None

    try:
        nse_bhavcopy_fetch.fetch_range(day, day, Path(cache_dir), verbose=verbose)
    except Exception as exc:  # noqa: BLE001 — NSE blocks / missing dep / holiday
        if verbose:
            print(f"[eod-repair] Bhavcopy fetch failed for {date_iso}: {str(exc)[:160]}")
        return None

    return find_cached_bhavcopy(cache_dir, date_iso)


# ---------------------------------------------------------------------------
# Repair
# ---------------------------------------------------------------------------

def _row_has_valid_prices(frame: pd.DataFrame, date_iso: str) -> bool:
    match = frame[frame["date"] == date_iso]
    if match.empty:
        return False
    return not match[OHLC_COLUMNS].isna().any(axis=None)


def repair_csv_dir(csv_dir: Path, target_date: str, bars: dict[str, dict],
                   *, verbose: bool = True) -> dict:
    """Fill `target_date` into every per-ticker CSV that is missing it.

    Returns {patched, already_ok, unavailable, skipped}. `unavailable` counts
    tickers with a hole we could not fill because the symbol is absent from
    the Bhavcopy — normally delisted or newly listed names.
    """
    csv_dir = Path(csv_dir)
    summary = {"patched": 0, "already_ok": 0, "unavailable": 0, "skipped": 0}

    for csv_path in sorted(csv_dir.glob("*.csv")):
        symbol = csv_path.stem.upper()
        try:
            frame = pd.read_csv(csv_path)
        except Exception:  # noqa: BLE001 — a corrupt CSV must not abort the sweep
            summary["skipped"] += 1
            continue
        if frame.empty or "date" not in frame.columns:
            summary["skipped"] += 1
            continue

        frame["date"] = frame["date"].astype(str)

        if _row_has_valid_prices(frame, target_date):
            summary["already_ok"] += 1
            continue

        bar = bars.get(symbol)
        if bar is None:
            summary["unavailable"] += 1
            continue

        patch = pd.DataFrame([{
            "date": target_date,
            "symbol": symbol,
            "open": bar["open"],
            "high": bar["high"],
            "low": bar["low"],
            "close": bar["close"],
            "volume": bar["volume"],
            "factor": 1.0,
        }])

        merged = pd.concat([frame, patch], ignore_index=True)
        merged = merged.drop_duplicates(subset=["date"], keep="last").sort_values("date")
        for column in CSV_COLUMNS:
            if column not in merged.columns:
                merged[column] = 1.0 if column == "factor" else symbol
        merged[CSV_COLUMNS].to_csv(csv_path, index=False)
        summary["patched"] += 1

    if verbose:
        print(
            f"[eod-repair] date={target_date}  patched={summary['patched']}  "
            f"already_ok={summary['already_ok']}  "
            f"unavailable={summary['unavailable']}  skipped={summary['skipped']}"
        )
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def default_target_date() -> str:
    """Latest weekday strictly before today in IST. NSE holidays fall out
    naturally — the Bhavcopy simply won't exist and we no-op."""
    ist_now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)
    day = ist_now.date() - datetime.timedelta(days=1)
    while day.weekday() >= 5:
        day -= datetime.timedelta(days=1)
    return day.isoformat()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--date", default=None,
                        help="session to patch, YYYY-MM-DD (default: latest weekday before today IST)")
    parser.add_argument("--csv-dir", default="data/qlib_data/in_data/_csv",
                        help="per-ticker CSV directory written by nse_data_loader")
    parser.add_argument("--cache-dir", default="data/bhavcopy",
                        help="Bhavcopy cache root (default: data/bhavcopy)")
    parser.add_argument("--no-fetch", action="store_true",
                        help="use only what is already cached; never hit the network")
    args = parser.parse_args()

    target_date = args.date or default_target_date()
    csv_dir = Path(args.csv_dir)
    cache_dir = Path(args.cache_dir)

    if not csv_dir.is_dir():
        print(f"[eod-repair] csv dir {csv_dir} does not exist — nothing to do")
        return

    bhav_path = find_cached_bhavcopy(cache_dir, target_date)
    if bhav_path is None and not args.no_fetch:
        bhav_path = fetch_bhavcopy(cache_dir, target_date)

    if bhav_path is None:
        print(f"[eod-repair] no Bhavcopy available for {target_date} — "
              f"leaving data as-is (pipeline still runs on the last complete session)")
        return

    bars = parse_bhavcopy_ohlc(bhav_path)
    if not bars:
        print(f"[eod-repair] {bhav_path.name} parsed to 0 usable rows — leaving data as-is")
        return

    print(f"[eod-repair] {bhav_path.name}: {len(bars)} equity lines")
    repair_csv_dir(csv_dir, target_date, bars)


if __name__ == "__main__":
    main()
