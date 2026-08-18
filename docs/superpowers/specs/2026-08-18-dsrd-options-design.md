# DSRD Options-Selling — Design Spec

**Date:** 2026-08-18 · **Status:** approved-in-chat, spec for review
**Source idea:** operator's workshop notes ("DSRD" — Direction, Support,
Resistance, Delta) describing monthly short strangles on liquid NSE stock
options, ±10% / ~0.15-delta strikes, 80%-premium profit target, hard stops.

## 1. Objective and stance

Evaluate — then, only if evidence supports it, paper-trade — a short-strangle
premium-collection strategy on NSE stock options. The build order is
deliberately adversarial: the backtest judge (Phase 1) exists to **disprove**
the strategy. UI and paper-trading phases are contingent on the judge's
verdict. A cousin strategy (short straddle, sibling nse-options repo) already
failed its walk-forward gate at −₹93k; the default expectation is failure.

Paper capital: ₹1,00,000. Real money: out of scope for this spec entirely
(repo rule: 90 days clean paper first).

## 2. Phases and kill-gates

| Phase | Deliverable | Gate to proceed |
|---|---|---|
| 0 | F&O data layer + greeks | Data QA passes (§5) |
| 1 | Walk-forward backtest ("the judge") | Pass criteria (§7) — else STOP |
| 2 | Daily paper-trade step in existing cron | 0 manual interventions for 2 weeks |
| 3 | OPTIONS tab in v2 dashboard | — |

## 3. Module layout

Library code in a new top-level `options/` package; runnable entry points
follow repo convention as `examples/nse_options_*.py` thin wrappers.

```
options/
  fo_bhavcopy.py    # download/parse NSE F&O bhavcopy (UDiFF ≥ Jul-2024 and
                    # legacy format before), cache under data/fo_bhavcopy/
  greeks.py         # Black-76 IV inversion + delta (own Newton solver or
                    # py_vollib; futures price as underlying where available)
  sigma.py          # expected-move bands: spot × IV × sqrt(DTE/365), 1σ/2σ
  strikes.py        # strike selection: |delta| in [0.10, 0.20], ideal 0.15,
                    # AND distance from spot ≥ 8%; else next-further strike
  filters.py        # RSI(14) regime, earnings-window exclusion, macro-event
                    # blackout (hand-maintained data/options_blackouts.yaml)
  score.py          # 0-100 trade score (liquidity 25, RSI 20, delta quality
                    # 25, σ-distance 15, earnings distance 15); trade ≥ 75
  costs.py          # Zerodha retail cost model (§6)
  backtest.py       # walk-forward monthly-cycle engine (§7)
  paper.py          # daily paper-trade loop (Phase 2)
examples/
  nse_options_fetch.py      # backfill/update F&O bhavcopy archive
  nse_options_backtest.py   # run the judge, write outputs/options/judge/
  nse_options_paper.py      # Phase 2 entry point (cron step)
tests/
  test_options_*.py         # per-module; greeks pinned to reference values
```

## 4. Data sources

| Need | Source | Notes |
|---|---|---|
| Historical option chains | NSE F&O bhavcopy daily archives | Free; per-contract close/settle, OI, volume. Format break Jul-2024 (UDiFF) — parser handles both. Backfill target: 2019-01 onward (covers COVID crash tail event). |
| Underlying spot OHLCV, RSI, HV | Existing qlib store (`data/qlib_data/in_data`) | Already maintained daily. |
| IV / delta | Computed (Black-76 on futures, else Black-Scholes on spot), r = 7% | NSE EOD files carry no IV. |
| Strikes/lots/expiries (live, Phase 2) | Kite instruments dump | Existing Kite integration. |
| Earnings dates | NSE board-meetings feed; fallback: exclude expiry cycles containing quarter-end result windows | Precision matters less than recall — over-excluding is acceptable. |
| Macro blackouts | `data/options_blackouts.yaml` (Budget day, general-election weeks) | Hand-maintained, ~5 lines/year. |

## 5. Phase 0 data QA gate

- ≥ 95% of expected trading days present per year in the F&O archive.
- For 10 sampled (stock, month) cells: strikes ladder is contiguous, OI > 0
  near ATM, computed ATM IV within [8%, 120%] (sanity band).
