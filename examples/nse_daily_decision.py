#!/usr/bin/env python3
"""Stage 6: daily decision runner.

Loads the trained baseline model + latest Qlib data, scores today's NIFTY universe,
and writes a JSON trade list:  BUY top-K, SELL anything currently held that fell
out of the top-K_plus_buffer.

Usage (cron-friendly — runs in <10 seconds):
  python examples/nse_daily_decision.py
  python examples/nse_daily_decision.py --topk 20 --holdings_csv /path/to/current_portfolio.csv

Intended as the prediction-side of a paper-trading loop:
  1. Cron fires this at 08:30 IST (markets open 09:15).
  2. Human reviews outputs/decisions/YYYY-MM-DD.json.
  3. Trades placed manually through broker UI (no auto-execution for first 6 months).
  4. Fills logged in current_portfolio.csv.
  5. Loop.

A current_portfolio.csv format (loose; you edit it by hand during paper trading):
  symbol,shares,avg_price,bought_on
  RELIANCE,10,1280.50,2026-04-15
  TCS,3,3900.00,2026-04-18
"""
import argparse
import json
import os
import pickle
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd


def load_latest_model(model_dir: Path):
    model_path = model_dir / "model.pkl"
    if not model_path.exists():
        sys.exit(f"[abort] no model at {model_path} — run nse_baseline.py first")
    with open(model_path, "rb") as f:
        return pickle.load(f)


