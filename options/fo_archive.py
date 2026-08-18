"""Download + cache NSE F&O bhavcopies as canonical per-day csv.gz files.

Failures are never silent: days that return 404 on both URL formats land in
gaps.json as "no_file" (holidays included — the QA step reconciles against
the qlib trading calendar); network/parse failures land as "error". A later
successful fetch clears the entry.
"""
from __future__ import annotations

import csv
import datetime
import gzip
import io
import json
import pathlib
import time
import zipfile

from options.fo_bhavcopy import UDIFF_CUTOVER_DATE, parse_legacy, parse_udiff

_CANONICAL_FIELDS = ["date", "symbol", "kind", "expiry", "strike", "close",
                     "settle", "oi", "volume", "underlying_close", "lot_size"]
_INT_FIELDS = {"oi", "volume", "lot_size"}
_FLOAT_FIELDS = {"strike", "close", "settle", "underlying_close"}

_BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Referer": "https://www.nseindia.com/",
}
_RETRY_DELAYS_SECONDS = [2, 8, 30]


def url_candidates(trading_date: datetime.date) -> list[str]:
    udiff_url = ("https://nsearchives.nseindia.com/content/fo/"
                 f"BhavCopy_NSE_FO_0_0_0_{trading_date:%Y%m%d}_F_0000.csv.zip")
    month_upper = trading_date.strftime("%b").upper()
    legacy_url = ("https://nsearchives.nseindia.com/content/historical/DERIVATIVES/"
                  f"{trading_date:%Y}/{month_upper}/"
                  f"fo{trading_date:%d}{month_upper}{trading_date:%Y}bhav.csv.zip")
    if trading_date >= UDIFF_CUTOVER_DATE:
        return [udiff_url, legacy_url]
    return [legacy_url, udiff_url]


def _default_http_get(url: str):
    import requests
    last_error = None
    for delay_seconds in [0] + _RETRY_DELAYS_SECONDS:
        if delay_seconds:
            time.sleep(delay_seconds)
        try:
            response = requests.get(url, headers=_BROWSER_HEADERS, timeout=30)
            if response.status_code < 500:
                return response.status_code, response.content
            last_error = f"http {response.status_code}"
        except requests.RequestException as exc:
            last_error = str(exc)
    raise ConnectionError(f"{url}: {last_error}")


def _day_path(trading_date: datetime.date, archive_root: pathlib.Path) -> pathlib.Path:
    return archive_root / f"{trading_date:%Y}" / f"{trading_date:%Y%m%d}.csv.gz"


def _update_ledger(archive_root: pathlib.Path, trading_date: datetime.date,
                   status: str | None) -> None:
    ledger_path = archive_root / "gaps.json"
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {}
    date_key = trading_date.isoformat()
    if status is None:
        ledger.pop(date_key, None)
    else:
        ledger[date_key] = status
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(json.dumps(ledger, indent=1, sort_keys=True))


def fetch_day(trading_date: datetime.date, archive_root: pathlib.Path,
              http_get=None) -> str:
    http_get = http_get or _default_http_get
    day_path = _day_path(trading_date, archive_root)
    if day_path.exists():
        return "cached"
    try:
        for candidate_url in url_candidates(trading_date):
            status_code, content = http_get(candidate_url)
            if status_code != 200:
                continue
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                csv_text = archive.read(archive.namelist()[0]).decode("utf-8", "replace")
            parser = parse_udiff if "BhavCopy_NSE_FO" in candidate_url else parse_legacy
            rows = parser(csv_text)
            if not rows:
                continue  # wrong-format 200 page (NSE serves HTML error bodies)
            day_path.parent.mkdir(parents=True, exist_ok=True)
            with gzip.open(day_path, "wt", newline="") as gz_file:
                writer = csv.DictWriter(gz_file, fieldnames=_CANONICAL_FIELDS)
                writer.writeheader()
                writer.writerows(rows)
            _update_ledger(archive_root, trading_date, None)
            return "written"
    except (ConnectionError, zipfile.BadZipFile, KeyError, ValueError) as exc:
        _update_ledger(archive_root, trading_date, f"error: {exc}"[:200])
        return "error"
    _update_ledger(archive_root, trading_date, "no_file")
    return "no_file"


def load_day(trading_date: datetime.date, archive_root: pathlib.Path) -> list[dict]:
    with gzip.open(_day_path(trading_date, archive_root), "rt") as gz_file:
        rows = []
        for record in csv.DictReader(gz_file):
            for field_name in _FLOAT_FIELDS:
                record[field_name] = float(record[field_name]) if record[field_name] else None
            for field_name in _INT_FIELDS:
                if record[field_name]:
                    record[field_name] = int(float(record[field_name]))
                else:
                    record[field_name] = None if field_name == "lot_size" else 0
            record["strike"] = record["strike"] or 0.0
            record["close"] = record["close"] or 0.0
            record["settle"] = record["settle"] or 0.0
            rows.append(record)
        return rows
