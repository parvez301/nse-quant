#!/usr/bin/env python3
"""Download Indian-equity daily OHLCV from yfinance and dump to Qlib binary format.

Universe (default): union of NIFTY 500 + Next 50 + Midcap 150 + Smallcap 250 + an
extra hardcoded BSE-only liquid list. Each symbol is fetched on NSE first
(yfinance ".NS"); if NSE returns no data, BSE (".BO") is tried as a fallback.
This naturally covers both exchanges without creating dual-listed duplicates.

Usage:
  # full refresh — 20 years of OHLCV for the whole liquid Indian universe
  python examples/nse_data_loader.py

  # incremental — fetch only new bars since each CSV's last date (use daily)
  python examples/nse_data_loader.py --incremental

  # restrict to one or two indices for a faster smoke test
  python examples/nse_data_loader.py --indices nifty500 niftynext50

  # custom tickers
  python examples/nse_data_loader.py --tickers RELIANCE TCS INFY HDFCBANK

  # reuse existing CSVs, just redo the Qlib bin dump
  python examples/nse_data_loader.py --skip_download

Output:
  data/qlib_data/in_data/            <- Qlib binary data root (use this with qlib.init)
  data/qlib_data/in_data/_csv/       <- per-stock CSVs (incremental-friendly)
"""
import argparse
import concurrent.futures
import os
import subprocess
import sys
import urllib.request
from io import StringIO
from pathlib import Path

import pandas as pd


# ----------------------------------------------------------------------------
# Index source URLs (NSE archives, free + reliable)
# ----------------------------------------------------------------------------

INDEX_URLS = {
    # NIFTY Total Market = 750 stocks = NIFTY 500 + NIFTY Microcap 250.
    # This is the broadest official NSE index and covers essentially every
    # tradeable Indian equity. Use this as the default.
    "niftytotalmarket": "https://archives.nseindia.com/content/indices/ind_niftytotalmarket_list.csv",
    # Microcap 250 alone — names beyond NIFTY 500.
    "niftymicrocap250": "https://archives.nseindia.com/content/indices/ind_niftymicrocap250_list.csv",
    # Sub-indices (subsets of Total Market — useful for smoke tests):
    "nifty500":         "https://archives.nseindia.com/content/indices/ind_nifty500list.csv",
    "niftynext50":      "https://archives.nseindia.com/content/indices/ind_niftynext50list.csv",
    "niftymidcap150":   "https://archives.nseindia.com/content/indices/ind_niftymidcap150list.csv",
    "niftysmallcap250": "https://archives.nseindia.com/content/indices/ind_niftysmallcap250list.csv",
    "nifty100":         "https://archives.nseindia.com/content/indices/ind_nifty100list.csv",
    "nifty50":          "https://archives.nseindia.com/content/indices/ind_nifty50list.csv",
}

DEFAULT_INDICES = ["niftytotalmarket"]

# BSE-only liquid names (best-effort hardcoded — not exhaustive). Most Indian
# stocks worth trading are on NSE; this list covers a small set of names with
# real BSE-side liquidity that aren't in the NSE indices above.
BSE_ONLY = [
    "BBTC",          # Bombay Burmah Trading Corp
    "CAPRIHANS",     # Caprihans India
    "GTLINFRA",      # GTL Infrastructure
    "ASHIKACR",      # Ashika Credit Capital
    "MAGADSUGAR",    # Magadh Sugar
    "GANDHITUBE",    # Gandhi Special Tubes
    "BIRLAMONEY",    # Aditya Birla Money
    "INDOTECH",      # Indo Tech Transformers
    "INSPIRISYS",    # Inspirisys Solutions
    "STANCEM",       # Star Cement
    "EUROBOND",      # Euro Industries
    "BIRLATYRE",     # Birla Tyres
    "RAJESHEXPO",    # Rajesh Exports (also on NSE as RAJESHEXPO, but BSE is primary for some)
    "CARERATING",    # CARE Ratings (also on NSE)
    "DRLALPATHLAB",  # Dr Lal PathLabs (also on NSE)
]

