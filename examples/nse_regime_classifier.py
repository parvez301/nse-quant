#!/usr/bin/env python3
"""Classify the current NIFTY 50 market regime.

Buckets the last 60 trading days into one of three regimes:

- "Trending"  — low realised vol AND meaningful drift (|60d return| ≥ 5%)
- "Volatile"  — high realised vol (annualised σ above the long-run 75th pct)
- "Choppy"    — low vol, no clear drift

Produces `outputs/regime.json` for the `/api/regime` endpoint. Read by the
v2 Today briefing to give context for "model historically weaker here"-type
caveats.

Run from repo root:
  ./.venv/bin/python examples/nse_regime_classifier.py
"""
from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd


WINDOW = 60          # trading days for "here" stats
TREND_HISTORY = 504  # 2y of trading days for "trend" benchmark
VOL_THRESHOLD = 0.20 # annualised σ above this → "Volatile"
TREND_THRESHOLD = 0.05  # 60d return |.| above this → "Trending" (when not volatile)


def fetch_nifty_closes(provider_uri: str) -> pd.DataFrame:
    """Pull NIFTY 50 daily closes from the local qlib store."""
    import qlib
    from qlib.data import D

    qlib.init(provider_uri=os.path.expanduser(provider_uri), region="cn")
    df = D.features(["NIFTY50"], ["$close"], freq="day")
    if df.empty:
        raise SystemExit("[regime] qlib returned no NIFTY50 data")
    df = df.reset_index()
    df.columns = ["instrument", "date", "close"]
    df = df.sort_values("date").reset_index(drop=True)
    return df


def annualised_vol(returns: pd.Series) -> float:
    return float(returns.std() * math.sqrt(252))


def annualised_sharpe(returns: pd.Series) -> float:
    sd = float(returns.std())
    if sd == 0 or math.isnan(sd):
        return 0.0
    return float((returns.mean() / sd) * math.sqrt(252))


def classify(closes: pd.DataFrame) -> dict:
    closes = closes.copy()
    closes["ret"] = closes["close"].pct_change()
    closes = closes.dropna(subset=["ret"])
    if len(closes) < WINDOW + 5:
        raise SystemExit(f"[regime] need ≥{WINDOW + 5} days of returns, have {len(closes)}")

    here = closes.tail(WINDOW)
    trend_window = closes.tail(TREND_HISTORY)

    vol_here = annualised_vol(here["ret"])
    sharpe_here = annualised_sharpe(here["ret"])
    sharpe_trend = annualised_sharpe(trend_window["ret"])

    first_close = float(here["close"].iloc[0])
    last_close = float(here["close"].iloc[-1])
    drift = (last_close - first_close) / first_close

    if vol_here >= VOL_THRESHOLD:
        label = "Volatile"
    elif abs(drift) >= TREND_THRESHOLD:
        label = "Trending"
    else:
        label = "Choppy"

    # how many trailing days have stayed in the same bucket — best-effort
    since_days = compute_regime_persistence(closes, label)

    return {
        "as_of": str(closes["date"].iloc[-1].date() if hasattr(closes["date"].iloc[-1], "date") else closes["date"].iloc[-1]),
        "label": label,
        "since_days": since_days,
        "sharpe_here": round(sharpe_here, 3),
        "sharpe_trend": round(sharpe_trend, 3),
        "vol_60d_ann_pct": round(vol_here * 100, 2),
        "drift_60d_pct": round(drift * 100, 2),
        "thresholds": {
            "vol_threshold_ann_pct": round(VOL_THRESHOLD * 100, 1),
            "trend_threshold_pct": round(TREND_THRESHOLD * 100, 1),
        },
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }


def compute_regime_persistence(closes: pd.DataFrame, current_label: str) -> int:
    """Walk backwards day-by-day, recomputing the label over a 60-day rolling
    window, and return how many days the label has matched the current one."""
    n = len(closes)
    streak = 0
    for end in range(n, WINDOW + 1, -1):
        win = closes.iloc[end - WINDOW:end]
        v = annualised_vol(win["ret"])
        first_c = float(win["close"].iloc[0])
        last_c = float(win["close"].iloc[-1])
        drift = (last_c - first_c) / first_c
        if v >= VOL_THRESHOLD:
            label = "Volatile"
        elif abs(drift) >= TREND_THRESHOLD:
            label = "Trending"
        else:
            label = "Choppy"
        if label == current_label:
            streak += 1
        else:
            break
    return streak


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--provider_uri", default="data/qlib_data/in_data")
    p.add_argument("--out", default="outputs/regime.json")
    args = p.parse_args()

    closes = fetch_nifty_closes(args.provider_uri)
    payload = classify(closes)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(payload, f, indent=2, default=str)

    print(f"[regime] {payload['label']} · vol={payload['vol_60d_ann_pct']}% · "
          f"drift={payload['drift_60d_pct']}% · since {payload['since_days']}d")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
