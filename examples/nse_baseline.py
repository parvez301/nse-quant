#!/usr/bin/env python3
"""Stage 2 baseline: Alpha158 + LightGBM cross-sectional ranker on NIFTY 500.

Prereq: run examples/nse_data_loader.py first to populate data/qlib_data/in_data/.

Usage:
  python examples/nse_baseline.py
  python examples/nse_baseline.py --topk 20 --n_drop 3 --capital 1000000
  python examples/nse_baseline.py --benchmark NIFTY50 --rebalance 5

What the output means:
  IC / Rank IC     -> cross-sectional correlation between predicted and realised returns.
                      Rank IC > 0.04 per day is decent. < 0.02 means the model isn't learning.
  Annualized ret.  -> strategy's gross return before costs.
  Annualized Sharpe-> return / volatility, annualised. After-cost > 1.0 is the bar.
  Max drawdown     -> peak-to-trough loss. Watch this more than the return.
  Excess vs bench  -> the only number that matters. >3% after costs = you've beaten most
                      Indian active mutual funds.
"""
import argparse
import os
import pickle
from pathlib import Path

import numpy as np
import pandas as pd


def configure_qlib(provider_uri: str, region: str = "cn"):
    import qlib
    qlib.init(provider_uri=os.path.expanduser(provider_uri), region=region)


def build_dataset(
    train_range,
    valid_range,
    test_range,
    label_horizon: int,
    instruments: str = "all",
):
    """Build an Alpha158 dataset for cross-sectional ranking.

    Label = forward `label_horizon`-day return on close:  close[t+H] / close[t] - 1
    """
    from qlib.contrib.data.handler import Alpha158
    from qlib.data.dataset import DatasetH

    handler = Alpha158(
        instruments=instruments,
        start_time=train_range[0],
        end_time=test_range[1],
        fit_start_time=train_range[0],
        fit_end_time=train_range[1],
        label=[f"Ref($close, -{label_horizon}) / $close - 1"],
    )
    dataset = DatasetH(
        handler=handler,
        segments={
            "train": tuple(train_range),
            "valid": tuple(valid_range),
            "test":  tuple(test_range),
        },
    )
    return dataset


def train_lgbm(dataset):
    from qlib.contrib.model.gbdt import LGBModel

    model = LGBModel(
        loss="mse",
        learning_rate=0.05,
        num_leaves=63,
        max_depth=8,
        num_threads=os.cpu_count() or 4,
        early_stopping_rounds=50,
        num_boost_round=2000,
        subsample=0.9,
        colsample_bytree=0.85,
        reg_alpha=1.0,
        reg_lambda=1.0,
        min_child_samples=200,
    )
    print("[train] fitting LightGBM on Alpha158 features...")
    model.fit(dataset)
    return model


def compute_ic(pred: pd.DataFrame, label: pd.DataFrame):
    """Per-day Pearson & Spearman cross-sectional correlations."""
    merged = pd.concat([pred, label], axis=1)
    merged.columns = ["score", "label"]
    merged = merged.dropna()

    ic = merged.groupby(level="datetime").apply(
        lambda g: g["score"].corr(g["label"]) if len(g) > 5 else np.nan
    )
    rank_ic = merged.groupby(level="datetime").apply(
        lambda g: g["score"].corr(g["label"], method="spearman") if len(g) > 5 else np.nan
    )
    return ic.dropna(), rank_ic.dropna()


def run_backtest(
    pred_series,
    test_range,
    benchmark: str,
    topk: int,
    n_drop: int,
    capital: float,
    open_cost: float,
    close_cost: float,
    min_cost: float,
    limit_threshold: float,
):
    from qlib.contrib.evaluate import backtest_daily, risk_analysis

    strategy_config = {
        "class": "TopkDropoutStrategy",
        "module_path": "qlib.contrib.strategy",
        "kwargs": {
            "signal": pred_series,
            "topk": topk,
            "n_drop": n_drop,
        },
    }
    exchange_kwargs = {
        "freq": "day",
        "limit_threshold": limit_threshold,
        "deal_price": "close",
        "open_cost": open_cost,      # buy-side slippage + brokerage
        "close_cost": close_cost,    # sell-side + STT 0.1% on delivery
        "min_cost": min_cost,        # Zerodha-style ₹5 floor
        "trade_unit": None,
    }

    print(f"[backtest] {test_range[0]} -> {test_range[1]}  "
          f"topk={topk} drop={n_drop} costs={open_cost}/{close_cost}")

    report, positions = backtest_daily(
        start_time=test_range[0],
        end_time=test_range[1],
        strategy=strategy_config,
        exchange_kwargs=exchange_kwargs,
        benchmark=benchmark,
        account=capital,
    )

    analysis = {
        "excess_return_without_cost": risk_analysis(
            report["return"] - report["bench"], freq="day"
        ),
        "excess_return_with_cost": risk_analysis(
            report["return"] - report["bench"] - report["cost"], freq="day"
        ),
        "strategy_return_with_cost": risk_analysis(
            report["return"] - report["cost"], freq="day"
        ),
    }
    return report, positions, analysis


