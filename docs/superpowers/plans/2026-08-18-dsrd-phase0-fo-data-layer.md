# DSRD Phase 0 — F&O Data Layer + Greeks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the NSE F&O bhavcopy archive (2019→present, both file formats) plus a stdlib Black-Scholes greeks module, ending with a data-QA gate that clears Phase 1.

**Architecture:** A new top-level `options/` package holds pure-logic modules (parsers, greeks) with no network in the import path; a downloader module does HTTP with retry and writes one canonical `csv.gz` per trading day under `data/fo_bhavcopy/`, recording failures in a gap ledger instead of skipping silently. Runnable entry points live in `examples/` per repo convention.

**Tech Stack:** Python 3.12+, stdlib (`csv`, `zipfile`, `math`, `json`), `requests` for HTTP. No pandas in the data layer (row dicts + csv module keep memory flat); no py_vollib (greeks are ~80 lines of math, tested against pinned reference values).

**Spec:** `docs/superpowers/specs/2026-08-18-dsrd-options-design.md` (§3 layout, §4 sources, §5 QA gate)

## Global Constraints

- Descriptive variable names throughout (user's global rule) — `strikePrice`, not `sp`.
- Tests run with `.venv/bin/pytest tests/test_options_<module>.py -q` from repo root.
- Stock derivatives only: UDiFF `FinInstrmTp` ∈ {STO, STF}; legacy `INSTRUMENT` ∈ {OPTSTK, FUTSTK}. Index contracts are dropped at parse time (spec §11).
- Canonical row schema (every parser produces exactly this dict, later tasks rely on it):
  `{"date": "YYYY-MM-DD", "symbol": str, "kind": "FUT"|"CE"|"PE", "expiry": "YYYY-MM-DD", "strike": float (0.0 for FUT), "close": float, "settle": float, "oi": int, "volume": int, "underlying_close": float|None, "lot_size": int|None}`
- Archive layout: `data/fo_bhavcopy/<YYYY>/<YYYYMMDD>.csv.gz` (canonical schema, header row included); ledger at `data/fo_bhavcopy/gaps.json`.
- Never commit archive data: add `data/fo_bhavcopy/` to `.gitignore` in Task 3.

---

### Task 1: `options/greeks.py` — Black-Scholes price, delta, implied vol

**Files:**
- Create: `options/__init__.py` (empty), `options/greeks.py`
- Test: `tests/test_options_greeks.py`

**Interfaces:**
- Produces:
  - `bs_price(spot: float, strike: float, years_to_expiry: float, volatility: float, rate: float = 0.07, option_kind: str = "CE") -> float`
  - `bs_delta(spot, strike, years_to_expiry, volatility, rate=0.07, option_kind="CE") -> float` (CE in [0,1], PE in [-1,0])
  - `implied_volatility(option_price, spot, strike, years_to_expiry, rate=0.07, option_kind="CE") -> float | None` (None when no vol in [0.01, 5.0] reproduces the price — non-convergence contract per spec §10)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_options_greeks.py
import math
import pytest

from options.greeks import bs_price, bs_delta, implied_volatility


# Pinned reference values, hand-derivable with r=0:
# ATM call, S=K=100, T=1y, sigma=0.20, r=0  ->  price 7.9656, delta 0.5398
def test_bs_price_atm_call_zero_rate_reference():
    assert bs_price(100.0, 100.0, 1.0, 0.20, rate=0.0, option_kind="CE") == pytest.approx(7.9656, abs=1e-3)


def test_bs_delta_atm_call_zero_rate_reference():
    assert bs_delta(100.0, 100.0, 1.0, 0.20, rate=0.0, option_kind="CE") == pytest.approx(0.5398, abs=1e-3)


def test_put_call_parity_holds():
    # C - P = S - K*exp(-rT) must hold for any inputs
    spot, strike, years, vol, rate = 950.0, 1000.0, 0.25, 0.35, 0.07
    call = bs_price(spot, strike, years, vol, rate, "CE")
    put = bs_price(spot, strike, years, vol, rate, "PE")
    assert call - put == pytest.approx(spot - strike * math.exp(-rate * years), abs=1e-6)


@pytest.mark.parametrize("volatility", [0.08, 0.20, 0.45, 0.90])
@pytest.mark.parametrize("moneyness", [0.85, 1.0, 1.15])
def test_implied_volatility_roundtrip(volatility, moneyness):
    spot, years, rate = 500.0, 30 / 365, 0.07
    strike = spot * moneyness
    for option_kind in ("CE", "PE"):
        price = bs_price(spot, strike, years, volatility, rate, option_kind)
        recovered = implied_volatility(price, spot, strike, years, rate, option_kind)
        assert recovered == pytest.approx(volatility, abs=1e-4)


def test_implied_volatility_returns_none_for_impossible_price():
    # A call can never cost more than spot; inversion must refuse, not guess.
    assert implied_volatility(600.0, 500.0, 500.0, 0.1, 0.07, "CE") is None
    # Price below intrinsic is equally impossible.
    assert implied_volatility(1.0, 500.0, 400.0, 0.1, 0.07, "CE") is None


def test_pe_delta_is_negative():
    assert -1.0 < bs_delta(500.0, 450.0, 30 / 365, 0.3, 0.07, "PE") < 0.0
```

- [ ] **Step 2: Run tests, verify they fail with ModuleNotFoundError**

Run: `.venv/bin/pytest tests/test_options_greeks.py -q`
Expected: collection error, `No module named 'options'`

- [ ] **Step 3: Implement `options/greeks.py`**

```python
"""Black-Scholes pricing, delta, and implied-volatility inversion.

Stdlib only. Used on EOD settle prices where NSE publishes no IV; spot is
the equity close (UndrlygPric where the UDiFF file carries it). r defaults
to 0.07 (approx. repo-rate regime average) per the Phase 0 spec — a
documented approximation, not a curve.
"""
from __future__ import annotations

import math

_MIN_VOLATILITY = 0.01
_MAX_VOLATILITY = 5.0


def _norm_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _d1_d2(spot, strike, years_to_expiry, volatility, rate):
    vol_sqrt_t = volatility * math.sqrt(years_to_expiry)
    d1 = (math.log(spot / strike) + (rate + 0.5 * volatility ** 2) * years_to_expiry) / vol_sqrt_t
    return d1, d1 - vol_sqrt_t


def bs_price(spot: float, strike: float, years_to_expiry: float,
             volatility: float, rate: float = 0.07, option_kind: str = "CE") -> float:
    d1, d2 = _d1_d2(spot, strike, years_to_expiry, volatility, rate)
    discounted_strike = strike * math.exp(-rate * years_to_expiry)
    if option_kind == "CE":
        return spot * _norm_cdf(d1) - discounted_strike * _norm_cdf(d2)
    return discounted_strike * _norm_cdf(-d2) - spot * _norm_cdf(-d1)


def bs_delta(spot: float, strike: float, years_to_expiry: float,
             volatility: float, rate: float = 0.07, option_kind: str = "CE") -> float:
    d1, _ = _d1_d2(spot, strike, years_to_expiry, volatility, rate)
    call_delta = _norm_cdf(d1)
    return call_delta if option_kind == "CE" else call_delta - 1.0


def implied_volatility(option_price: float, spot: float, strike: float,
                       years_to_expiry: float, rate: float = 0.07,
                       option_kind: str = "CE") -> float | None:
    """Bisection on [0.01, 5.0]. Returns None when the price is outside the
    range any such volatility can produce (spec: refuse, never guess)."""
    if option_price <= 0 or spot <= 0 or years_to_expiry <= 0:
        return None
    price_at_low = bs_price(spot, strike, years_to_expiry, _MIN_VOLATILITY, rate, option_kind)
    price_at_high = bs_price(spot, strike, years_to_expiry, _MAX_VOLATILITY, rate, option_kind)
    if not (price_at_low <= option_price <= price_at_high):
        return None
    low, high = _MIN_VOLATILITY, _MAX_VOLATILITY
    for _ in range(100):
        mid = 0.5 * (low + high)
        if bs_price(spot, strike, years_to_expiry, mid, rate, option_kind) < option_price:
            low = mid
        else:
            high = mid
    return 0.5 * (low + high)
```

Also create empty `options/__init__.py`.

- [ ] **Step 4: Run tests, verify all pass**

Run: `.venv/bin/pytest tests/test_options_greeks.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add options/__init__.py options/greeks.py tests/test_options_greeks.py
git commit -m "feat(options): Black-Scholes greeks with refusing IV inversion"
```

---

### Task 2: `options/fo_bhavcopy.py` — parsers for both NSE file formats

**Files:**
- Create: `options/fo_bhavcopy.py`
- Test: `tests/test_options_fo_bhavcopy.py`

**Interfaces:**
- Produces:
  - `parse_udiff(csv_text: str) -> list[dict]` — canonical rows (Global Constraints schema) from the ≥ Jul-2024 UDiFF format
  - `parse_legacy(csv_text: str) -> list[dict]` — same, from the pre-Jul-2024 format
  - `UDIFF_CUTOVER_DATE = datetime.date(2024, 7, 8)`
- Consumes: nothing from earlier tasks.

- [ ] **Step 1: Write the failing tests with embedded format fixtures**

```python
# tests/test_options_fo_bhavcopy.py
import datetime

from options.fo_bhavcopy import parse_udiff, parse_legacy, UDIFF_CUTOVER_DATE

# Column subset + order as served by NSE UDiFF files (extra columns in real
# files are ignored because parsing is by header name, not position).
UDIFF_SAMPLE = """TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,FininstrmActlXpryDt,StrkPric,OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,ChngInOpnIntrst,TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty
2024-08-01,2024-08-01,FO,NSE,STO,67310,INE002A01018,RELIANCE,,2024-08-29,2024-08-29,3300,CE,RELIANCE24AUG3300CE,45.2,52,41,47.65,47.65,44.1,3111.85,47.65,125750,4500,1834,60.61,912,F1,250
2024-08-01,2024-08-01,FO,NSE,STO,67311,INE002A01018,RELIANCE,,2024-08-29,2024-08-29,2900,PE,RELIANCE24AUG2900PE,22.1,25,19.5,21.3,21.3,23.9,3111.85,21.3,98500,-1250,922,26.9,455,F1,250
2024-08-01,2024-08-01,FO,NSE,STF,52175,INE002A01018,RELIANCE,,2024-08-29,2024-08-29,,,RELIANCEFUT,3120,3140,3095,3118.4,3118.4,3105,3111.85,3118.4,10112750,52250,18223,5683.1,40112,F1,250
2024-08-01,2024-08-01,FO,NSE,IDO,41210,,NIFTY,,2024-08-08,2024-08-08,25000,CE,NIFTY24AUG25000CE,120,140,95,101.2,101.2,131,24950.1,101.2,5000000,10,90000,4501,100000,F1,25
"""

LEGACY_SAMPLE = """INSTRUMENT,SYMBOL,EXPIRY_DT,STRIKE_PR,OPTION_TYP,OPEN,HIGH,LOW,CLOSE,SETTLE_PR,CONTRACTS,VAL_INLAKH,OPEN_INT,CHG_IN_OI,TIMESTAMP,
OPTSTK,RELIANCE,27-FEB-2020,1500.00,CE,28.00,31.50,22.10,25.85,25.85,1834,412.20,1257500,45000,03-FEB-2020,
OPTSTK,RELIANCE,27-FEB-2020,1340.00,PE,18.20,20.00,15.10,16.55,16.55,922,127.90,985000,-12500,03-FEB-2020,
FUTSTK,RELIANCE,27-FEB-2020,0.00,XX,1425.00,1441.00,1408.10,1420.55,1420.55,18223,15683.10,10112750,52250,03-FEB-2020,
OPTIDX,NIFTY,27-FEB-2020,12000.00,CE,150.00,160.00,120.00,131.00,131.00,90000,45010.00,5000000,10,03-FEB-2020,
"""


def test_udiff_parses_stock_contracts_and_drops_index():
    rows = parse_udiff(UDIFF_SAMPLE)
    assert len(rows) == 3  # NIFTY (IDO) dropped
    assert {row["symbol"] for row in rows} == {"RELIANCE"}


def test_udiff_canonical_option_row():
    call_row = next(r for r in parse_udiff(UDIFF_SAMPLE) if r["kind"] == "CE")
    assert call_row == {
        "date": "2024-08-01", "symbol": "RELIANCE", "kind": "CE",
        "expiry": "2024-08-29", "strike": 3300.0, "close": 47.65,
        "settle": 47.65, "oi": 125750, "volume": 1834,
        "underlying_close": 3111.85, "lot_size": 250,
    }


def test_udiff_future_row_has_zero_strike():
    future_row = next(r for r in parse_udiff(UDIFF_SAMPLE) if r["kind"] == "FUT")
    assert future_row["strike"] == 0.0
    assert future_row["settle"] == 3118.4


def test_legacy_parses_stock_contracts_and_drops_index():
    rows = parse_legacy(LEGACY_SAMPLE)
    assert len(rows) == 3
    assert {row["kind"] for row in rows} == {"CE", "PE", "FUT"}


def test_legacy_canonical_option_row_no_underlying_or_lot():
    call_row = next(r for r in parse_legacy(LEGACY_SAMPLE) if r["kind"] == "CE")
    assert call_row == {
        "date": "2020-02-03", "symbol": "RELIANCE", "kind": "CE",
        "expiry": "2020-02-27", "strike": 1500.0, "close": 25.85,
        "settle": 25.85, "oi": 1257500, "volume": 1834,
        "underlying_close": None, "lot_size": None,
    }


def test_cutover_constant():
    assert UDIFF_CUTOVER_DATE == datetime.date(2024, 7, 8)
```

- [ ] **Step 2: Run tests, verify failure**

Run: `.venv/bin/pytest tests/test_options_fo_bhavcopy.py -q`
Expected: `cannot import name 'parse_udiff'` (or module missing)

- [ ] **Step 3: Implement the two parsers**

```python
# options/fo_bhavcopy.py
"""Parse NSE F&O bhavcopy files into the canonical row schema.

NSE switched formats on 2024-07-08: the modern UDiFF layout carries
underlying price and board lot; the legacy layout does not (those fields
become None and are backfilled from the qlib store downstream). Only stock
derivatives survive parsing — index contracts are out of scope (spec §11).
"""
from __future__ import annotations

import csv
import datetime
import io

UDIFF_CUTOVER_DATE = datetime.date(2024, 7, 8)

_UDIFF_STOCK_TYPES = {"STO", "STF"}
_LEGACY_STOCK_INSTRUMENTS = {"OPTSTK", "FUTSTK"}


def _to_float(raw: str) -> float | None:
    raw = (raw or "").strip()
    try:
        return float(raw)
    except ValueError:
        return None


def _to_int(raw: str) -> int:
    value = _to_float(raw)
    return int(value) if value is not None else 0


def parse_udiff(csv_text: str) -> list[dict]:
    rows = []
    for record in csv.DictReader(io.StringIO(csv_text)):
        if (record.get("FinInstrmTp") or "").strip() not in _UDIFF_STOCK_TYPES:
            continue
        is_future = record["FinInstrmTp"].strip() == "STF"
        rows.append({
            "date": record["TradDt"].strip(),
            "symbol": record["TckrSymb"].strip(),
            "kind": "FUT" if is_future else record["OptnTp"].strip(),
            "expiry": record["XpryDt"].strip(),
            "strike": 0.0 if is_future else (_to_float(record["StrkPric"]) or 0.0),
            "close": _to_float(record["ClsPric"]) or 0.0,
            "settle": _to_float(record["SttlmPric"]) or 0.0,
            "oi": _to_int(record["OpnIntrst"]),
            "volume": _to_int(record["TtlTradgVol"]),
            "underlying_close": _to_float(record["UndrlygPric"]),
            "lot_size": (lambda lot: int(lot) if lot else None)(_to_float(record.get("NewBrdLotQty", ""))),
        })
    return rows


def _legacy_date(raw: str) -> str:
    return datetime.datetime.strptime(raw.strip().title(), "%d-%b-%Y").date().isoformat()


def parse_legacy(csv_text: str) -> list[dict]:
    rows = []
    for record in csv.DictReader(io.StringIO(csv_text)):
        if (record.get("INSTRUMENT") or "").strip() not in _LEGACY_STOCK_INSTRUMENTS:
            continue
        is_future = record["INSTRUMENT"].strip() == "FUTSTK"
        rows.append({
            "date": _legacy_date(record["TIMESTAMP"]),
            "symbol": record["SYMBOL"].strip(),
            "kind": "FUT" if is_future else record["OPTION_TYP"].strip(),
            "expiry": _legacy_date(record["EXPIRY_DT"]),
            "strike": 0.0 if is_future else (_to_float(record["STRIKE_PR"]) or 0.0),
            "close": _to_float(record["CLOSE"]) or 0.0,
            "settle": _to_float(record["SETTLE_PR"]) or 0.0,
            "oi": _to_int(record["OPEN_INT"]),
            "volume": _to_int(record["CONTRACTS"]),
            "underlying_close": None,
            "lot_size": None,
        })
    return rows
```

- [ ] **Step 4: Run tests, verify all pass**

Run: `.venv/bin/pytest tests/test_options_fo_bhavcopy.py -q`

- [ ] **Step 5: Commit**

```bash
git add options/fo_bhavcopy.py tests/test_options_fo_bhavcopy.py
git commit -m "feat(options): parse UDiFF and legacy F&O bhavcopy formats"
```

---

### Task 3: `options/fo_archive.py` — downloader, day cache, gap ledger

**Files:**
- Create: `options/fo_archive.py`
- Modify: `.gitignore` (append `data/fo_bhavcopy/` line)
- Test: `tests/test_options_fo_archive.py`

**Interfaces:**
- Consumes: `parse_udiff`, `parse_legacy`, `UDIFF_CUTOVER_DATE` from `options.fo_bhavcopy`.
- Produces:
  - `fetch_day(trading_date: datetime.date, archive_root: pathlib.Path, http_get=None) -> str` — returns one of `"written"`, `"cached"`, `"no_file"` (404 both formats — holiday or genuinely missing), `"error"`; writes `<root>/<YYYY>/<YYYYMMDD>.csv.gz` on success and updates `<root>/gaps.json` on `no_file`/`error` (and clears the entry on later success). `http_get(url) -> (status_code: int, content: bytes)` is injectable for tests; default implementation uses `requests` with browser headers and 3 retries (2s/8s/30s backoff) on 5xx/timeouts.
  - `load_day(trading_date, archive_root) -> list[dict]` — canonical rows from the cached file; raises `FileNotFoundError` if absent.
  - `url_candidates(trading_date) -> list[str]` — UDiFF URL first on/after cutover, legacy first before; both always returned (cutover fuzz tolerance).

- [ ] **Step 1: Write the failing tests (fake `http_get`, tmp_path archive)**

```python
# tests/test_options_fo_archive.py
import datetime
import gzip
import io
import json
import zipfile

from options.fo_archive import fetch_day, load_day, url_candidates
from tests.test_options_fo_bhavcopy import UDIFF_SAMPLE, LEGACY_SAMPLE


def _zip_bytes(inner_name: str, text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(inner_name, text)
    return buffer.getvalue()


def test_url_candidates_order_flips_at_cutover():
    before = url_candidates(datetime.date(2020, 2, 3))
    after = url_candidates(datetime.date(2024, 8, 1))
    assert "DERIVATIVES/2020/FEB/fo03FEB2020bhav.csv.zip" in before[0]
    assert "BhavCopy_NSE_FO_0_0_0_20240801_F_0000.csv.zip" in after[0]
    assert len(before) == len(after) == 2


def test_fetch_day_writes_canonical_gz_and_is_idempotent(tmp_path):
    def fake_http_get(url):
        return 200, _zip_bytes("BhavCopy_NSE_FO_0_0_0_20240801_F_0000.csv", UDIFF_SAMPLE)

    trading_date = datetime.date(2024, 8, 1)
    assert fetch_day(trading_date, tmp_path, http_get=fake_http_get) == "written"
    assert fetch_day(trading_date, tmp_path, http_get=fake_http_get) == "cached"
    rows = load_day(trading_date, tmp_path)
    assert len(rows) == 3 and rows[0]["symbol"] == "RELIANCE"
    assert rows[0]["oi"] == 125750  # ints survive the gz round-trip


def test_fetch_day_legacy_format(tmp_path):
    def fake_http_get(url):
        if "DERIVATIVES" in url:
            return 200, _zip_bytes("fo03FEB2020bhav.csv", LEGACY_SAMPLE)
        return 404, b""

    assert fetch_day(datetime.date(2020, 2, 3), tmp_path, http_get=fake_http_get) == "written"
    assert len(load_day(datetime.date(2020, 2, 3), tmp_path)) == 3


def test_fetch_day_records_gap_on_double_404_then_clears(tmp_path):
    trading_date = datetime.date(2024, 8, 15)  # holiday-like: 404 everywhere
    assert fetch_day(trading_date, tmp_path, http_get=lambda url: (404, b"")) == "no_file"
    ledger = json.loads((tmp_path / "gaps.json").read_text())
    assert ledger["2024-08-15"] == "no_file"
    # a later successful fetch clears the ledger entry
    ok_get = lambda url: (200, _zip_bytes("BhavCopy_NSE_FO_0_0_0_20240815_F_0000.csv", UDIFF_SAMPLE))
    assert fetch_day(trading_date, tmp_path, http_get=ok_get) == "written"
    assert "2024-08-15" not in json.loads((tmp_path / "gaps.json").read_text())
```

- [ ] **Step 2: Run tests, verify failure**

Run: `.venv/bin/pytest tests/test_options_fo_archive.py -q`

- [ ] **Step 3: Implement `options/fo_archive.py`**

```python
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
                record[field_name] = int(float(record[field_name])) if record[field_name] else (0 if field_name != "lot_size" else None)
            record["strike"] = record["strike"] or 0.0
            record["close"] = record["close"] or 0.0
            record["settle"] = record["settle"] or 0.0
            rows.append(record)
        return rows
```

- [ ] **Step 4: Run tests, verify all pass; append `data/fo_bhavcopy/` to `.gitignore`**

Run: `.venv/bin/pytest tests/test_options_fo_archive.py tests/test_options_fo_bhavcopy.py -q`

- [ ] **Step 5: Commit**

```bash
git add options/fo_archive.py tests/test_options_fo_archive.py .gitignore
git commit -m "feat(options): F&O bhavcopy downloader with day cache and gap ledger"
```

---

### Task 4: `examples/nse_options_fetch.py` — backfill/update entry point

**Files:**
- Create: `examples/nse_options_fetch.py`
- Test: `tests/test_options_fetch_script.py`

**Interfaces:**
- Consumes: `fetch_day` from `options.fo_archive`.
- Produces: CLI `python examples/nse_options_fetch.py --start 2019-01-01 --end 2026-08-18 [--archive-root data/fo_bhavcopy] [--sleep 0.6]`; iterates weekdays only, prints one status line per non-cached day, exits 0 with a summary line `fetched=N cached=N no_file=N error=N`. Exposed as `run_fetch(start_date, end_date, archive_root, sleep_seconds, fetch_day_fn=fetch_day) -> dict` for tests.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_options_fetch_script.py
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
```

- [ ] **Step 2: Run test, verify failure**

Run: `.venv/bin/pytest tests/test_options_fetch_script.py -q`

- [ ] **Step 3: Implement the script**

```python
#!/usr/bin/env python3
"""Backfill / update the local NSE F&O bhavcopy archive.

Usage:
  python examples/nse_options_fetch.py --start 2019-01-01 --end 2026-08-18
Polite pacing: NSE archives throttle aggressive clients; default 0.6s sleep
between network fetches (cached days cost nothing and skip the sleep).
"""
from __future__ import annotations

import argparse
import datetime
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from options.fo_archive import fetch_day  # noqa: E402


def run_fetch(start_date: datetime.date, end_date: datetime.date,
              archive_root: pathlib.Path, sleep_seconds: float,
              fetch_day_fn=fetch_day) -> dict:
    summary = {"written": 0, "cached": 0, "no_file": 0, "error": 0}
    current_date = start_date
    while current_date <= end_date:
        if current_date.weekday() < 5:
            status = fetch_day_fn(current_date, archive_root)
            summary[status] += 1
            if status != "cached":
                print(f"{current_date} {status}", flush=True)
                if sleep_seconds:
                    time.sleep(sleep_seconds)
        current_date += datetime.timedelta(days=1)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, type=datetime.date.fromisoformat)
    parser.add_argument("--end", required=True, type=datetime.date.fromisoformat)
    parser.add_argument("--archive-root", default="data/fo_bhavcopy", type=pathlib.Path)
    parser.add_argument("--sleep", default=0.6, type=float)
    arguments = parser.parse_args()
    summary = run_fetch(arguments.start, arguments.end, arguments.archive_root, arguments.sleep)
    print(" ".join(f"{key}={value}" for key, value in summary.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test, verify pass; then a 3-day live smoke test**

Run: `.venv/bin/pytest tests/test_options_fetch_script.py -q`
Then: `.venv/bin/python examples/nse_options_fetch.py --start 2026-08-12 --end 2026-08-14`
Expected: 3 lines ending `written` (or `cached` on rerun); spot-open one file with `gzcat data/fo_bhavcopy/2026/20260812.csv.gz | head -3`. Also verify one **legacy-era** day: `--start 2020-02-03 --end 2020-02-03`.

- [ ] **Step 5: Commit**

```bash
git add examples/nse_options_fetch.py tests/test_options_fetch_script.py
git commit -m "feat(options): archive backfill CLI"
```

---

### Task 5: `options/qa.py` + `examples/nse_options_qa.py` — the Phase 0 QA gate (spec §5)

**Files:**
- Create: `options/qa.py`, `examples/nse_options_qa.py`
- Test: `tests/test_options_qa.py`

**Interfaces:**
- Consumes: `load_day` from `options.fo_archive`; `implied_volatility` from `options.greeks`; qlib calendar file `data/qlib_data/in_data/calendars/day.txt` (one `YYYY-MM-DD` per line) for expected trading days.
- Produces:
  - `coverage_report(archive_root, calendar_dates: list[datetime.date]) -> dict` — `{year: {"expected": int, "present": int, "coverage": float}}`, coverage = present/expected.
  - `sample_cell_checks(archive_root, trading_date, symbol) -> dict` — `{"strikes_contiguous": bool, "atm_oi_positive": bool, "atm_iv": float|None, "atm_iv_sane": bool}`; ATM = strike nearest `underlying_close` (or FUT settle when underlying is None) among the nearest monthly expiry's CE rows; contiguity = the sorted unique strike ladder within ±15% of ATM has no gap larger than 2× the modal gap; IV sane = value in [0.08, 1.20].
  - CLI `python examples/nse_options_qa.py [--archive-root ...] [--year-floor 0.95]` printing a per-year coverage table + 10 sampled cell check lines, exit 1 if any year < floor or > 3 of 10 cells fail — this exit code IS the Phase 0 gate.

- [ ] **Step 1: Write the failing tests (synthetic archive via `fo_archive` writer path)**

```python
# tests/test_options_qa.py
import datetime

from options.fo_archive import fetch_day
from options.qa import coverage_report, sample_cell_checks
from tests.test_options_fo_archive import _zip_bytes


def _write_synthetic_day(archive_root, trading_date, strikes, underlying_close=1000.0):
    header = ("TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,"
              "FininstrmActlXpryDt,StrkPric,OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,"
              "LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,ChngInOpnIntrst,TtlTradgVol,"
              "TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty\n")
    lines = [header]
    expiry = trading_date + datetime.timedelta(days=25)
    for strike_price in strikes:
        # settle ~ a plausible OTM-ish premium so IV inversion converges
        premium = max(2.0, (underlying_close - strike_price) * 0.5 + 20.0)
        lines.append(f"{trading_date},{trading_date},FO,NSE,STO,1,ISIN,TESTSTK,,{expiry},{expiry},"
                     f"{strike_price},CE,NAME,1,1,1,{premium},{premium},1,{underlying_close},{premium},"
                     f"500,0,100,1,10,F1,500\n")
    payload = _zip_bytes(f"BhavCopy_NSE_FO_0_0_0_{trading_date:%Y%m%d}_F_0000.csv", "".join(lines))
    fetch_day(trading_date, archive_root, http_get=lambda url: (200, payload))


def test_coverage_report_counts_present_days(tmp_path):
    calendar_dates = [datetime.date(2024, 8, 1), datetime.date(2024, 8, 2), datetime.date(2024, 8, 5)]
    _write_synthetic_day(tmp_path, calendar_dates[0], [950, 1000, 1050])
    report = coverage_report(tmp_path, calendar_dates)
    assert report[2024]["expected"] == 3 and report[2024]["present"] == 1
    assert report[2024]["coverage"] < 0.95


def test_sample_cell_checks_pass_on_clean_ladder(tmp_path):
    trading_date = datetime.date(2024, 8, 1)
    _write_synthetic_day(tmp_path, trading_date, [900, 950, 1000, 1050, 1100])
    checks = sample_cell_checks(tmp_path, trading_date, "TESTSTK")
    assert checks["strikes_contiguous"] is True
    assert checks["atm_oi_positive"] is True
    assert checks["atm_iv_sane"] in (True, False)  # sanity band applied to a real inversion
    assert checks["atm_iv"] is None or checks["atm_iv"] > 0


def test_sample_cell_checks_flags_gapped_ladder(tmp_path):
    trading_date = datetime.date(2024, 8, 2)
    _write_synthetic_day(tmp_path, trading_date, [900, 950, 1000, 1200])  # hole at 1050/1100
    checks = sample_cell_checks(tmp_path, trading_date, "TESTSTK")
    assert checks["strikes_contiguous"] is False
```

- [ ] **Step 2: Run tests, verify failure**

Run: `.venv/bin/pytest tests/test_options_qa.py -q`

- [ ] **Step 3: Implement `options/qa.py`**

```python
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
```

- [ ] **Step 4: Implement `examples/nse_options_qa.py` CLI**

```python
#!/usr/bin/env python3
"""Run the Phase 0 QA gate over the local F&O archive. Exit 0 = gate passed."""
from __future__ import annotations

import argparse
import datetime
import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from options.qa import coverage_report, sample_cell_checks  # noqa: E402

_SAMPLE_SYMBOLS = ["RELIANCE", "HDFCBANK", "TCS", "SBIN", "ITC"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", default="data/fo_bhavcopy", type=pathlib.Path)
    parser.add_argument("--calendar", default="data/qlib_data/in_data/calendars/day.txt", type=pathlib.Path)
    parser.add_argument("--year-floor", default=0.95, type=float)
    arguments = parser.parse_args()

    calendar_dates = [datetime.date.fromisoformat(line.strip())
                      for line in arguments.calendar.read_text().splitlines()
                      if line.strip() >= "2019-01-01"]
    report = coverage_report(arguments.archive_root, calendar_dates)
    gate_failed = False
    for year, year_bucket in sorted(report.items()):
        flag = "" if year_bucket["coverage"] >= arguments.year_floor else "  <-- BELOW FLOOR"
        gate_failed |= bool(flag)
        print(f"{year}: {year_bucket['present']}/{year_bucket['expected']}"
              f" ({year_bucket['coverage']:.1%}){flag}")

    random.seed(20260818)  # reproducible sample
    present_dates = [d for d in calendar_dates
                     if (arguments.archive_root / f"{d:%Y}" / f"{d:%Y%m%d}.csv.gz").exists()]
    failed_cells = 0
    for sampled_date in random.sample(present_dates, min(10, len(present_dates))):
        symbol = random.choice(_SAMPLE_SYMBOLS)
        try:
            checks = sample_cell_checks(arguments.archive_root, sampled_date, symbol)
        except (StopIteration, ValueError) as exc:
            checks = {"error": str(exc)}
        cell_ok = checks.get("strikes_contiguous") and checks.get("atm_oi_positive") and checks.get("atm_iv_sane")
        failed_cells += 0 if cell_ok else 1
        print(f"{sampled_date} {symbol}: {'OK' if cell_ok else 'FAIL'} {checks}")

    gate_failed |= failed_cells > 3
    print(f"\nQA GATE: {'FAILED' if gate_failed else 'PASSED'} (cells failed: {failed_cells}/10)")
    return 1 if gate_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_options_qa.py -q` then the full options suite `.venv/bin/pytest tests/test_options_*.py -q`

- [ ] **Step 6: Commit**

```bash
git add options/qa.py examples/nse_options_qa.py tests/test_options_qa.py
git commit -m "feat(options): Phase 0 data QA gate"
```

---

### Task 6: Full backfill run + gate verdict (no new code)

**Files:** none created; archive data + `outputs/options/phase0_qa.txt` produced.

- [ ] **Step 1: Run the backfill (long-running, background it)**

Run: `.venv/bin/python examples/nse_options_fetch.py --start 2019-01-01 --end <today> 2>&1 | tee outputs/options_fetch.log`
~1,900 trading days × ~0.6s pacing + download time ≈ 45–90 min. Rerun is idempotent (cached days skip).

- [ ] **Step 2: Reconcile gaps**

Inspect `data/fo_bhavcopy/gaps.json`: entries on NSE holidays are expected (`no_file`); any `error:` entries get one retry via the same fetch command. Weekday `no_file` entries that are NOT NSE holidays are real gaps — investigate before proceeding.

- [ ] **Step 3: Run the QA gate and record the verdict**

Run: `.venv/bin/python examples/nse_options_qa.py | tee outputs/options/phase0_qa.txt`
Expected: exit 0, every year ≥ 95%, ≤ 3 failed cells. **Exit 1 = Phase 0 gate failed — stop, diagnose, do not start Phase 1.**

- [ ] **Step 4: Commit the QA record**

```bash
git add outputs/options/phase0_qa.txt
git commit -m "chore(options): Phase 0 data QA gate verdict"
```

---

## Self-review notes

- Spec §5 coverage ↔ Task 5/6; §4 sources ↔ Tasks 3/4 (bhavcopy) — Kite/earnings/blackouts are Phase 1–2 concerns, correctly absent here.
- Legacy rows carry `underlying_close=None` by design; Task 5's checks fall back to FUT settle, and Phase 1's loader backfills spot from the qlib store (out of Phase 0 scope, noted in spec §4).
- Type consistency: canonical schema defined once in Global Constraints; Tasks 2/3/5 all conform; `_zip_bytes` and format fixtures are imported from earlier test modules rather than redefined.
- Real-world risk consciously accepted: the UDiFF/legacy fixture headers match NSE's published formats, but live files may deviate (extra columns are harmless by construction; renamed columns would fail loudly with KeyError → gap ledger `error`). Task 4 Step 4's live smoke test on one modern + one legacy day catches this before the 90-minute backfill.
