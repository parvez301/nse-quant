#!/usr/bin/env python3
"""Realistic slippage simulator — replaces Qlib's flat 40bps round-trip.

Why
---
Qlib's backtest applies a flat percentage cost (we use 15bps buy + 25bps sell).
That's fine for liquid large-caps but wildly optimistic for the microcap end of
NIFTY Total Market, where a ₹1Cr order in a stock with ₹5Cr daily turnover
moves the price 50-100bps on its own. A backtest that ignores this looks
profitable on paper and bleeds in production.

This script re-simulates the TopkDropoutStrategy from a saved pred.pkl with a
per-trade slippage model:

    slippage_bps = base_bps + impact_coef * (trade_inr / adv_inr) ** 0.5

where ADV = 20-day average traded value (close * volume) for that stock. The
square-root impact law is the standard "Almgren-Chriss" / "BARRA" form used by
real desks. Defaults are conservative for Indian retail-size capital:

    base_bps     = 5      (always-on bid-ask + brokerage residual)
    impact_coef  = 50     (calibrated so a 1%-of-ADV trade adds ~5bps)

Usage
-----
  python examples/nse_slippage_model.py \
      --model_dir outputs/nse_baseline_750_long \
      --capital 1_000_000

  # Stress test — what if you're trading 10x the size?
  python examples/nse_slippage_model.py \
      --model_dir outputs/nse_baseline_750_long \
      --capital 10_000_000

  # Sensitivity sweep
  python examples/nse_slippage_model.py \
      --model_dir outputs/nse_baseline_750_long \
      --sweep_capital 500000 1000000 5000000 10000000 50000000

Output
------
  outputs/nse_baseline_750_long/slippage_report.json  (or sweep CSV)
  Console: side-by-side comparison of headline numbers.
"""
import argparse
import json
import math
import os
import pickle
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass
class SlippageParams:
    base_bps: float = 5.0       # always-on cost regardless of size
    impact_coef: float = 50.0   # square-root impact coefficient
    impact_exponent: float = 0.5
    impact_cap_bps: float = 200.0  # don't pretend you can model a 5%-of-ADV trade
    brokerage_bps: float = 3.0  # Zerodha-style flat brokerage in bps
    stt_sell_bps: float = 10.0  # Securities transaction tax on delivery sell


def fmt_pct(x: float) -> str:
    return f"{x:+.2%}" if not math.isnan(x) else "  nan"


def load_universe_data(provider_uri: str, instruments: list[str],
                       start: str, end: str) -> pd.DataFrame:
    """Pull close + volume from Qlib, compute 20-day rolling ADV (in INR)."""
    import qlib
    from qlib.data import D

    qlib.init(provider_uri=os.path.expanduser(provider_uri), region="cn")
    df = D.features(instruments, ["$close", "$volume"],
                    start_time=start, end_time=end)
    df = df.rename(columns={"$close": "close", "$volume": "volume"})
    df["turnover"] = df["close"] * df["volume"]
    # ADV = 20-day rolling mean turnover, per instrument
    df = df.sort_index()
    df["adv20"] = (
        df.groupby(level="instrument")["turnover"]
          .rolling(20, min_periods=5).mean()
          .reset_index(level=0, drop=True)
    )
    return df


