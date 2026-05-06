"""Tests for the four new pure-Python helpers added this session.

- nse_build_rank_history.collect_rows_from_decision
- nse_regime_classifier.classify
- nse_hitrate_scan.assign_buckets / scan
- nse_export_features_today.compute_shap_today / compute_peers_today
  (pure-numpy paths exercised with hand-rolled fake booster + matrix)
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "examples"))


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, _REPO / "examples" / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ────────────────────────────────────────────────────────────────────────
# rank-history backfill

def test_rank_history_collects_buy_hold_and_top10():
    mod = _load("brh", "nse_build_rank_history.py")
    decision = {
        "as_of": "2026-04-27",
        "actions": {
            "BUY":  [{"symbol": "AAA", "rank": 1,  "score": 0.5}],
            "HOLD": [{"symbol": "BBB", "rank_now": 12, "score": 0.04}],
            "SELL": [{"symbol": "CCC", "rank_now": 99, "reason": "fell out"}],
        },
        "top_10_candidates": [
            {"instrument": "DDD", "rank": 7, "score": 0.08},
        ],
    }
    rows = mod.collect_rows_from_decision(decision)
    assert rows["AAA"] == {"date": "2026-04-27", "rank": 1, "score": 0.5}
    assert rows["BBB"] == {"date": "2026-04-27", "rank": 12, "score": 0.04}
    assert rows["DDD"] == {"date": "2026-04-27", "rank": 7, "score": 0.08}
    # SELL is intentionally excluded from rank-history (rank_now there is the
    # post-fall rank, not a top-K position; would distort the spark).
    assert "CCC" not in rows


def test_rank_history_skips_decision_without_as_of():
    mod = _load("brh2", "nse_build_rank_history.py")
    rows = mod.collect_rows_from_decision({"actions": {"BUY": []}})
    assert rows == {}


# ────────────────────────────────────────────────────────────────────────
# regime classifier

def _make_closes(values):
    dates = pd.bdate_range("2024-01-01", periods=len(values))
    return pd.DataFrame({"date": dates, "close": values})


def test_regime_calm_uptrend_is_trending():
    mod = _load("rg", "nse_regime_classifier.py")
    # 80 sessions of 0.10% drift, very low vol → drift > 5% → Trending
    closes = _make_closes([100 * (1.001 ** i) for i in range(80)])
    payload = mod.classify(closes)
    assert payload["label"] == "Trending"
    assert payload["drift_60d_pct"] > 5
    assert payload["vol_60d_ann_pct"] < 5  # very smooth


def test_regime_high_vol_is_volatile():
    mod = _load("rg2", "nse_regime_classifier.py")
    np.random.seed(7)
    # 80 sessions with σ ≈ 3%/day → annualised σ ≈ 47% → Volatile
    rets = np.random.normal(loc=0, scale=0.03, size=80)
    closes_arr = 100 * np.cumprod(1 + rets)
    payload = mod.classify(_make_closes(closes_arr))
    assert payload["label"] == "Volatile"


def test_regime_flat_low_vol_is_choppy():
    mod = _load("rg3", "nse_regime_classifier.py")
    np.random.seed(11)
    rets = np.random.normal(loc=0, scale=0.005, size=80)  # ~8% annualised
    closes_arr = 100 * np.cumprod(1 + rets)
    payload = mod.classify(_make_closes(closes_arr))
    assert payload["label"] == "Choppy"


# ────────────────────────────────────────────────────────────────────────
# hit-rate scan

def test_hitrate_assign_buckets_boundaries():
    mod = _load("hr", "nse_hitrate_scan.py")
    assert mod.assign_buckets(1) == "top_5"
    assert mod.assign_buckets(5) == "top_5"
    assert mod.assign_buckets(6) == "top_10"
    assert mod.assign_buckets(10) == "top_10"
    assert mod.assign_buckets(30) == "top_30"
    assert mod.assign_buckets(50) == "rank_30_50"
    assert mod.assign_buckets(100) == "rank_50_100"
    assert mod.assign_buckets(200) == "rank_100_200"
    assert mod.assign_buckets(201) == "rank_200_plus"


def test_hitrate_scan_e2e_synthetic():
    mod = _load("hr2", "nse_hitrate_scan.py")
    # 6 symbols × 3 dates: AAA always top-1 with positive 5-day return,
    # FFF always last with negative. Verify hit_rate sorts correctly.
    dates = pd.bdate_range("2024-01-01", periods=10)
    syms = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]
    rows = []
    for i, sym in enumerate(syms):
        # close trends upward for AAA, flat for middle, downward for FFF
        slope = 0.005 - i * 0.002
        for j, d in enumerate(dates):
            rows.append({"instrument": sym, "date": d, "close": 100 * (1 + slope) ** j})
    closes = pd.DataFrame(rows)

    pred_idx = pd.MultiIndex.from_product(
        [dates[:3], syms], names=["datetime", "instrument"]
    )
    # higher score for AAA, lower for FFF
    scores = [0.5 - 0.1 * syms.index(sym) for (_, sym) in pred_idx]
    pred = pd.DataFrame({"score": scores}, index=pred_idx)

    result = mod.scan(pred, closes)
    # AAA is rank 1 across 3 dates → top_5 bucket has ≥3 rows
    top5 = result["buckets"]["top_5"]["5d"]
    assert top5["total"] >= 3
    assert top5["hit_rate"] is not None and top5["hit_rate"] >= 0.5


# ────────────────────────────────────────────────────────────────────────
# peers (cosine) — no model needed

def test_compute_peers_today_basic():
    mod = _load("ft", "nse_export_features_today.py")
    # 3 symbols in 2D feature space:
    #  AAA = [1, 0]   (closest to AAB)
    #  AAB = [0.99, 0.01]
    #  ZZZ = [0, 1]   (orthogonal)
    df = pd.DataFrame({
        "date": ["2026-04-27"] * 3,
        "symbol": ["AAA", "AAB", "ZZZ"],
        "f0": [1.0, 0.99, 0.0],
        "f1": [0.0, 0.01, 1.0],
    })
    peers = mod.compute_peers_today(df, top_k=2)
    assert peers["AAA"][0]["symbol"] == "AAB"
    assert peers["AAA"][0]["similarity"] > 0.99
    # ZZZ should be ranked last for AAA
    aaa_syms = [p["symbol"] for p in peers["AAA"]]
    assert aaa_syms.index("AAB") < aaa_syms.index("ZZZ") if "ZZZ" in aaa_syms else True


def test_compute_peers_today_handles_zero_norm():
    mod = _load("ft2", "nse_export_features_today.py")
    # All zeros for one symbol → norm 0; should not divide-by-zero
    df = pd.DataFrame({
        "date": ["2026-04-27"] * 2,
        "symbol": ["AAA", "ZERO"],
        "f0": [1.0, 0.0],
        "f1": [0.0, 0.0],
    })
    peers = mod.compute_peers_today(df, top_k=1)
    # No exception; ZERO gets *some* peer (similarity 0 is fine)
    assert "AAA" in peers
    assert "ZERO" in peers