NIFTY_50_FALLBACK = [
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BEL", "BHARTIARTL",
    "BRITANNIA", "CIPLA", "COALINDIA", "DRREDDY", "EICHERMOT",
    "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO",
    "HINDALCO", "HINDUNILVR", "ICICIBANK", "ITC", "INDUSINDBK",
    "INFY", "JSWSTEEL", "KOTAKBANK", "LT", "M&M",
    "MARUTI", "NTPC", "NESTLEIND", "ONGC", "POWERGRID",
    "RELIANCE", "SBILIFE", "SHRIRAMFIN", "SBIN", "SUNPHARMA",
    "TCS", "TATACONSUM", "TATAMOTORS", "TATASTEEL", "TECHM",
    "TITAN", "TRENT", "ULTRACEMCO", "WIPRO", "ZOMATO",
]

BENCHMARK_YF = "^NSEI"           # NIFTY 50 index
BENCHMARK_SYMBOL = "NIFTY50"
BSE_BENCHMARK_YF = "^BSESN"      # SENSEX
BSE_BENCHMARK_SYMBOL = "SENSEX"
DUMP_BIN_URL = "https://raw.githubusercontent.com/microsoft/qlib/main/scripts/dump_bin.py"


# ----------------------------------------------------------------------------
# Ticker list resolution
# ----------------------------------------------------------------------------

def _fetch_csv(url: str) -> list[str]:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8", errors="ignore")
    return pd.read_csv(StringIO(body))["Symbol"].str.strip().str.upper().tolist()


def fetch_index(name: str) -> list[str]:
    if name not in INDEX_URLS:
        print(f"[warn] unknown index '{name}', skipping")
        return []
    try:
        tickers = _fetch_csv(INDEX_URLS[name])
        print(f"[tickers] fetched {len(tickers)} from {name}")
        return tickers
    except Exception as exc:
        print(f"[warn] {name} fetch failed ({exc})")
        return []


def assemble_universe(indices: list[str], include_bse: bool) -> list[str]:
    seen = set()
    ordered = []
    for idx in indices:
        for t in fetch_index(idx):
            if t and t not in seen:
                seen.add(t)
                ordered.append(t)
    if include_bse:
        for t in BSE_ONLY:
            if t not in seen:
                seen.add(t)
                ordered.append(t)
    if not ordered:
        print(f"[warn] all index fetches failed, falling back to NIFTY 50 hardcoded")
        return list(NIFTY_50_FALLBACK)
    return ordered


# ----------------------------------------------------------------------------
# yfinance download (with NSE -> BSE fallback)
# ----------------------------------------------------------------------------

