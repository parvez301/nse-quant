#!/usr/bin/env python3
"""ETL: dump qlib OHLCV + walk-forward model scores to partitioned Parquet,
plus a precomputed symbols.json index so the analytics Lambda doesn't have to
scan every partition on cold start.

Output layout:
  outputs/analytics/prices/year=YYYY/data.parquet   (date, symbol, OHLCV, factor, adv20)
  outputs/analytics/scores/year=YYYY/data.parquet   (date, symbol, score)
  outputs/analytics/symbols.json                    [{symbol, first_date, last_date, n_bars}]

Run from repo root:
  ./.venv/bin/python examples/nse_export_analytics.py
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import pandas as pd


def enrich_prices(raw: pd.DataFrame) -> pd.DataFrame:
    """Pure: take a (symbol, date, OHLCV, factor) DataFrame and add adv20.

    `adv20` = 20-day rolling mean of close*volume per symbol, in INR.
    Used by the slippage / cost-sensitivity panel as a liquidity proxy.
    """
    df = raw.copy().sort_values(["symbol", "date"])
    df["turnover"] = df["close"].fillna(0) * df["volume"].fillna(0)
    df["adv20"] = (
        df.groupby("symbol")["turnover"]
          .rolling(20, min_periods=5)
          .mean()
          .reset_index(level=0, drop=True)
    )
    return df.drop(columns=["turnover"])


def write_partitioned_by_year(df: pd.DataFrame, out_dir: Path) -> dict[int, dict]:
    """Pure-ish: split `df` (must have a `date` column) by calendar year and
    write each partition to `out_dir/year=YYYY/data.parquet`.
    """
    df = df.copy()
    df["year"] = df["date"].dt.year
    written: dict[int, dict] = {}
    for year, g in df.groupby("year"):
        g = g.drop(columns=["year"])
        path = out_dir / f"year={int(year)}" / "data.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        g.to_parquet(path, index=False, compression="snappy")
        written[int(year)] = {
            "rows": len(g), "path": str(path), "bytes": path.stat().st_size,
        }
    return written


def build_symbols_index(prices: pd.DataFrame) -> list[dict]:
    """Per-symbol first/last bar + count, sorted by symbol. Pure function."""
    g = prices.groupby("symbol")["date"].agg(["min", "max", "count"])
    out = []
    for sym, row in g.iterrows():
        out.append({
            "symbol": sym,
            "first_date": str(row["min"].date()),
            "last_date":  str(row["max"].date()),
            "n_bars": int(row["count"]),
        })
    out.sort(key=lambda r: r["symbol"])
    return out


def export_prices(provider_uri: str, out_root: Path) -> dict:
    """Read full OHLCV from qlib and write per-year Parquet files +
    a precomputed symbols.json index so the analytics Lambda can answer
    /api/analytics/symbols without scanning every partition."""
    import qlib
    from qlib.data import D

    qlib.init(provider_uri=os.path.expanduser(provider_uri), region="cn")
    instruments = D.list_instruments(D.instruments(market="all"), as_list=True)
    instruments = [s for s in instruments if s not in ("NIFTY50", "SENSEX")]

    fields = ["$close", "$open", "$high", "$low", "$volume", "$factor"]
    df = D.features(instruments, fields, freq="day")
    if df.empty:
        raise SystemExit("[abort] qlib returned empty OHLCV")

    df = df.rename(columns=lambda c: c.lstrip("$"))
    df = df.reset_index().rename(
        columns={"datetime": "date", "instrument": "symbol"}
    )
    df = enrich_prices(df)
    written = write_partitioned_by_year(df, out_root / "prices")

    symbols_index = build_symbols_index(df)
    (out_root / "symbols.json").write_text(json.dumps(symbols_index))

    return {
        "rows_total": int(len(df)),
        "n_symbols": int(df["symbol"].nunique()),
        "date_min": str(df["date"].min().date()),
        "date_max": str(df["date"].max().date()),
        "by_year": written,
        "symbols_index_rows": len(symbols_index),
    }


def export_scores(model_dir: Path, out_root: Path) -> dict:
    """Dump pred.pkl (walk-forward model scores) into per-year Parquet."""
    pred_path = model_dir / "pred.pkl"
    if not pred_path.exists():
        raise SystemExit(f"[abort] {pred_path} not found")
    pred = pd.read_pickle(pred_path)
    if isinstance(pred, pd.Series):
        pred = pred.to_frame("score")
    if "score" not in pred.columns:
        pred.columns = ["score"]

    df = pred.reset_index().rename(
        columns={"datetime": "date", "instrument": "symbol"}
    )
    written = write_partitioned_by_year(df, out_root / "scores")

    return {
        "rows_total": int(len(df)),
        "n_symbols": int(df["symbol"].nunique()),
        "date_min": str(df["date"].min().date()),
        "date_max": str(df["date"].max().date()),
        "by_year": written,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--provider_uri", default="data/qlib_data/in_data")
    p.add_argument("--model_dir", default="outputs/nse_baseline_750_long")
    p.add_argument("--out", default="outputs/analytics")
    args = p.parse_args()

    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)

    print(f"[etl] exporting prices from {args.provider_uri}")
    px_stats = export_prices(args.provider_uri, out_root)
    print(f"[etl] prices: {px_stats['rows_total']:,} rows, "
          f"{px_stats['n_symbols']} symbols, {px_stats['date_min']}..{px_stats['date_max']}")

    print(f"[etl] exporting scores from {args.model_dir}")
    sc_stats = export_scores(Path(args.model_dir), out_root)
    print(f"[etl] scores: {sc_stats['rows_total']:,} rows, "
          f"{sc_stats['n_symbols']} symbols, {sc_stats['date_min']}..{sc_stats['date_max']}")

    # Manifest: a tiny JSON the Lambda can GET on every request to detect
    # whether its in-memory cache is stale. Generation timestamp + last bar
    # date together change once per cron run.
    from datetime import datetime, timezone
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "prices_last_date": px_stats["date_max"],
        "scores_last_date": sc_stats["date_max"],
        "n_symbols": px_stats["n_symbols"],
    }
    (out_root / "manifest.json").write_text(json.dumps(manifest))
    print(f"[etl] manifest: {manifest}")

    total_bytes = (
        sum(b["bytes"] for b in px_stats["by_year"].values())
        + sum(b["bytes"] for b in sc_stats["by_year"].values())
    )
    print(f"[etl] total parquet footprint: {total_bytes / 1024 / 1024:.1f} MB "
          f"across {len(px_stats['by_year']) + len(sc_stats['by_year'])} files")


if __name__ == "__main__":
    main()
