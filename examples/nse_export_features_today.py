#!/usr/bin/env python3
"""ETL extension: compute Alpha158 features for the symbols on today's
decision list (BUY + HOLD + SELL) and write them to a single small Parquet.

Why scoped to today's universe only? Computing all 158 features for the full
750-stock × 15-year history takes ~7 hours — way over the cron's 11-min
budget. The "why this BUY today?" attribution endpoint only needs TODAY's
features for the ~50 symbols actually under consideration. That run takes
~30 seconds and adds ~30 KB to S3.

Output:
  outputs/analytics/features_today.parquet
    columns: date, symbol, KMID, KLEN, ... (158 alpha cols)

Run from repo root:
  ./.venv/bin/python examples/nse_export_features_today.py
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import pandas as pd


def collect_universe(decisions_dir: Path) -> tuple[str, list[str]]:
    """Read the most recent decision JSON and return (date, list of symbols)."""
    latest = sorted(decisions_dir.glob("*.json"))
    if not latest:
        raise SystemExit(f"[abort] no decisions found in {decisions_dir}")
    payload = json.loads(latest[-1].read_text())
    date = payload.get("as_of") or payload.get("date") or latest[-1].stem
    actions = payload.get("actions", {})
    syms = set()
    for bucket in ("BUY", "SELL", "HOLD"):
        for a in actions.get(bucket, []):
            sym = a.get("symbol")
            if sym:
                syms.add(sym)
    return date, sorted(syms)


def compute_features(provider_uri: str, symbols: list[str], date: str) -> pd.DataFrame:
    """Run Alpha158 against the given universe for one date.
    Lookback is handled by Alpha158 itself (some features need 60 prior days),
    so we ask qlib for [date-90, date]."""
    import qlib
    from qlib.contrib.data.handler import Alpha158

    qlib.init(provider_uri=os.path.expanduser(provider_uri), region="cn")
    start = (pd.Timestamp(date) - pd.Timedelta(days=120)).strftime("%Y-%m-%d")
    handler = Alpha158(
        instruments=symbols,
        start_time=start,
        end_time=date,
        fit_start_time=start,
        fit_end_time=date,
    )
    df = handler.fetch(col_set="feature")
    if df.empty:
        raise SystemExit(f"[abort] Alpha158 returned no rows for {date}")
    # Keep only the target date — most users only want "as-of today"
    df = df.reset_index().rename(
        columns={"datetime": "date", "instrument": "symbol"}
    )
    df = df[df["date"] == pd.Timestamp(date)]
    if df.empty:
        # Fall back to the latest available date in case `date` isn't a session
        last = df.assign(_d=df["date"]).groupby("_d").size().sort_index().index[-1] \
               if not df.empty else None
        if last is None:
            raise SystemExit(f"[abort] no Alpha158 row matched {date}")
        df = df[df["date"] == last]
    return df


def export_booster_text(model_dir: Path, out_path: Path) -> None:
    """Unpickle the qlib LGBModel and dump just the lightgbm.Booster as text.
    This lets the analytics Lambda load the model with `lightgbm` alone, no
    qlib dependency. The text format is a stable, version-tolerant artefact.
    """
    import pickle
    with open(model_dir / "model.pkl", "rb") as f:
        wrapped = pickle.load(f)
    booster = getattr(wrapped, "model", wrapped)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    booster.save_model(str(out_path))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--provider_uri", default="data/qlib_data/in_data")
    p.add_argument("--decisions_dir", default="outputs/decisions")
    p.add_argument("--model_dir", default="outputs/nse_baseline_750_long")
    p.add_argument("--out", default="outputs/analytics/features_today.parquet")
    p.add_argument("--booster_out", default="outputs/analytics/model_booster.txt")
    args = p.parse_args()

    date, symbols = collect_universe(Path(args.decisions_dir))
    print(f"[features] computing Alpha158 for {len(symbols)} symbols on {date}")
    df = compute_features(args.provider_uri, symbols, date)
    print(f"[features] {len(df)} rows × {len(df.columns)-2} features")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False, compression="snappy")
    print(f"[features] wrote {out_path} ({out_path.stat().st_size / 1024:.1f} KB)")

    # Re-export the LightGBM booster in text format for the Lambda
    booster_path = Path(args.booster_out)
    export_booster_text(Path(args.model_dir), booster_path)
    print(f"[features] wrote {booster_path} ({booster_path.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
