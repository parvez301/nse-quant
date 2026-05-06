#!/usr/bin/env python3
"""One-shot scan: per-rank-bucket forward-return hit-rates from the
trained model's test-period predictions.

Loads `outputs/nse_baseline_750_long/pred.pkl` (multi-index date×symbol
score), computes daily ranks, joins forward returns from the qlib store,
and bins by rank bucket. Output is the per-bucket scoreboard rendered
in the Today briefing and Lab tab.

Run from repo root once (rerun whenever the model retrains):
  ./.venv/bin/python examples/nse_hitrate_scan.py
"""
from __future__ import annotations

import argparse
import json
import os
import pickle
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd


HORIZONS = {"5d": 5, "10d": 10, "20d": 20}

BUCKETS = [
    ("top_5",     1, 5),
    ("top_10",    1, 10),
    ("top_30",    1, 30),
    ("rank_30_50", 31, 50),
    ("rank_50_100", 51, 100),
    ("rank_100_200", 101, 200),
    ("rank_200_plus", 201, 99999),
]


def load_predictions(pred_path: Path) -> pd.DataFrame:
    with open(pred_path, "rb") as f:
        pred = pickle.load(f)
    if "score" not in pred.columns:
        raise SystemExit(f"[abort] pred.pkl has no 'score' column: {pred.columns.tolist()}")
    return pred


def load_closes(provider_uri: str, instruments: list[str], start: str, end: str) -> pd.DataFrame:
    import qlib
    from qlib.data import D
    qlib.init(provider_uri=os.path.expanduser(provider_uri), region="cn")
    df = D.features(instruments, ["$close"], start_time=start, end_time=end)
    if df.empty:
        raise SystemExit("[abort] qlib returned empty closes")
    df = df.reset_index()
    df.columns = ["instrument", "date", "close"]
    return df.sort_values(["instrument", "date"])


def compute_forward_returns(closes: pd.DataFrame, horizon: int) -> pd.DataFrame:
    closes = closes.copy()
    closes["fwd"] = closes.groupby("instrument")["close"].shift(-horizon) / closes["close"] - 1.0
    return closes[["instrument", "date", "fwd"]].dropna()


def assign_buckets(rank: int) -> str | None:
    for name, lo, hi in BUCKETS:
        if lo <= rank <= hi:
            return name
    return None


def scan(pred: pd.DataFrame, closes: pd.DataFrame) -> dict:
    pred = pred.reset_index()
    pred = pred.rename(columns={"datetime": "date"})
    pred["rank"] = pred.groupby("date")["score"].rank(method="first", ascending=False).astype(int)
    pred["bucket"] = pred["rank"].map(assign_buckets)
    pred = pred.dropna(subset=["bucket"])

    # Pre-compute the universe-average forward return per (date, horizon)
    # for the "vs universe" delta.
    universe_means: dict = {}
    for label, h in HORIZONS.items():
        fwd = compute_forward_returns(closes, h)
        merged = pred.merge(fwd, on=["date", "instrument"], how="inner")
        univ = merged.groupby("date")["fwd"].mean().rename("univ_fwd").reset_index()
        merged = merged.merge(univ, on="date", how="left")
        universe_means[label] = merged

    out: dict = {"buckets": {}, "horizons": list(HORIZONS.keys()), "n_decisions": int(pred.shape[0])}
    for name, _lo, _hi in BUCKETS:
        out["buckets"][name] = {}
        for label in HORIZONS.keys():
            df = universe_means[label]
            sub = df[df["bucket"] == name]
            if sub.empty:
                out["buckets"][name][label] = {"hits": 0, "total": 0, "hit_rate": None,
                                                "mean_fwd": None, "vs_universe": None}
                continue
            total = int(sub.shape[0])
            hits = int((sub["fwd"] > 0).sum())
            mean_fwd = float(sub["fwd"].mean())
            vs_univ = float((sub["fwd"] - sub["univ_fwd"]).mean())
            out["buckets"][name][label] = {
                "hits": hits,
                "total": total,
                "hit_rate": round(hits / total, 4),
                "mean_fwd": round(mean_fwd, 6),
                "vs_universe": round(vs_univ, 6),
            }
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pred_pkl", default="outputs/nse_baseline_750_long/pred.pkl")
    p.add_argument("--provider_uri", default="data/qlib_data/in_data")
    p.add_argument("--out", default="outputs/hit_rates.json")
    args = p.parse_args()

    pred = load_predictions(Path(args.pred_pkl))
    print(f"[hitrate] loaded {pred.shape[0]} predictions")

    instruments = sorted(pred.index.get_level_values("instrument").unique().tolist())
    dates = pred.index.get_level_values("datetime")
    start = dates.min().strftime("%Y-%m-%d")
    end = (dates.max() + pd.Timedelta(days=40)).strftime("%Y-%m-%d")
    print(f"[hitrate] fetching closes for {len(instruments)} symbols, {start}→{end}")
    closes = load_closes(args.provider_uri, instruments, start, end)
    print(f"[hitrate] {closes.shape[0]} close rows")

    payload = scan(pred, closes)
    payload["generated_at"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(payload, f, indent=2, default=str)

    print(f"[hitrate] wrote {out}")
    for name in [b[0] for b in BUCKETS]:
        cells = payload["buckets"][name]
        print(f"  {name:<14s}", end="")
        for h in HORIZONS:
            c = cells[h]
            if c["total"] == 0:
                print(f"  {h}: empty", end="")
            else:
                print(f"  {h}: {c['hits']:>4d}/{c['total']:<5d} ({c['hit_rate']*100:.0f}%) vs+{c['vs_universe']*100:+.2f}pp", end="")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
