"""Tests for the rank-diff merge in nse_daily_decision.

Focus: load_prev_rank_map walks decision JSONs correctly and build_decision
attaches `rank_prev`/`score_prev` to each action item.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd
import pytest


_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "examples"))


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "nse_daily_decision_mod", _REPO / "examples" / "nse_daily_decision.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_decision(dirpath: Path, name: str, payload: dict) -> None:
    dirpath.mkdir(parents=True, exist_ok=True)
    (dirpath / f"{name}.json").write_text(json.dumps(payload))


def test_load_prev_rank_map_picks_latest_strictly_before(tmp_path: Path):
    mod = _load_module()
    _write_decision(tmp_path, "2026-04-25", {
        "as_of": "2026-04-25",
        "actions": {
            "BUY":  [{"symbol": "AAA", "rank": 5,  "score": 0.10}],
            "HOLD": [{"symbol": "BBB", "rank_now": 12, "score": 0.04}],
            "SELL": [],
        },
        "top_10_candidates": [
            {"instrument": "CCC", "rank": 7, "score": 0.08},
        ],
    })
    _write_decision(tmp_path, "2026-04-26", {
        "as_of": "2026-04-26",
        "actions": {"BUY": [{"symbol": "ZZZ", "rank": 1, "score": 0.5}], "HOLD": [], "SELL": []},
        "top_10_candidates": [],
    })

    pm = mod.load_prev_rank_map(tmp_path, "2026-04-26")
    assert pm == {"AAA": {"rank": 5, "score": 0.10},
                  "BBB": {"rank": 12, "score": 0.04},
                  "CCC": {"rank": 7, "score": 0.08}}


def test_load_prev_rank_map_returns_empty_when_no_history(tmp_path: Path):
    mod = _load_module()
    assert mod.load_prev_rank_map(tmp_path, "2026-04-26") == {}


def test_load_prev_rank_map_skips_today_and_future(tmp_path: Path):
    mod = _load_module()
    _write_decision(tmp_path, "2026-04-26", {
        "as_of": "2026-04-26",
        "actions": {"BUY": [{"symbol": "TODAY", "rank": 1, "score": 0.5}], "HOLD": [], "SELL": []},
    })
    _write_decision(tmp_path, "2026-04-27", {
        "as_of": "2026-04-27",
        "actions": {"BUY": [{"symbol": "FUTURE", "rank": 1, "score": 0.5}], "HOLD": [], "SELL": []},
    })
    assert mod.load_prev_rank_map(tmp_path, "2026-04-26") == {}


def test_load_prev_rank_map_tolerates_corrupt_json(tmp_path: Path):
    mod = _load_module()
    (tmp_path / "2026-04-25.json").write_text("{ corrupt }")
    assert mod.load_prev_rank_map(tmp_path, "2026-04-26") == {}


def test_build_decision_attaches_prev_rank(monkeypatch):
    mod = _load_module()
    scored = pd.DataFrame({
        "instrument": ["AAA", "BBB", "CCC"],
        "score": [0.5, 0.3, 0.1],
        "close": [100.0, 200.0, 300.0],
        "volume": [1_000_000, 2_000_000, 3_000_000],
    })
    portfolio = pd.DataFrame({"symbol": ["BBB"]})
    prev_map = {
        "AAA": {"rank": 8, "score": 0.20},
        "BBB": {"rank": 2, "score": 0.45},
    }
    decision = mod.build_decision(
        scored=scored, portfolio=portfolio,
        topk=2, buffer=1, min_liquidity=0.0, as_of="2026-04-27",
        prev_map=prev_map,
    )
    buys = {b["symbol"]: b for b in decision["actions"]["BUY"]}
    holds = {h["symbol"]: h for h in decision["actions"]["HOLD"]}
    assert buys["AAA"]["rank_prev"] == 8
    assert buys["AAA"]["score_prev"] == 0.20
    assert holds["BBB"]["rank_prev"] == 2
    assert holds["BBB"]["score_prev"] == 0.45


def test_build_decision_handles_missing_prev_map(monkeypatch):
    mod = _load_module()
    scored = pd.DataFrame({
        "instrument": ["AAA"], "score": [0.5],
        "close": [100.0], "volume": [1_000_000],
    })
    decision = mod.build_decision(
        scored=scored, portfolio=pd.DataFrame({"symbol": []}),
        topk=1, buffer=1, min_liquidity=0.0, as_of="2026-04-27",
        prev_map=None,
    )
    aaa = decision["actions"]["BUY"][0]
    assert aaa["rank_prev"] is None
    assert aaa["score_prev"] is None