def score_today(
    model,
    qlib_provider: str,
    target_date: str | None,
    lookback_days: int = 400,
) -> pd.DataFrame:
    """Generate per-stock scores for the most recent available trading day.

    Returns: DataFrame indexed by instrument with columns [score, close, volume].
    """
    import qlib
    from qlib.data import D
    from qlib.contrib.data.handler import Alpha158
    from qlib.data.dataset import DatasetH

    qlib.init(provider_uri=os.path.expanduser(qlib_provider), region="cn")

    # Figure out the most recent date with data (fall back from target_date)
    instruments = D.instruments(market="all")
    cal = D.calendar(start_time="2024-01-01")
    if target_date is None:
        target_date = cal[-1].strftime("%Y-%m-%d")

    # Build a handler that only processes the small tail we need
    handler_start = (pd.Timestamp(target_date) - pd.Timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    handler = Alpha158(
        instruments=instruments,
        start_time=handler_start,
        end_time=target_date,
        fit_start_time=handler_start,
        fit_end_time=target_date,
        label=["Ref($close, -5) / $close - 1"],  # label is meaningless on latest day, but handler wants one
    )

    dataset = DatasetH(
        handler=handler,
        segments={"infer": (handler_start, target_date)},
    )
    pred = model.predict(dataset, segment="infer")
    if isinstance(pred, pd.Series):
        pred = pred.to_frame("score")
    else:
        pred.columns = ["score"]

    # Take only the last available date per instrument
    latest_date = pred.index.get_level_values("datetime").max()
    today_scores = pred.xs(latest_date, level="datetime")

    # Enrich with current close + rolling 20-day avg turnover (robust liquidity filter)
    window_start = (latest_date - pd.Timedelta(days=45)).strftime("%Y-%m-%d")
    enrich = D.features(
        today_scores.index.tolist(),
        ["$close", "$volume"],
        start_time=window_start,
        end_time=str(latest_date.date()),
    )
    enrich = enrich.rename(columns=lambda c: c.lstrip("$"))
    enrich["turnover"] = enrich["close"] * enrich["volume"]

    avg_turnover = (
        enrich.groupby(level="instrument")["turnover"]
        .apply(lambda s: s.dropna().tail(20).mean())
    )
    latest_close = (
        enrich.groupby(level="instrument")["close"]
        .apply(lambda s: s.dropna().iloc[-1] if s.dropna().size else float("nan"))
    )
    latest_volume = (
        enrich.groupby(level="instrument")["volume"]
        .apply(lambda s: s.dropna().iloc[-1] if s.dropna().size else float("nan"))
    )

    close_vol = pd.DataFrame({
        "close": latest_close,
        "volume": latest_volume,
        "avg_turnover_20d": avg_turnover,
    })

    out = today_scores.join(close_vol, how="left")
    out.attrs["as_of"] = str(latest_date.date())
    return out


def load_current_portfolio(path: Path | None) -> pd.DataFrame:
    if path is None or not path.exists():
        return pd.DataFrame(columns=["symbol", "shares", "avg_price", "bought_on"])
    df = pd.read_csv(path)
    df["symbol"] = df["symbol"].str.upper().str.strip()
    return df


def load_prev_rank_map(out_dir: Path, as_of: str) -> dict:
    """Build {symbol: {rank, score}} from the most recent prior decision JSON.

    Looks for any decision JSON dated strictly before `as_of`. Returns empty
    dict if none exists (first-run case). Reads BUY + HOLD + top_10_candidates
    so the merge has rank coverage for any name that's relevant today.
    """
    if not out_dir.is_dir():
        return {}
    candidates = sorted(
        p for p in out_dir.glob("*.json") if p.stem < as_of
    )
    if not candidates:
        return {}
    try:
        with open(candidates[-1]) as f:
            prev = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict = {}
    acts = prev.get("actions") or {}
    for kind in ("BUY", "HOLD"):
        for item in acts.get(kind) or []:
            sym = item.get("symbol")
            if not sym:
                continue
            rank = item.get("rank") if "rank" in item else item.get("rank_now")
            out[sym] = {"rank": rank, "score": item.get("score")}
    for r in prev.get("top_10_candidates") or []:
        sym = r.get("instrument") or r.get("symbol")
        if sym and sym not in out:
            out[sym] = {"rank": r.get("rank"), "score": r.get("score")}
    return out


def build_decision(
    scored: pd.DataFrame,
    portfolio: pd.DataFrame,
    topk: int,
    buffer: int,
    min_liquidity: float,
    as_of: str,
    prev_map: dict | None = None,
) -> dict:
    """Translate a score table into a concrete trade list.

    - BUY: top-`topk` scores not currently in portfolio
    - HOLD: anything in current portfolio that's still in top-`topk + buffer`
    - SELL: anything in current portfolio that fell out of top-`topk + buffer`
    """
    # Liquidity filter using 20-day average turnover (robust to single-day data gaps)
    scored = scored.copy()
    # Fallback to spot turnover if rolling avg is missing
    if "avg_turnover_20d" not in scored.columns:
        scored["avg_turnover_20d"] = scored["close"] * scored["volume"]
    scored["turnover_proxy"] = scored["avg_turnover_20d"].fillna(
        scored["close"] * scored["volume"]
    )
    liquid = scored[scored["turnover_proxy"] >= min_liquidity].sort_values("score", ascending=False)

    ranked = liquid.reset_index()
    ranked["rank"] = range(1, len(ranked) + 1)

    top_buy = set(ranked.head(topk)["instrument"])
    top_hold = set(ranked.head(topk + buffer)["instrument"])
    held = set(portfolio["symbol"]) if len(portfolio) else set()

    buys = sorted(top_buy - held)
    sells = sorted(held - top_hold)
    holds = sorted(held & top_hold)

    def rank_of(sym):
        row = ranked[ranked["instrument"] == sym]
        return int(row["rank"].iloc[0]) if len(row) else None

    def score_of(sym):
        row = ranked[ranked["instrument"] == sym]
        return float(row["score"].iloc[0]) if len(row) else None

    pm = prev_map or {}

    def with_prev(item: dict) -> dict:
        sym = item.get("symbol")
        prev = pm.get(sym) or {}
        item["rank_prev"] = prev.get("rank")
        item["score_prev"] = prev.get("score")
        return item

    return {
        "as_of": as_of,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "universe_size": int(len(scored)),
        "liquid_universe_size": int(len(liquid)),
        "topk": topk,
        "hold_buffer": buffer,
        "actions": {
            "BUY": [with_prev({"symbol": s, "rank": rank_of(s), "score": score_of(s)}) for s in buys],
            "SELL": [
                with_prev({
                    "symbol": s,
                    "rank_now": rank_of(s),
                    "reason": "fell out of top-{}".format(topk + buffer),
                })
                for s in sells
            ],
            "HOLD": [with_prev({"symbol": s, "rank_now": rank_of(s), "score": score_of(s)}) for s in holds],
        },
        "top_10_candidates": ranked.head(10)[["instrument", "rank", "score", "close", "turnover_proxy"]].to_dict(orient="records"),
    }


def format_human_readable(decision: dict) -> str:
    lines = []
    lines.append("=" * 60)
    lines.append(f"  NSE DAILY DECISION  —  as of {decision['as_of']}")
    lines.append(f"  Generated: {decision['generated_at']}")
    lines.append(f"  Universe: {decision['liquid_universe_size']} liquid / {decision['universe_size']} total")
    lines.append(f"  Strategy: top-{decision['topk']} long, hold buffer {decision['hold_buffer']}")
    lines.append("=" * 60)

    acts = decision["actions"]
    if acts["BUY"]:
        lines.append(f"\n BUY ({len(acts['BUY'])})")
        for a in acts["BUY"]:
            lines.append(f"   rank#{a['rank']:<3d} {a['symbol']:<14s}  score {a['score']:+.4f}")
    else:
        lines.append("\n BUY: none")

    if acts["SELL"]:
        lines.append(f"\n SELL ({len(acts['SELL'])})")
        for a in acts["SELL"]:
            rank = a["rank_now"] if a["rank_now"] is not None else "OUT"
            lines.append(f"   {a['symbol']:<14s}  rank now {rank}  [{a['reason']}]")
    else:
        lines.append("\n SELL: none")

    if acts["HOLD"]:
        lines.append(f"\n HOLD ({len(acts['HOLD'])})")
        for a in acts["HOLD"]:
            lines.append(f"   rank#{a['rank_now']:<3d} {a['symbol']:<14s}  score {a['score']:+.4f}")

    lines.append("\n--- top-10 candidates overall ---")
    for r in decision["top_10_candidates"]:
        lines.append(
            f"   #{r['rank']:<3d} {r['instrument']:<14s} score {r['score']:+.4f}  "
            f"close {r['close']:>8.2f}  turnover ₹{r['turnover_proxy']/1e7:.2f} Cr"
        )

    lines.append("\n" + "=" * 60)
    lines.append(" REMINDER: paper-trade this for 3 months before real money.")
    lines.append("=" * 60)
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(
        description="Emit today's NSE BUY/HOLD/SELL decision list",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--model_dir", default="outputs/nse_baseline")
    p.add_argument("--qlib_provider", default="data/qlib_data/in_data")
    p.add_argument("--target_date", default=None,
                   help="YYYY-MM-DD (default: latest available in data)")
    p.add_argument("--topk", type=int, default=20)
    p.add_argument("--buffer", type=int, default=10,
                   help="keep holding names that are still in top-(topk+buffer)")
    p.add_argument("--min_liquidity", type=float, default=5e7,
                   help="min ₹ daily turnover (price*volume) to be eligible; default 5 crore")
    p.add_argument("--holdings_csv", default="outputs/current_portfolio.csv",
                   help="CSV of current holdings (columns: symbol,shares,avg_price,bought_on)")
    p.add_argument("--out_dir", default="outputs/decisions")
    args = p.parse_args()

    model_dir = Path(args.model_dir)
    model = load_latest_model(model_dir)

    print(f"[score] running model {model_dir}/model.pkl against latest Qlib data...")
    scored = score_today(model, args.qlib_provider, args.target_date)
    as_of = scored.attrs["as_of"]
    print(f"[score] {len(scored)} stocks scored, as of {as_of}")

    portfolio = load_current_portfolio(Path(args.holdings_csv))
    print(f"[portfolio] {len(portfolio)} currently held")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    prev_map = load_prev_rank_map(out_dir, as_of)
    if prev_map:
        print(f"[prev] loaded {len(prev_map)} prior ranks for diff")

    decision = build_decision(
        scored=scored,
        portfolio=portfolio,
        topk=args.topk,
        buffer=args.buffer,
        min_liquidity=args.min_liquidity,
        as_of=as_of,
        prev_map=prev_map,
    )
    out_json = out_dir / f"{as_of}.json"
    out_txt = out_dir / f"{as_of}.txt"
    with open(out_json, "w") as f:
        json.dump(decision, f, indent=2, default=str)
    human = format_human_readable(decision)
    with open(out_txt, "w") as f:
        f.write(human)

    print(human)
    print(f"\n[saved] {out_json}")
    print(f"[saved] {out_txt}")


if __name__ == "__main__":
    main()