def simulate(
    pred: pd.DataFrame,
    px: pd.DataFrame,
    capital: float,
    topk: int,
    n_drop: int,
    rebalance: int,
    slip: SlippageParams,
    benchmark_ret: pd.Series | None = None,
) -> dict:
    """Day-by-day simulation of the TopkDropoutStrategy with ADV slippage.

    Parameters
    ----------
    pred : DataFrame indexed by (datetime, instrument), column 'score'
    px   : DataFrame indexed by (datetime, instrument), columns close/volume/adv20
    """
    pred = pred.copy()
    if "score" not in pred.columns:
        pred.columns = ["score"]
    pred = pred[["score"]]

    dates = sorted(pred.index.get_level_values("datetime").unique())
    holdings: dict[str, float] = {}      # instrument -> shares
    cash = capital
    nav_series = []
    cost_series = []
    realized_slippage_bps = []

    rebalance_dates = dates[::rebalance]
    rebalance_set = set(rebalance_dates)

    for i, d in enumerate(dates):
        try:
            day_px = px.xs(d, level="datetime")
        except KeyError:
            # no price bar for this date
            if nav_series:
                nav_series.append((d, nav_series[-1][1]))
            else:
                nav_series.append((d, capital))
            continue

        # Mark to market first (using today's close)
        equity = cash
        for inst, shares in holdings.items():
            if inst in day_px.index and not pd.isna(day_px.loc[inst, "close"]):
                equity += shares * day_px.loc[inst, "close"]

        day_cost = 0.0

        if d in rebalance_set:
            try:
                day_pred = pred.xs(d, level="datetime")["score"].dropna()
            except KeyError:
                nav_series.append((d, equity))
                cost_series.append((d, 0.0))
                continue

            # Filter to instruments with a valid close + adv20 today
            valid = day_pred.index.intersection(
                day_px.dropna(subset=["close", "adv20"]).index
            )
            day_pred = day_pred.loc[valid]
            if len(day_pred) < topk:
                nav_series.append((d, equity))
                cost_series.append((d, 0.0))
                continue

            # New target = top-k by score
            target = set(day_pred.nlargest(topk).index)
            current = set(holdings.keys())
            # Drop the n_drop worst current names (per today's score)
            current_in_pred = [c for c in current if c in day_pred.index]
            sorted_current = sorted(current_in_pred, key=lambda x: day_pred[x])
            to_drop = set(sorted_current[:n_drop]) if current else set()
            # Anything in current but no longer in target also drops
            to_drop |= current - target
            # Buys: top-k from target not currently held
            need_to_add = list(target - (current - to_drop))
            # Take only top need_to_add by score
            need_to_add = sorted(need_to_add, key=lambda x: -day_pred[x])[:n_drop + len(target - current)]

            # Execute sells first (free up cash)
            for inst in to_drop:
                if inst not in holdings or inst not in day_px.index:
                    continue
                shares = holdings[inst]
                price = day_px.loc[inst, "close"]
                trade_inr = abs(shares * price)
                if trade_inr <= 0:
                    continue
                adv = day_px.loc[inst, "adv20"]
                slip_bps = compute_slippage(trade_inr, adv, slip)
                # Brokerage + STT on sell
                fee_bps = slip.brokerage_bps + slip.stt_sell_bps
                total_bps = slip_bps + fee_bps
                proceeds = shares * price * (1 - total_bps / 10_000)
                cash += proceeds
                day_cost += shares * price * (total_bps / 10_000)
                realized_slippage_bps.append(slip_bps)
                del holdings[inst]

            # Then buys — equal weight across new positions
            new_target_size = max(0, topk - len(holdings))
            buy_list = need_to_add[:new_target_size]
            if buy_list:
                # Re-mark equity after sells
                equity_after_sells = cash + sum(
                    holdings[i] * day_px.loc[i, "close"]
                    for i in holdings if i in day_px.index
                )
                budget_per_buy = equity_after_sells / topk
                for inst in buy_list:
                    if inst not in day_px.index:
                        continue
                    price = day_px.loc[inst, "close"]
                    if price <= 0:
                        continue
                    trade_inr = budget_per_buy
                    if trade_inr > cash:
                        trade_inr = cash * 0.99
                    if trade_inr < 1000:
                        continue
                    adv = day_px.loc[inst, "adv20"]
                    slip_bps = compute_slippage(trade_inr, adv, slip)
                    fee_bps = slip.brokerage_bps  # no STT on buy
                    total_bps = slip_bps + fee_bps
                    # Effective buy price after slippage
                    eff_price = price * (1 + total_bps / 10_000)
                    shares = trade_inr / eff_price
                    holdings[inst] = holdings.get(inst, 0) + shares
                    cash -= trade_inr
                    day_cost += trade_inr * (total_bps / 10_000)
                    realized_slippage_bps.append(slip_bps)

            # Recompute equity post-trade
            equity = cash + sum(
                holdings[i] * day_px.loc[i, "close"]
                for i in holdings if i in day_px.index
            )

        nav_series.append((d, equity))
        cost_series.append((d, day_cost))

    nav = pd.Series({d: v for d, v in nav_series}).sort_index()
    cost = pd.Series({d: v for d, v in cost_series}).sort_index()
    daily_ret = nav.pct_change().fillna(0.0)

    # Headline stats
    n_days = len(daily_ret)
    if n_days < 2:
        return {"error": "insufficient days simulated"}

    ann = (nav.iloc[-1] / nav.iloc[0]) ** (252 / n_days) - 1 if nav.iloc[0] > 0 else float("nan")
    sharpe = (daily_ret.mean() * 252) / (daily_ret.std() * np.sqrt(252)) if daily_ret.std() > 0 else float("nan")
    rolling_max = nav.cummax()
    mdd = (nav / rolling_max - 1).min()

    out = {
        "ann_return": float(ann),
        "sharpe": float(sharpe),
        "max_drawdown": float(mdd),
        "total_cost_inr": float(cost.sum()),
        "total_cost_pct": float(cost.sum() / capital),
        "n_rebalances": int((cost > 0).sum()),
        "avg_slippage_bps": float(np.mean(realized_slippage_bps)) if realized_slippage_bps else 0.0,
        "p95_slippage_bps": float(np.percentile(realized_slippage_bps, 95)) if realized_slippage_bps else 0.0,
        "final_nav": float(nav.iloc[-1]),
        "final_cash": float(cash),
        "n_holdings_end": len(holdings),
    }

    if benchmark_ret is not None:
        bench = benchmark_ret.reindex(daily_ret.index).fillna(0.0)
        excess_daily = daily_ret - bench
        excess_ann = (1 + excess_daily).prod() ** (252 / n_days) - 1 if n_days > 0 else float("nan")
        excess_sharpe = (excess_daily.mean() * 252) / (excess_daily.std() * np.sqrt(252)) if excess_daily.std() > 0 else float("nan")
        out["excess_ann_return"] = float(excess_ann)
        out["excess_sharpe"] = float(excess_sharpe)
    return out


