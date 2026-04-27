#!/usr/bin/env python3
"""Live information-coefficient snapshot — Tier 3 of the Kite read-only stack.

The existing nse_ic_monitor.py computes IC for past decisions that have a
fully-observable forward window (needs H trading days to elapse). This
script is the T+0 complement: at any time during or after market hours,
quote every pick in the latest decision, compute return-since-decision-
close using Kite's last_price, and report cross-sectional IC of
(model score, intraday/T+0 return).

Outputs append-only to outputs/live_ic.csv:
    captured_at, decision_as_of, n_symbols, pearson_ic, rank_ic,
    mean_return_bps, model_picks_pct_positive

Use it daily after market close to spot signal decay early — much earlier
than the H-day backward-looking monitor.

Exit codes mirror the rest of the Kite tools:
    0   snapshot taken (or skipped because no token / no decision)
    2   token rejected by Kite
    1   unexpected error
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Pure helpers — testable, no I/O
# ---------------------------------------------------------------------------

def compute_live_returns(
    scores: dict[str, float],
    ref_closes: dict[str, float],
    kite_last: dict[str, float],
) -> list[dict]:
    """Join score / ref_close / kite_last on symbol; drop incomplete or
    invalid rows. Returns one dict per usable symbol with the return.
    """
    out = []
    for sym, score in scores.items():
        ref = ref_closes.get(sym)
        last = kite_last.get(sym)
        if ref is None or last is None:
            continue
        try:
            ref_f = float(ref)
            last_f = float(last)
        except (TypeError, ValueError):
            continue
        if ref_f <= 0 or last_f <= 0:
            continue
        out.append({
            "symbol": sym,
            "score": float(score),
            "ref_close": ref_f,
            "kite_last": last_f,
            "ret": last_f / ref_f - 1.0,
        })
    return out


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3 or len(ys) != n:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    # Tolerance handles "effectively constant" inputs where float demeaning
    # leaves a residual variance ~ 1e-32 instead of exactly 0.
    if var_x < 1e-12 or var_y < 1e-12:
        return None
    return cov / math.sqrt(var_x * var_y)


def _ranks(values: list[float]) -> list[float]:
    """Average-rank ranking (handles ties)."""
    indexed = sorted(enumerate(values), key=lambda p: p[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i
        while j + 1 < len(indexed) and indexed[j + 1][1] == indexed[i][1]:
            j += 1
        avg = (i + j) / 2.0 + 1  # 1-indexed average
        for k in range(i, j + 1):
            ranks[indexed[k][0]] = avg
        i = j + 1
    return ranks


def compute_live_ic(rows: list[dict]) -> dict:
    """Pearson + Spearman of (score, return), plus a few quality stats.
    Returns None values when there's too little data or no variance."""
    n = len(rows)
    if n < 3:
        return {
            "n": n, "pearson_ic": None, "rank_ic": None,
            "mean_return_bps": None, "pct_positive": None,
        }
    scores = [r["score"] for r in rows]
    rets = [r["ret"] for r in rows]
    pearson = _pearson(scores, rets)
    rank_ic = _pearson(_ranks(scores), _ranks(rets))
    return {
        "n": n,
        "pearson_ic": round(pearson, 6) if pearson is not None else None,
        "rank_ic": round(rank_ic, 6) if rank_ic is not None else None,
        "mean_return_bps": round(sum(rets) / n * 1e4, 2),
        "pct_positive": round(sum(1 for r in rets if r > 0) / n, 4),
    }


def picks_from_decision(decision: dict) -> dict[str, float]:
    """Extract {symbol: score} for both BUY-side picks and the broader
    candidate list (top_K_candidates) if present."""
    by_sym: dict[str, float] = {}
    for action_key in ("BUY", "SELL", "HOLD"):
        for pick in decision.get("actions", {}).get(action_key, []) or []:
            sym = pick.get("symbol")
            score = pick.get("score")
            if sym is None or score is None:
                continue
            by_sym[sym] = float(score)
    # Some decision files also carry a 'top_10_candidates' or
    # 'top_k_candidates' list with a fuller ranked universe.
    for fallback_key in ("top_10_candidates", "top_k_candidates", "candidates"):
        for pick in decision.get(fallback_key, []) or []:
            sym = pick.get("instrument") or pick.get("symbol")
            score = pick.get("score")
            if sym is None or score is None:
                continue
            by_sym.setdefault(sym, float(score))
    return by_sym


# ---------------------------------------------------------------------------
# I/O glue
# ---------------------------------------------------------------------------

def _load_creds(secret_name: str) -> dict:
    try:
        import boto3
        sm = boto3.client("secretsmanager")
        raw = sm.get_secret_value(SecretId=secret_name)["SecretString"]
        return json.loads(raw)
    except Exception:
        return {}