def main():
    p = argparse.ArgumentParser(
        description="Qlib Alpha158 + LightGBM baseline on NSE data",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--provider_uri", default="data/qlib_data/in_data")
    p.add_argument("--region", default="cn",
                   help="'cn' is fine — Qlib infers the calendar from your data")
    p.add_argument("--benchmark", default="NIFTY50",
                   help="must match a symbol you loaded (NIFTY50 from the loader)")

    p.add_argument("--train", nargs=2, default=["2014-01-01", "2020-12-31"])
    p.add_argument("--valid", nargs=2, default=["2021-01-01", "2022-12-31"])
    p.add_argument("--test",  nargs=2, default=["2023-01-01", "2025-12-31"])

    p.add_argument("--rebalance", type=int, default=5,
                   help="forward-return horizon (days) used as training label")
    p.add_argument("--topk", type=int, default=30)
    p.add_argument("--n_drop", type=int, default=5)

    p.add_argument("--capital", type=float, default=1_000_000,
                   help="starting capital in INR for backtest (cosmetic)")
    p.add_argument("--open_cost", type=float, default=0.0015,   # 15 bps
                   help="buy-side cost (brokerage + slippage + exchange fees)")
    p.add_argument("--close_cost", type=float, default=0.0025,  # 25 bps
                   help="sell-side cost (includes STT 0.1% on delivery)")
    p.add_argument("--min_cost", type=float, default=5.0)
    p.add_argument("--limit_threshold", type=float, default=0.095,
                   help="skip days where |return| exceeds this (circuit-limit proxy)")

    p.add_argument("--out_dir", default="outputs/nse_baseline")
    args = p.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ----- 1. Qlib init ----------------------------------------------------
    configure_qlib(args.provider_uri, args.region)

    # ----- 2. Dataset ------------------------------------------------------
    print(f"[data] train={args.train}  valid={args.valid}  test={args.test}")
    dataset = build_dataset(args.train, args.valid, args.test, args.rebalance)

    # ----- 3. Train --------------------------------------------------------
    model = train_lgbm(dataset)
    with open(out_dir / "model.pkl", "wb") as f:
        pickle.dump(model, f)

    # ----- 4. Predict on the test segment ----------------------------------
    print("[predict] scoring test segment...")
    pred = model.predict(dataset, segment="test")
    if isinstance(pred, pd.Series):
        pred.name = "score"
        pred_df = pred.to_frame()
    else:
        pred_df = pred
        pred_df.columns = ["score"]
    pred_df.to_pickle(out_dir / "pred.pkl")

    # ----- 5. IC analysis --------------------------------------------------
    from qlib.data.dataset.handler import DataHandlerLP
    label = dataset.prepare("test", col_set="label", data_key=DataHandlerLP.DK_R)
    label.columns = ["label"]
    ic, rank_ic = compute_ic(pred_df, label)

    print("\n============== SIGNAL QUALITY ==============")
    print(f" IC mean:       {ic.mean():+.4f}   (IR = {ic.mean()/ic.std():.3f})")
    print(f" Rank IC mean:  {rank_ic.mean():+.4f}   (IR = {rank_ic.mean()/rank_ic.std():.3f})")
    print(f" IC > 0 days:   {(ic > 0).mean():.2%}")
    print(f" N test days:   {len(ic)}")
    ic.to_frame("ic").join(rank_ic.rename("rank_ic")).to_csv(out_dir / "ic.csv")

    # ----- 6. Backtest -----------------------------------------------------
    signal = pred_df["score"]  # Qlib accepts a Series indexed by (datetime, instrument)
    report, positions, analysis = run_backtest(
        pred_series=signal,
        test_range=args.test,
        benchmark=args.benchmark,
        topk=args.topk,
        n_drop=args.n_drop,
        capital=args.capital,
        open_cost=args.open_cost,
        close_cost=args.close_cost,
        min_cost=args.min_cost,
        limit_threshold=args.limit_threshold,
    )
    report.to_pickle(out_dir / "report.pkl")

    # ----- 7. Report -------------------------------------------------------
    print("\n============== BACKTEST RESULTS ==============")
    for name, block in analysis.items():
        print(f"\n--- {name} ---")
        print(block.to_string())

    # Headline numbers
    strat = analysis["strategy_return_with_cost"].iloc[:, 0]
    excess = analysis["excess_return_with_cost"].iloc[:, 0]

    print("\n==================== HEADLINE ====================")
    print(f" Benchmark:                 {args.benchmark}")
    print(f" Strategy annualised ret:   {strat.get('annualized_return', float('nan')):+.2%}")
    print(f" Strategy Sharpe (post-cost): {strat.get('information_ratio', float('nan')):.3f}")
    print(f" Strategy max drawdown:     {strat.get('max_drawdown', float('nan')):.2%}")
    print(f" Excess return vs bench:    {excess.get('annualized_return', float('nan')):+.2%}")
    print(f" Excess Sharpe (IR):        {excess.get('information_ratio', float('nan')):.3f}")
    print("==================================================")

    # Save headline as JSON for later comparison vs Kronos-augmented run
    import json
    headline = {
        "signal": {
            "ic_mean": float(ic.mean()),
            "ic_ir": float(ic.mean() / ic.std()) if ic.std() else None,
            "rank_ic_mean": float(rank_ic.mean()),
            "rank_ic_ir": float(rank_ic.mean() / rank_ic.std()) if rank_ic.std() else None,
        },
        "strategy_post_cost": strat.to_dict(),
        "excess_post_cost": excess.to_dict(),
        "config": vars(args),
    }
    with open(out_dir / "headline.json", "w") as f:
        json.dump(headline, f, indent=2, default=str)

    print(f"\n[saved] model, predictions, report, headline -> {out_dir}/")
    print("\nNext step: add Kronos predictions as an extra feature to this pipeline")
    print("and re-run. If Rank IC improves by 10%+, the foundation model is earning its keep.")


if __name__ == "__main__":
    main()
