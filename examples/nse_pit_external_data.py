#!/usr/bin/env python3
"""External point-in-time data adapter — for when you subscribe to a paid feed.

The free path (yfinance + nse_universe_pit.py) gives you a partial PIT
correction: it knows when each *currently-listed* stock was first traded,
but it can't recover stocks that yfinance has dropped entirely (DHFL,
RCOM, JET, PUNJLLOYD, etc.). For those, you need a paid data source that
preserves delisted history.

This module defines a small adapter interface so you can plug in any
provider when you subscribe. Today it ships with:

  * `EODHistoricalDataAdapter` (https://eodhd.com — ~$30/mo, NSE+BSE pack)
    Stub-mode: prints the exact API call it WOULD make if you set
    EOD_HISTORICAL_API_KEY in your .envrc.local. Doesn't fabricate data.

  * `NoOpAdapter` (default) — returns the existing yfinance universe
    unchanged. Used when no API key is configured.

To activate the paid adapter:

    # 1. Subscribe at https://eodhd.com (NSE+BSE pack covers India)
    # 2. Add to .envrc.local (gitignored):
    export EOD_HISTORICAL_API_KEY=your_key_here

    # 3. Build the corrected PIT universe:
    python examples/nse_pit_external_data.py build \\
        --provider eod-historical --out outputs/pit_universe_corrected.parquet

    # 4. Re-run walkforward with the corrected universe:
    python examples/nse_walkforward_backtest.py \\
        --pit_cache outputs/pit_universe_corrected.parquet

The corrected file slots in transparently — the rest of the pipeline
doesn't care which adapter built it.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Protocol


class PITDataAdapter(Protocol):
    """Minimal interface every adapter must satisfy."""

    name: str

    def is_available(self) -> bool:
        """Return True if the adapter can actually fetch data (e.g. API
        key configured), False if it's only the stub form."""
        ...

    def list_delisted_tickers(self, start_year: int, end_year: int) -> list[dict]:
        """Return [{ticker, first_date, last_date, exit_event}, ...] for
        every NSE-listed name that delisted between start_year and end_year."""
        ...


class NoOpAdapter:
    name = "no-op"

    def is_available(self) -> bool:
        return True

    def list_delisted_tickers(self, start_year: int, end_year: int) -> list[dict]:
        return []


class EODHistoricalDataAdapter:
    """https://eodhd.com — paid PIT data including delisted symbols.

    Stub today: structured to make the migration to the real API call a
    one-line change. Once you set EOD_HISTORICAL_API_KEY, replace the
    `_fetch_delisted` body with the real `requests.get(...)` call against
    https://eodhd.com/api/exchange-symbol-list/NSE?delisted=1
    """
    name = "eod-historical"
    BASE_URL = "https://eodhd.com/api/exchange-symbol-list/NSE"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("EOD_HISTORICAL_API_KEY")

    def is_available(self) -> bool:
        return bool(self.api_key)

    def _fetch_delisted(self, start_year: int, end_year: int) -> list[dict]:
        """Real implementation will live here. Stubbed today.

        Once API key is configured, replace with:

            import requests
            url = f"{self.BASE_URL}?api_token={self.api_key}&delisted=1&fmt=json"
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            return [
                {
                    "ticker": row["Code"],
                    "first_date": row["IsinFirstDate"],
                    "last_date": row["IsinLastDate"],
                    "exit_event": row.get("Type") or "delisted",
                }
                for row in response.json()
                if start_year <= int(row["IsinLastDate"][:4]) <= end_year
            ]
        """
        raise NotImplementedError(
            "EOD Historical Data adapter is currently stub-only. Subscribe at "
            "https://eodhd.com (NSE+BSE pack), set EOD_HISTORICAL_API_KEY in "
            ".envrc.local, then replace this method body with the real "
            "requests.get() call documented in the docstring above."
        )

    def list_delisted_tickers(self, start_year: int, end_year: int) -> list[dict]:
        if not self.is_available():
            print(
                "[eod-historical] EOD_HISTORICAL_API_KEY not set — "
                "returning empty delisted list. Subscribe at https://eodhd.com "
                "and set the key in .envrc.local to enable.",
                file=sys.stderr,
            )
            return []
        return self._fetch_delisted(start_year, end_year)