def _flatten_yf_columns(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df = df.droplevel(1, axis=1)
    df.columns = [str(c).lower() for c in df.columns]
    return df


OHLC_COLUMNS = ["open", "high", "low", "close"]


def _drop_unusable_bars(df: pd.DataFrame) -> pd.DataFrame:
    """Drop rows whose OHLC is not fully populated.

    Yahoo publishes the previous session's bar with `volume` filled but the
    price fields null for a large slice of NSE names, and only backfills the
    prices ~a day after the close. Letting those rows through advances the
    Qlib calendar to a date whose close is NaN, which makes stale data look
    fresh to every downstream consumer and trips the coverage gate in
    nse_safety.check_data.

    Zero volume is deliberately left alone — illiquid microcaps legitimately
    print a no-trade session, and those bars carry usable prices.
    """
    return df.dropna(subset=OHLC_COLUMNS)


def _yf_one(yf_symbol: str, start: str, end: str):
    import yfinance as yf
    df = yf.download(
        yf_symbol,
        start=start, end=end,
        interval="1d",
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    if df is None or df.empty:
        return None
    df = _flatten_yf_columns(df.reset_index())
    needed = {"date", "open", "high", "low", "close", "volume"}
    if not needed.issubset(df.columns):
        return None
    df = _drop_unusable_bars(df)
    if df.empty:
        return None
    return df


def download_one(symbol: str, start: str, end: str, out_dir: Path,
                 incremental: bool, force_yf_symbol: str | None = None):
    """Download one ticker. Tries .NS first, then .BO. Honors incremental mode.

    Returns (symbol, n_bars_or_error_code, exchange_used).
    """
    csv_path = out_dir / f"{symbol}.csv"

    # Incremental: only fetch from after the last date already on disk
    real_start = start
    existing = None
    if incremental and csv_path.exists():
        try:
            existing = pd.read_csv(csv_path, parse_dates=["date"])
            last_date = existing["date"].max()
            if pd.notna(last_date):
                # ask for at least 7 days back to refresh recent stale bars (handles late-arriving adjustments)
                real_start = (last_date - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
        except Exception:
            existing = None

    candidates = [force_yf_symbol] if force_yf_symbol else [f"{symbol}.NS", f"{symbol}.BO"]

    df = None
    used_yf = None
    for yf_sym in candidates:
        if yf_sym is None:
            continue
        try:
            df = _yf_one(yf_sym, real_start, end)
        except Exception:
            df = None
        if df is not None and len(df) >= (1 if incremental else 100):
            used_yf = yf_sym
            break

    if df is None:
        return symbol, 0, None

    df["symbol"] = symbol
    df["factor"] = 1.0
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df = df[["date", "symbol", "open", "high", "low", "close", "volume", "factor"]]

    # Merge with existing if incremental
    if incremental and existing is not None and len(existing):
        existing["date"] = pd.to_datetime(existing["date"]).dt.strftime("%Y-%m-%d")
        merged = pd.concat([existing[df.columns], df], ignore_index=True)
        merged = merged.drop_duplicates(subset=["date"], keep="last").sort_values("date")
        df = merged

    df.to_csv(csv_path, index=False)
    return symbol, len(df), used_yf.split(".")[-1] if used_yf else None


def download_all(pairs, start: str, end: str, out_dir: Path, workers: int,
                 incremental: bool):
    out_dir.mkdir(parents=True, exist_ok=True)
    counts = {"NS": 0, "BO": 0, "EMPTY": 0, "ERR": 0}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {
            ex.submit(download_one, sym, start, end, out_dir, incremental, force): sym
            for sym, force in pairs
        }
        total = len(futs)
        for i, fut in enumerate(concurrent.futures.as_completed(futs), 1):
            try:
                sym, n, exch = fut.result()
            except Exception as exc:
                sym = futs[fut]
                n, exch = -1, None
            if n > 0 and exch:
                counts[exch] = counts.get(exch, 0) + 1
                status = f"{n:5d} bars [{exch}]"
            elif n > 0:
                counts["NS"] += 1
                status = f"{n:5d} bars"
            elif n == 0:
                counts["EMPTY"] += 1
                status = "EMPTY"
            else:
                counts["ERR"] += 1
                status = f"ERR({n})"
            if i <= 50 or i % 20 == 0 or i == total:
                print(f"[{i:4d}/{total}] {sym:14s} {status}")
    print(f"\n[download] NSE-fetched={counts.get('NS',0)} BSE-fetched={counts.get('BO',0)} "
          f"empty={counts['EMPTY']} err={counts['ERR']}")
    return counts.get("NS", 0) + counts.get("BO", 0)


# ----------------------------------------------------------------------------
# Qlib bin dump
# ----------------------------------------------------------------------------

def ensure_dump_bin_script() -> Path:
    target = Path.home() / ".cache" / "kronos" / "dump_bin.py"
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    print(f"[setup] downloading dump_bin.py -> {target}")
    req = urllib.request.Request(DUMP_BIN_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        target.write_bytes(resp.read())
    return target


def dump_to_qlib(csv_dir: Path, qlib_dir: Path):
    qlib_dir.mkdir(parents=True, exist_ok=True)
    script = ensure_dump_bin_script()
    cmd = [
        sys.executable, str(script), "dump_all",
        "--data_path", str(csv_dir),
        "--qlib_dir", str(qlib_dir),
        "--include_fields", "open,high,low,close,volume,factor",
        "--date_field_name", "date",
        "--symbol_field_name", "symbol",
    ]
    print(f"[dump] {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(
        description="Indian-equities OHLCV -> Qlib binary loader (NSE primary, BSE fallback)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--out", default=os.path.expanduser("data/qlib_data/in_data"))
    p.add_argument("--csv_dir", default=None)
    p.add_argument("--start", default="2005-01-01",
                   help="earliest date to fetch (default: 2005 = 20 years)")
    p.add_argument("--end", default=pd.Timestamp.today().strftime("%Y-%m-%d"))
    p.add_argument("--indices", nargs="+", default=DEFAULT_INDICES,
                   choices=list(INDEX_URLS.keys()),
                   help="NSE indices to combine for the universe")
    p.add_argument("--include_bse", action="store_true", default=True,
                   help="also include hardcoded BSE-only liquid stocks")
    p.add_argument("--no_bse", dest="include_bse", action="store_false",
                   help="skip BSE-only stocks (NSE indices only)")
    p.add_argument("--tickers", nargs="+", default=None,
                   help="override universe with explicit ticker list")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--incremental", action="store_true",
                   help="fetch only new bars since each CSV's last date (daily-cron use)")
    p.add_argument("--skip_download", action="store_true")
    p.add_argument("--skip_benchmark", action="store_true")
    p.add_argument("--skip_dump", action="store_true",
                   help="don't rebuild Qlib binary after download")
    p.add_argument("--dump_only", action="store_true",
                   help="rebuild the Qlib binary from the existing CSVs and nothing "
                        "else — no universe assembly, no download. Used by the daily "
                        "cron to re-dump after nse_eod_repair.py patches the CSVs.")
    args = p.parse_args()

    qlib_dir = Path(args.out).expanduser()
    csv_dir = Path(args.csv_dir).expanduser() if args.csv_dir else (qlib_dir / "_csv")

    # ----- dump-only fast path -----
    # Deliberately skips assemble_universe: that hits NSE for index membership,
    # and a second network dependency in the re-dump pass would reintroduce the
    # very fragility this path exists to avoid.
    if args.dump_only:
        if not csv_dir.exists():
            sys.exit(f"[abort] --dump_only set but {csv_dir} does not exist")
        try:
            import qlib  # noqa: F401
        except ImportError:
            sys.exit("pyqlib not installed. Run: pip install pyqlib")
        print(f"[plan] dump-only from {csv_dir} -> {qlib_dir}")
        dump_to_qlib(csv_dir, qlib_dir)
        print(f"\n Qlib binary dataset rebuilt at: {qlib_dir}")
        return

    # ----- universe -----
    if args.tickers:
        base_tickers = [t.upper() for t in args.tickers]
    else:
        base_tickers = assemble_universe(args.indices, args.include_bse)

    pairs: list[tuple[str, str | None]] = [(sym, None) for sym in base_tickers]
    if not args.skip_benchmark:
        pairs.append((BENCHMARK_SYMBOL, BENCHMARK_YF))
        pairs.append((BSE_BENCHMARK_SYMBOL, BSE_BENCHMARK_YF))

    print(f"[plan] universe={len(base_tickers)} stocks  +{2 if not args.skip_benchmark else 0} benchmarks")
    print(f"[plan] csv_dir={csv_dir}  qlib_dir={qlib_dir}")
    print(f"[plan] range={args.start} -> {args.end}  "
          f"incremental={args.incremental}  bse_fallback=on")

    # ----- download -----
    if not args.skip_download:
        try:
            import yfinance  # noqa: F401
        except ImportError:
            sys.exit("yfinance not installed. Run: pip install yfinance")
        nok = download_all(pairs, args.start, args.end, csv_dir, args.workers, args.incremental)
        if nok == 0:
            sys.exit("[abort] 0 successful downloads — check network / tickers")
    elif not csv_dir.exists():
        sys.exit(f"[abort] --skip_download set but {csv_dir} does not exist")

    # ----- dump to qlib -----
    if not args.skip_dump:
        try:
            import qlib  # noqa: F401
        except ImportError:
            sys.exit("pyqlib not installed. Run: pip install pyqlib")
        dump_to_qlib(csv_dir, qlib_dir)

        print("\n=================================================================")
        print(f" Qlib binary dataset ready at: {qlib_dir}")
        print("=================================================================")
        print("Sanity check:\n")
        print("  import qlib")
        print("  from qlib.data import D")
        print(f"  qlib.init(provider_uri={str(qlib_dir)!r}, region='cn')")
        print("  print(D.features(['RELIANCE'], ['$close', '$volume'],")
        print("                   start_time='2024-01-01', end_time='2024-03-01').head())")
        print()
        print(f"  Benchmarks loaded as instruments: {BENCHMARK_SYMBOL!r}, {BSE_BENCHMARK_SYMBOL!r}")


if __name__ == "__main__":
    main()