- Greeks module reproduces py_vollib reference values to 1e-4 on a pinned
  test vector set.

## 6. Strategy rules under test (fixed before running — no peeking)

- Universe: **all NSE F&O stocks with per-period membership** (survivorship-
  aware via contract presence in that month's bhavcopy). Report a
  **top-20-by-mcap subset** as a separate cut of the same run.
- Cycle: enter first Friday after monthly expiry (skip if score < 75 or
  filters exclude); exit at 80% of collected premium, or stop-loss, or
  time-exit last Tuesday before expiry. Positions: max 3 concurrent, margin
  target ≤ 70% of capital (margin ≈ SPAN proxy: 20% of notional − OTM amount,
  floor 10% notional — documented approximation, calibrated against Kite
  margin API in Phase 2).
- Strikes: per `strikes.py` (delta-based with ≥ 8% distance floor).
- Stop-loss variants tested as a grid: 1:1, 1:1.5, 1:2, none.
- Costs per leg: brokerage ₹20/order, STT 0.1% on sell premium (and 0.125%
  intrinsic if exercised — avoided by time-exit), NSE txn 0.053% premium,
  GST 18% on (brokerage + txn), SEBI ₹10/crore, stamp 0.003%. Slippage:
  half the modeled bid-ask spread, floor ₹0.05/share, doubled on stop-loss
  exits (stops trade in stressed books).

## 7. Phase 1 — the judge (pass criteria fixed in advance)

Walk-forward monthly cycles 2019-01 → present (~90 cycles), no parameter
fitted on data it is then judged on: the stop-loss grid is chosen on
2019–2022 and judged on 2023→present only.

**PASS requires all of:**
1. Net-of-cost CAGR on judged window > FD benchmark (7%).
2. Sharpe ≥ NIFTY-50 buy-and-hold Sharpe on the same window.
3. Max drawdown < 30% of capital.
4. March-2020 cycle simulated explicitly; account survives (> 60% capital).
5. Monthly excess return t-stat > 2 on the judged window (same window as
   criteria 1–2; the 2019–2022 selection years never enter the inference).

**Also reported (not gating):** win rate, profit factor, premium-capture %,
per-stock attribution, ±10%-breach frequency, results with/without RSI
filter and with/without earnings exclusion (the doc's claims, tested),
probability of >30% loss (block bootstrap), top-20 subset vs full universe.

Outputs: `outputs/options/judge/headline.json` + `report.md` + equity/DD
CSVs. Judged in one honest report — same style as
`outputs/nse_baseline_750_long/headline.json`.

## 8. Phase 2 sketch (contingent)

One extra step in the existing daily cron container after the equity
pipeline: refresh chains for open/candidate positions (Kite quotes), apply
exit/stop/score logic, append `outputs/options/paper_state.json` +
`paper_equity.csv` (separate ledger from the stock ranker's; the two paper
books never mix). SNS alert on stop-loss hit, via existing alerting. HALT
file honored: if `outputs/HALT` exists, no new entries.

## 9. Phase 3 sketch (contingent)

Fifth tab "OPTIONS" in `ui_lambda/v2/` (new `options.jsx`), served by
existing routes; new `/api/options/*` endpoints in `handler.py` reading the
S3 JSONs. Panels: paper equity curve, open strangles with P/L shape +
σ-bands + breach distance, candidate scorecard, judge headline.

## 10. Error handling & testing conventions

- Data layer: missing/malformed bhavcopy days are recorded in a gap ledger,
  never silently skipped; backtest refuses to run a cycle with > 2 missing
  days.
- Greeks: non-converging IV inversion returns None; strike selector treats
  None-IV contracts as untradeable rather than guessing.
- TDD per repo norms; every module lands with tests, reference vectors
  pinned for greeks/sigma; backtest engine gets a synthetic-data test where
  the correct P&L is hand-computable.

## 11. Explicitly out of scope

Index options, weekly expiries, intraday adjustment logic, live order
placement, margin pledging, the doc's "chasing and adjustment strategy"
(breaches are recorded and counted, not adjusted — matching Prompt 1's
"do not assume adjustment").
