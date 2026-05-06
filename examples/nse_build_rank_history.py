#!/usr/bin/env python3
"""Backfill per-symbol rank history from existing decision JSONs.

Scans `outputs/decisions/*.json` and emits one file per symbol at
`outputs/rank_history/<SYMBOL>.json` containing a date-sorted list of
`{date, rank, score}` rows pulled from each decision's BUY/HOLD lists
plus its top-10 candidate panel.

Run once to backfill, then re-run after each cron to extend (it does a
full rebuild — small enough at ~30 KB per symbol that incremental is
not worth the complexity).
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def collect_rows_from_decision(decision: dict) -> dict:
    as_of = decision.get("as_of")
    if not as_of:
        return {}
    out: dict = {}
    acts = decision.get("actions") or {}
    for kind in ("BUY", "HOLD"):
        for item in acts.get(kind) or []:
            sym = item.get("symbol")
            if not sym:
                continue
            rank = item.get("rank") if "rank" in item else item.get("rank_now")
            out[sym] = {"date": as_of, "rank": rank, "score": item.get("score")}
    for r in decision.get("top_10_candidates") or []:
        sym = r.get("instrument") or r.get("symbol")
        if sym and sym not in out:
            out[sym] = {"date": as_of, "rank": r.get("rank"), "score": r.get("score")}
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--decisions_dir", default="outputs/decisions")
    p.add_argument("--out_dir", default="outputs/rank_history")
    args = p.parse_args()

    decisions_dir = Path(args.decisions_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(decisions_dir.glob("*.json"))
    if not files:
        print(f"[abort] no decision JSONs in {decisions_dir}")
        return 1

    series: dict[str, list[dict]] = defaultdict(list)
    for f in files:
        try:
            with open(f) as fh:
                decision = json.load(fh)
        except (OSError, json.JSONDecodeError) as e:
            print(f"[skip] {f.name}: {e}")
            continue
        for sym, row in collect_rows_from_decision(decision).items():
            series[sym].append(row)

    written = 0
    for sym, rows in series.items():
        rows.sort(key=lambda r: r["date"])
        target = out_dir / f"{sym}.json"
        with open(target, "w") as fh:
            json.dump(rows, fh, default=str)
        written += 1

    print(f"[done] wrote {written} symbols × up to {len(files)} dates → {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