def _latest_decision(decisions_dir: Path) -> Path | None:
    cands = sorted(decisions_dir.glob("*.json"))
    return cands[-1] if cands else None


def _ref_closes_via_qlib(symbols: list[str], as_of: str, qlib_provider: str) -> dict[str, float]:
    """Look up close price per symbol on `as_of` using qlib. Imported
    lazily so the script can be unit-tested without qlib installed."""
    if not symbols:
        return {}
    import qlib
    from qlib.data import D
    qlib.init(provider_uri=os.path.expanduser(qlib_provider), region="cn")
    df = D.features(list(symbols), ["$close"], start_time=as_of, end_time=as_of)
    if df.empty:
        return {}
    s = df["$close"]
    if "datetime" in s.index.names:
        s = s.droplevel("datetime")
    return {sym: float(px) for sym, px in s.items() if px == px}  # drop NaN


def fetch_kite_last_prices(kite, kite_keys: list[str]) -> dict[str, float]:
    """Strip 'NSE:' prefix off the keys when returning so the caller's
    score-side dict (which is unprefixed) lines up."""
    if not kite_keys:
        return {}
    quotes = kite.quote(kite_keys)
    out = {}
    for key, q in quotes.items():
        sym = key.split(":", 1)[1] if ":" in key else key
        last = (q or {}).get("last_price")
        if last is None:
            continue
        try:
            out[sym] = float(last)
        except (TypeError, ValueError):
            continue
    return out


def append_csv_row(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_existed = path.exists()
    with path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        if not file_existed:
            writer.writeheader()
        writer.writerow(row)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--decisions-dir", default="outputs/decisions")
    p.add_argument("--output", default="outputs/live_ic.csv")
    p.add_argument("--qlib-provider", default="data/qlib_data/in_data")
    p.add_argument("--secret", default="nse-quant/kite")
    p.add_argument(
        "--skip-if-missing", action="store_true",
        help="exit 0 if no token / SDK / decision is configured (cron-friendly)",
    )
    args = p.parse_args()

    decision_path = _latest_decision(Path(args.decisions_dir))
    if decision_path is None:
        if args.skip_if_missing:
            print("[live-ic] no decision file yet — skipping")
            return
        sys.exit(f"[live-ic] no decisions found in {args.decisions_dir}")

    decision = json.loads(decision_path.read_text())
    scores = picks_from_decision(decision)
    if not scores:
        print("[live-ic] decision has no scored picks — nothing to monitor")
        return

    creds = _load_creds(args.secret)
    api_key = creds.get("api_key")
    access_token = creds.get("access_token")
    if not api_key or not access_token:
        if args.skip_if_missing:
            print("[live-ic] no Kite token configured — skipping")
            return
        sys.exit("[live-ic] kite credentials missing — log in via /kite-login first")

    try:
        from kiteconnect import KiteConnect
    except ImportError:
        if args.skip_if_missing:
            print("[live-ic] kiteconnect SDK not installed — skipping")
            return
        sys.exit("[live-ic] kiteconnect not installed. Run: pip install kiteconnect")

    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(access_token)
    try:
        kite_keys = [f"NSE:{s}" for s in scores]
        kite_last = fetch_kite_last_prices(kite, kite_keys)
    except Exception as exc:
        print(f"[live-ic] kite.quote() rejected: {exc}")
        sys.exit(2)

    ref_closes = _ref_closes_via_qlib(
        list(scores.keys()), decision["as_of"], args.qlib_provider
    )
    rows = compute_live_returns(scores, ref_closes, kite_last)
    if not rows:
        print(f"[live-ic] no overlap between scored picks ({len(scores)}), "
              f"qlib closes ({len(ref_closes)}), and Kite quotes ({len(kite_last)})")
        return

    ic = compute_live_ic(rows)
    captured_at = datetime.now(timezone.utc).isoformat()
    csv_row = {
        "captured_at": captured_at,
        "decision_as_of": decision["as_of"],
        "n_symbols": ic["n"],
        "pearson_ic": "" if ic["pearson_ic"] is None else ic["pearson_ic"],
        "rank_ic": "" if ic["rank_ic"] is None else ic["rank_ic"],
        "mean_return_bps": "" if ic["mean_return_bps"] is None else ic["mean_return_bps"],
        "pct_positive": "" if ic["pct_positive"] is None else ic["pct_positive"],
    }
    append_csv_row(Path(args.output), csv_row)

    print(
        f"[live-ic] decision={decision['as_of']} "
        f"n={ic['n']} pearson={ic['pearson_ic']} rank_ic={ic['rank_ic']} "
        f"mean_ret={ic['mean_return_bps']}bps pct+={ic['pct_positive']}"
    )


if __name__ == "__main__":
    main()
