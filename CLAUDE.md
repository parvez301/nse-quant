# CLAUDE.md — context for future Claude sessions

This file gives a future Claude (or you) the context to be productive in this
repo without re-deriving the architecture.

## What this repo is

A production-only fork of the parent `Kronos/` experiment. Pure
Qlib + LightGBM cross-sectional ranker on NSE+BSE daily OHLCV. **No transformer
models. No deep learning. No GPU.** That's a feature, not a bug — the simpler
stack outperformed the Kronos foundation model in apples-to-apples A/B.

## Production stack (what the daily cron runs)

```
yfinance --incremental --> Qlib binary store (data/qlib_data/in_data)
                       --> Alpha158 features (qlib.contrib.data.handler)
                       --> LightGBM ranker (qlib.contrib.model.gbdt.LGBModel)
                       --> top-K (default 30) BUY list
                       --> paper portfolio mark-to-market
                       --> P&L kill switch
```

## Architectural decisions worth knowing

1. **Universe = NIFTY Total Market 750** (NIFTY 500 + Microcap 250).
   Bigger universe alone hurts (microcap noise), but with 15-year training
   it net-helps. Don't expand beyond 750 — beyond that you're in penny-stock
   territory that can't actually be traded at retail size.

2. **Region in `qlib.init` is "cn".** That's not wrong — Qlib uses China region
   defaults but learns the calendar from your data. Setting region="us" or
   "in" causes calendar mismatches.

3. **Default rebalance = 5 trading days, topk = 30, drop = 5.** Higher rebalance
   means lower turnover means lower realised costs. Daily rebalance was
   tested — it overtrades into noise.

4. **Costs are flat 15bps buy + 25bps sell in Qlib's backtester.** This
   over-states retail costs (real ADV-aware slippage is ~7bps) but is roughly
   correct at ₹5Cr+ AUM. See `nse_slippage_model.py` to model your real AUM.

5. **PIT survivorship correction is partial-only.** `nse_universe_pit.py`
   filters by listing date (using yfinance first-bar). It does NOT recover
   fully-delisted tickers (yfinance drops them). True survivorship fix needs
   paid data — see README.

6. **Walk-forward t-stat = 3.79.** That's the load-bearing statistical claim.
   8 annual windows, 7 positive, t-test against zero rejects null at p < 0.001.
   Outliers (2020 +178%, 2021 +107%) are post-COVID dispersion regimes — real
   but not repeatable.

## What was tried and rejected (don't re-attempt without reason)

- **Kronos zero-shot as a feature:** RankIC -40%, Sharpe -88%. Negative.
- **Kronos with finetuning:** never tried — would need ~10 hours GPU + NSE-
  specific finetune dataset. Possibly worth revisiting if this stack stops
  working in live trading, but very speculative.
- **Daily rebalance:** worse than 5-day after costs.
- **NIFTY 500 only (vs 750):** worse — needs the longer training window of 750
  to stabilise.
- **Spot-day liquidity filter:** brittle on partial yfinance bars. Use 20-day
  rolling turnover (current default).

## Where to look for what

| You want to... | Read |
|---|---|
| Understand a number in the headline | `outputs/nse_baseline_750_long/headline.json` |
| See historical decisions | `outputs/decisions/*.txt` |
| Inspect paper P&L curve | `outputs/paper_equity.csv` |
| Read the long-form context | `docs/nightly_report.md` |
| Re-run honest evaluation | `examples/nse_walkforward_backtest.py` (~40 min) |
| Tune costs to your AUM | `examples/nse_slippage_model.py --sweep_capital ...` |

## Absolute rules

1. **Don't push live trading code without 90 days clean paper-trade.**
2. **Don't anchor on +31% excess.** The honest forward expectation is +8-15%.
3. **Don't add features without an apples-to-apples A/B.** The Kronos failure
   was identified by exactly such a test.
4. **Don't `rm` `outputs/HALT` without understanding why it was set.**
   `nse_safety.py status` shows why.
5. **Pin the AWS profile per-machine in `.envrc.local`** (gitignored). The
   committed `.envrc` / `activate.sh` default to `AWS_PROFILE=default` —
   override locally so you never accidentally deploy to the wrong account.
   Run `source ./activate.sh` (or install direnv to auto-load `.envrc`)
   before any ad-hoc `aws`/`cdk`/`boto3` command.
