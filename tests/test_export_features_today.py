"""Tests for the today-only features ETL.

The Alpha158 compute is integration-level (needs qlib data); we exercise the
universe-collection logic in unit tests.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "examples"))

import nse_export_features_today as mod


def _write_decision(dirpath: Path, name: str, payload: dict):
    dirpath.mkdir(parents=True, exist_ok=True)
    (dirpath / f"{name}.json").write_text(json.dumps(payload))


def test_collect_universe_picks_latest_decision(tmp_path: Path):
    _write_decision(tmp_path, "2026-04-23", {
        "as_of": "2026-04-23",
        "actions": {"BUY": [{"symbol": "OLD"}], "SELL": [], "HOLD": []},
    })
    _write_decision(tmp_path, "2026-04-24", {
        "as_of": "2026-04-24",
        "actions": {
            "BUY":  [{"symbol": "AAA"}, {"symbol": "BBB"}],
            "SELL": [{"symbol": "CCC"}],
            "HOLD": [{"symbol": "DDD"}],
        },
    })
    date, syms = mod.collect_universe(tmp_path)
    assert date == "2026-04-24"
    assert syms == ["AAA", "BBB", "CCC", "DDD"]
    assert "OLD" not in syms  # superseded


def test_collect_universe_aborts_when_empty(tmp_path: Path):
    import pytest
    with pytest.raises(SystemExit):
        mod.collect_universe(tmp_path)


def test_collect_universe_dedupes_across_buckets(tmp_path: Path):
    """A symbol can be in HOLD AND match the BUY logic on the same day in
    edge cases — make sure the universe is a set, not a list with dupes."""
    _write_decision(tmp_path, "2026-04-24", {
        "as_of": "2026-04-24",
        "actions": {
            "BUY":  [{"symbol": "AAA"}],
            "HOLD": [{"symbol": "AAA"}],  # duplicated
            "SELL": [],
        },
    })
    _, syms = mod.collect_universe(tmp_path)
    assert syms == ["AAA"]