def compute_slippage(trade_inr: float, adv_inr: float, slip: SlippageParams) -> float:
    """Square-root impact model. Returns bps."""
    if adv_inr is None or pd.isna(adv_inr) or adv_inr <= 0:
        return slip.impact_cap_bps  # treat unknown ADV as worst case
    participation = trade_inr / adv_inr
    impact = slip.impact_coef * (participation ** slip.impact_exponent)
    total = slip.base_bps + impact
    return min(total, slip.impact_cap_bps)


def get_benchmark_returns(provider_uri: str, symbol: str, start: str, end: str) -> pd.Series:
    import qlib
    from qlib.data import D
    qlib.init(provider_uri=os.path.expanduser(provider_uri), region="cn")
    df = D.features([symbol], ["$close"], start_time=start, end_time=end)
    if df.empty:
        return pd.Series(dtype=float)
    s = df.xs(symbol, level="instrument")["$close"]
    return s.pct_change().fillna(0.0)


def main():
    p = argparse.ArgumentParser(
        description="ADV-aware slippage simulator on a saved baseline.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--model_dir", required=True,
                   help="output dir from nse_baseline.py (must contain pred.pkl)")
    p.add_argument("--provider_uri", default="data/qlib_data/in_data")
    p.add_argument("--benchmark", default="NIFTY50")
    p.add_argument("--capital", type=float, default=1_000_000)
    p.add_argument("--topk", type=int, default=30)
    p.add_argument("--n_drop", type=int, default=5)
    p.add_argument("--rebalance", type=int, default=5)
    p.add_argument("--base_bps", type=float, default=5.0)
    p.add_argument("--impact_coef", type=float, default=50.0)
    p.add_argument("--sweep_capital", type=float, nargs="*", default=None,
                   help="if given, sweep these capital levels and write CSV")
    args = p.parse_args()

    model_dir = Path(args.model_dir)
    pred_path = model_dir / "pred.pkl"
    if not pred_path.exists():
        raise SystemExit(f"pred.pkl not found in {model_dir}")

    pred = pd.read_pickle(pred_path)
    if isinstance(pred, pd.Series):
        pred = pred.to_frame("score")

    # Determine date range from predictions
    dates = pred.index.get_level_values("datetime")
    start = (dates.min() - pd.Timedelta(days=40)).strftime("%Y-%m-%d")  # +buffer for adv20
    end = dates.max().strftime("%Y-%m-%d")
    instruments = sorted(pred.index.get_level_values("instrument").unique())

    print(f"[load] {len(instruments)} instruments, {start}..{end}")
    px = load_universe_data(args.provider_uri, instruments, start, end)

    bench = get_benchmark_returns(args.provider_uri, args.benchmark, start, end)

    slip = SlippageParams(base_bps=args.base_bps, impact_coef=args.impact_coef)

    capitals = args.sweep_capital if args.sweep_capital else [args.capital]

    rows = []
    for cap in capitals:
        print(f"\n=== capital ₹{cap:,.0f} ===")
        result = simulate(
            pred=pred, px=px, capital=cap,
            topk=args.topk, n_drop=args.n_drop, rebalance=args.rebalance,
            slip=slip, benchmark_ret=bench,
        )
        result["capital"] = cap
        rows.append(result)

        print(f"  Annualised return:    {fmt_pct(result['ann_return'])}")
        print(f"  Sharpe:               {result['sharpe']:+.3f}")
        print(f"  Max drawdown:         {fmt_pct(result['max_drawdown'])}")
        if "excess_ann_return" in result:
            print(f"  Excess vs {args.benchmark}:        {fmt_pct(result['excess_ann_return'])}")
            print(f"  Excess Sharpe:        {result['excess_sharpe']:+.3f}")
        print(f"  Avg / p95 slippage:   {result['avg_slippage_bps']:.1f} / "
              f"{result['p95_slippage_bps']:.1f} bps")
        print(f"  Total cost drag:      {fmt_pct(result['total_cost_pct'])} "
              f"(₹{result['total_cost_inr']:,.0f})")

    # Compare against baseline headline (if present)
    baseline_path = model_dir / "headline.json"
    if baseline_path.exists():
        baseline = json.loads(baseline_path.read_text())
        b_strat = baseline.get("strategy_post_cost", {})
        b_excess = baseline.get("excess_post_cost", {})
        print("\n=== vs Qlib's flat-cost backtest ===")
        try:
            print(f"  Qlib strat ann ret:   "
                  f"{float(b_strat.get('annualized_return', 'nan')):+.2%}")
            print(f"  Qlib strat Sharpe:    "
                  f"{float(b_strat.get('information_ratio', 'nan')):+.3f}")
            print(f"  Qlib excess ann ret:  "
                  f"{float(b_excess.get('annualized_return', 'nan')):+.2%}")
        except (TypeError, ValueError):
            pass

    out_path = model_dir / ("slippage_sweep.csv" if args.sweep_capital else "slippage_report.json")
    if args.sweep_capital:
        pd.DataFrame(rows).to_csv(out_path, index=False)
    else:
        out_path.write_text(json.dumps(rows[0], indent=2, default=str))
    print(f"\n[saved] {out_path}")


if __name__ == "__main__":
    main()