class NSEBhavcopyAdapter:
    """NSE daily Bhavcopy archive — free PIT data including delisted symbols.

    The NSE archive at https://nsearchives.nseindia.com publishes a daily
    "Bhavcopy" (cm{DDMMMYYY}bhav.csv.zip up to mid-2024, BhavCopy_NSE_CM_*.csv.zip
    after) that lists every cash-segment symbol that traded that day —
    crucially including names since delisted, which yfinance silently drops.

    Consuming the archive is its own multi-day project: NSE actively
    rate-limits / blocks programmatic access, the format changed mid-2024,
    ISIN/symbol changes from corporate actions need stitching, and ~5,500
    daily files cover the 21-year window. This adapter is therefore
    structured around a LOCAL CACHE that some upstream step populates,
    rather than fetching directly from NSE on every call.

    Cache layout expected:

        data/bhavcopy/
            2008/
                cm01JAN2008bhav.csv     # extracted CSV, one per trading day
                ...
            ...
            2024/
                BhavCopy_NSE_CM_0_0_0_20241231_F_0000.csv

    Once the cache is populated (separate phase), this adapter walks the
    files, computes per-ticker (first_date, last_date), and returns the set
    of symbols that traded but stopped appearing before the end of the
    requested year window — i.e. delisted candidates.

    Until the cache exists, `is_available` returns False and
    `list_delisted_tickers` returns []. The caller is expected to fall
    back to the curated `data/known_delisted_nse.json` layer (which is
    what nse_survivorship_estimate.py --include-known-delisted does).

    To populate the cache later (planned, separate session):

        # 1. Use jugaad-data or a manually-pulled archive zip
        pip install jugaad-data
        python -m jugaad_data.bhavcopy --from 2008-01-01 --to 2024-12-31 \\
            --out data/bhavcopy/

        # 2. Build the corrected delisted list
        python examples/nse_pit_external_data.py list-delisted \\
            --provider nse-bhavcopy --start-year 2008 --end-year 2024 \\
            --out outputs/external_delisted_tickers.json
    """
    name = "nse-bhavcopy"
    DEFAULT_CACHE = Path("data/bhavcopy")

    def __init__(self, cache_dir: str | Path | None = None):
        self.cache_dir = Path(cache_dir or self.DEFAULT_CACHE)

    def is_available(self) -> bool:
        # Available iff the cache directory exists AND has at least one
        # year-subdirectory with at least one CSV file inside. We don't
        # require all 21 years — partial coverage is still useful.
        if not self.cache_dir.is_dir():
            return False
        for year_dir in self.cache_dir.iterdir():
            if not year_dir.is_dir():
                continue
            for f in year_dir.iterdir():
                if f.suffix.lower() == ".csv":
                    return True
        return False

    def _iter_cache_files(self, start_year: int, end_year: int):
        """Yield (year, csv_path) for every cached Bhavcopy CSV in the
        requested year window. Pure walker — no NSE network access."""
        for year_dir in sorted(self.cache_dir.iterdir() if self.cache_dir.is_dir() else []):
            try:
                year = int(year_dir.name)
            except (ValueError, AttributeError):
                continue
            if not (start_year <= year <= end_year):
                continue
            if not year_dir.is_dir():
                continue
            for f in sorted(year_dir.iterdir()):
                if f.suffix.lower() == ".csv":
                    yield year, f

    def list_delisted_tickers(self, start_year: int, end_year: int) -> list[dict]:
        if not self.is_available():
            print(
                "[nse-bhavcopy] no cached Bhavcopy CSVs found under "
                f"{self.cache_dir}. The adapter SHELL is shipped; the data "
                "fetch is a separate phase. Until then, this returns []. "
                "See module docstring for the planned ingestion workflow.",
                file=sys.stderr,
            )
            return []
        # Real ingestion lives here. Stubbed today because populating the
        # cache itself is the multi-day project. Sketch:
        #   for year, csv_path in self._iter_cache_files(start_year, end_year):
        #       parse symbol column from each row
        #       record (symbol -> first_seen_date, last_seen_date)
        #   delisted = [
        #       {ticker, first_date, last_date, exit_event="bhavcopy_disappeared"}
        #       for symbol, (fd, ld) in observed.items()
        #       if ld < f"{end_year}-12-01"   # stopped trading before window end
        #   ]
        raise NotImplementedError(
            "NSEBhavcopyAdapter is currently shell-only. The data ingestion "
            "(downloading + parsing ~5,500 daily CSVs across two format eras) "
            "is a separate phase — see the module docstring. The pure cache "
            "walker (`_iter_cache_files`) is testable today."
        )


PROVIDERS: dict[str, type] = {
    "no-op": NoOpAdapter,
    "eod-historical": EODHistoricalDataAdapter,
    "nse-bhavcopy": NSEBhavcopyAdapter,
}


def get_adapter(name: str) -> PITDataAdapter:
    cls = PROVIDERS.get(name)
    if cls is None:
        raise ValueError(
            f"Unknown provider {name!r}. Valid: {sorted(PROVIDERS)}"
        )
    return cls()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def cmd_status(args):
    """Show which adapters are available."""
    rows = []
    for name in PROVIDERS:
        adapter = get_adapter(name)
        rows.append({
            "provider": name,
            "available": adapter.is_available(),
            "needs_subscription": name != "no-op",
        })
    print(json.dumps(rows, indent=2))


def cmd_list_delisted(args):
    adapter = get_adapter(args.provider)
    if not adapter.is_available():
        print(f"[abort] adapter {args.provider!r} not configured.", file=sys.stderr)
        if args.provider == "eod-historical":
            print(
                "  Subscribe at https://eodhd.com, then set\n"
                "  export EOD_HISTORICAL_API_KEY=... in .envrc.local",
                file=sys.stderr,
            )
        sys.exit(1)
    delisted = adapter.list_delisted_tickers(args.start_year, args.end_year)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "provider": adapter.name,
        "start_year": args.start_year,
        "end_year": args.end_year,
        "n_delisted": len(delisted),
        "delisted": delisted,
    }, indent=2))
    print(f"[external-pit] wrote {out} ({len(delisted)} delisted tickers)")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("status", help="Which adapters are configured")
    sp.set_defaults(fn=cmd_status)

    sp = sub.add_parser("list-delisted", help="Fetch delisted tickers from a paid provider")
    sp.add_argument("--provider", default="eod-historical", choices=list(PROVIDERS))
    sp.add_argument("--start-year", type=int, default=2008)
    sp.add_argument("--end-year", type=int, default=2024)
    sp.add_argument("--out", default="outputs/external_delisted_tickers.json")
    sp.set_defaults(fn=cmd_list_delisted)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
