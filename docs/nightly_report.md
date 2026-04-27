# Kronos/NSE overnight run — 2026-04-25

What I did while you were asleep. Read top-to-bottom; everything under "How to start tomorrow" is what you actually need to act on.

---

## TL;DR (60 seconds)

1. Full NIFTY 500 Qlib dataset built (497 instruments, 2014-01-01 → 2026-04-24).
2. Baseline model trained: **Rank IC 0.043, post-cost Sharpe 1.41, +21% excess return vs NIFTY 50**.
   Those are good numbers — but see "Honest caveats" before celebrating. Probably inflated by 5-10% from survivorship bias.
3. Daily decision runner + paper-trade logger work end-to-end. You have a concrete BUY list for 2026-04-23 already sitting at `outputs/decisions/2026-04-23.txt`.
4. Simulated paper portfolio already initialised at `outputs/current_portfolio.csv` (20 stocks, ₹10 lakh starting capital).
5. Kronos-as-feature generation is running in the background — should finish in ~90 minutes from report time. Augmented-baseline comparison will auto-append to this report at the end.

**Critical**: do NOT put real money into anything here until you've paper-traded for 3 months. This is v1. It will have bugs.

---

## What runs, right now, with no further work

| Capability | Command | Output |
|---|---|---|
| Refresh NSE data | `.venv/bin/python examples/nse_data_loader.py` | `~/.qlib/qlib_data/in_data/` |
| Emit today's BUY/SELL list | `.venv/bin/python examples/nse_daily_decision.py --model_dir outputs/nse_baseline_500` | `outputs/decisions/YYYY-MM-DD.{json,txt}` |
| Simulate a day's fills (paper) | `.venv/bin/python examples/nse_paper_trade.py execute YYYY-MM-DD` | `outputs/current_portfolio.csv`, `outputs/trade_log.csv`, `outputs/paper_equity.csv` |
| Mark portfolio to latest close | `.venv/bin/python examples/nse_paper_trade.py mark` | appends to `paper_equity.csv` |
| Rolling performance report | `.venv/bin/python examples/nse_paper_trade.py report` | stdout; needs >60 days of data to be meaningful |
| Full cron-friendly daily run | `examples/run_daily.sh` | runs decision + mark in one shot |
| Re-train on recent data (monthly/quarterly) | `.venv/bin/python examples/nse_walkforward.py --refit_through 2026-04-30` | `outputs/nse_baseline_500_YYYY_MM_DD/` |

---

## Honest performance caveats — read before trusting the numbers

The Rank IC 0.043 / post-cost Sharpe 1.41 / +21% excess return numbers are from a 3-year backtest (2023-01-01 → 2026-04-23). They look great. They are probably overstated. Here's why, ranked by how much they inflate:

1. **Survivorship bias (biggest)**. The data loader pulls *today's* NIFTY 500 constituents. Stocks that got removed (Yes Bank restructuring, Reliance Capital bankruptcy, etc.) are missing from history entirely. Your model "learned" from a universe that excludes the losers. Rough correction: subtract 3-8% from annualised return to get a fair estimate.
2. **2023-2025 Indian bull market**. NIFTY 50 roughly doubled in the test window. Any long-biased strategy makes money in that regime. Rerun on 2018-2020 (COVID drawdown) to stress-test.
3. **No transaction impact modelling**. The 15/25 bps cost is realistic for Zerodha fees + STT, but it doesn't model market impact when you buy ₹50k of a small-cap. At tiny capital you're fine; at ₹1 crore+, slippage gets ugly.
4. **No circuit-limit exit discipline**. The backtest treats circuit-locked days as unavailable for trading but doesn't simulate what happens when you *need* to exit a 20%-down lockedname. In reality, you could be stuck for days.
5. **Overfitting to 105 boosting rounds** — probably mild, since the early-stop was validation-driven, but not zero.

**Realistic expectation**: strip 3-5% from excess return (survivorship), discount another 2-3% for regime and slippage. Real-world post-cost excess return is probably **5-15% vs NIFTY 50**, with 25-35% max drawdown. Still solid, but not 21%.

### Matched-window baseline (more honest)

To give Kronos a fair A/B, I also trained the baseline on a **shorter, more recent window** (train 2020-06 → 2023-12, test 2025-2026) — matching the Kronos feature availability. Results:

| Metric | Long window (2015-2022 train) | Matched window (2020-2023 train) |
|---|---|---|
| Rank IC mean | +0.0434 | +0.0139 |
| IC IR | +0.5193 | +0.3092 |
| Post-cost Sharpe | +1.41 | +0.27 |
| Annualised excess vs NIFTY50 | +21.1% | **+4.3%** |
| Max drawdown | -26.5% | -29.7% |

The +4.3% number is the **honest bar**. Any retail-tradeable quant strategy that beats NIFTY 50 by 4-5% per year after realistic costs is already in the top decile of Indian active mutual funds. The Kronos-augmented run (pending) needs to beat *this* number to justify its compute cost.

---

## How to start tomorrow morning (step-by-step)

### Morning of day 1

```bash
cd <path-to-repo>

# See the decisions I already generated for you
cat outputs/decisions/2026-04-23.txt

# Check the simulated portfolio I opened
cat outputs/current_portfolio.csv

# Mark to today's close (will include whatever bars yfinance has landed)
./.venv/bin/python examples/nse_paper_trade.py mark
```

### Daily routine (from day 2 onwards)

```bash
# One command. Run it at 08:30 IST.
./examples/run_daily.sh

# Review outputs/decisions/YYYY-MM-DD.txt
# If you agree, simulate the fills at today's close:
./.venv/bin/python examples/nse_paper_trade.py execute YYYY-MM-DD

# Weekly — glance at performance
./.venv/bin/python examples/nse_paper_trade.py report
```

### Monthly

```bash
# Retrain on the latest data — model decay is real.
./.venv/bin/python examples/nse_walkforward.py --refit_through 2026-05-31
# Then update MODEL_DIR in examples/run_daily.sh to the new folder.
```

### Data refresh (do this weekly at minimum)

```bash
./.venv/bin/python examples/nse_data_loader.py
# 20-40 min. Download only + Qlib bin rebuild. Safe to re-run; idempotent.
```

### To actually trade real money (only after 3 months of paper, and even then, small)

The decision JSON already contains rank/score/symbol tuples. Use Zerodha Kite Connect (₹2000/month API key from console.zerodha.com):

```python
# Pseudo-code — NOT yet written; you'll write this after paper trading.
import json
from kiteconnect import KiteConnect

kite = KiteConnect(api_key=...)
kite.set_access_token(...)

decision = json.load(open("outputs/decisions/2026-05-01.json"))
for buy in decision["actions"]["BUY"]:
    kite.place_order(
        tradingsymbol=buy["symbol"],
        exchange="NSE",
        transaction_type="BUY",
        quantity=...,  # compute from your capital / topk
        order_type="MARKET",
        product="CNC",
    )
```

I deliberately did not wire this up. If I had, one bug would cost you real money tonight.

---

## Files written tonight

```
examples/
  nse_data_loader.py         # yfinance -> Qlib binary pipeline (already existed, fixed dump_bin CLI arg)
  nse_baseline.py            # Alpha158 + LightGBM baseline (already existed)
  nse_daily_decision.py      # daily BUY/HOLD/SELL emitter, robust 20-day turnover filter
  nse_paper_trade.py         # paper-trade execute/mark/report
  nse_kronos_features.py     # Kronos -> parquet feature generator, batched MPS inference
  nse_baseline_augmented.py  # baseline + Kronos features, with auto-diff vs non-augmented
  nse_kronos_benchmark.py    # latency microbenchmark so you don't waste 31 hours
  nse_walkforward.py         # monthly/quarterly refit helper
  run_daily.sh               # cron-friendly wrapper for decision + mark

outputs/
  nse_baseline/              # original 49-stock baseline (weak, for reference)
  nse_baseline_lowturn/      # 49-stock with lower turnover (Option B from earlier)
  nse_baseline_500/          # ⭐ the full NIFTY 500 model. This is what daily runner uses.
  kronos_features/           # sparse Kronos-derived features (in progress — see last section)
  nse_baseline_augmented/    # will be populated once Kronos features land
  decisions/                 # one JSON + one txt per day the runner fires
  current_portfolio.csv      # your simulated paper holdings
  trade_log.csv              # audit trail of every simulated fill
  paper_equity.csv           # daily marked-to-market equity
  nightly_report.md          # this file
  daily.log                  # append-only log of each run_daily.sh run
```

---

## Known issues / things I couldn't finish

1. **Survivorship bias is not fixed.** Would need historical NIFTY 500 constituents data, which isn't free. Cheap proxy: also pull NIFTY Next 50 + NIFTY Midcap 150 to cover the delisted cohort indirectly. (Edit `NIFTY_50` in `nse_data_loader.py` to include these.)
2. **`nse_baseline.py` uses `region='cn'`** in Qlib init. This doesn't break anything (calendar is inferred from data), but default benchmark names will be Chinese if you forget to pass `--benchmark NIFTY50`. The daily runner handles this correctly.
3. **Circuit-limit handling is approximate.** Qlib's `limit_threshold=0.095` skips days with |return| > 9.5%, which is a proxy, not real circuit-lock simulation.
4. **Sentiment / news / FinBERT layer not built.** Would add another 5-15% Sharpe per my earlier estimate but needs data scraping infrastructure. Defer to month 2 of paper trading.
5. **No live IC monitoring.** The paper-trade report gives strategy Sharpe but not daily prediction quality. Should add a `report-ic` subcommand that compares each day's predictions to next-N-day returns once data is available. Ran out of time to wire it.
6. **No Kite Connect integration.** Deliberately not written; real-money scaffolding is a solo decision, not an overnight auto-generate.

---

## What's still running as of report-write time

Background task: `nse_kronos_features.py` is generating Kronos-derived features on the full 496-stock universe, 2020-01-01 → 2026-04-24, biweekly sampling (158 target dates), pred_len=5, lookback=250.

Timing observed so far: ~40 seconds per date (353 eligible stocks × batched MPS inference). ETA ~100 minutes from start time.

Once it finishes, I'll:
1. Run `nse_baseline_augmented.py` to train LightGBM on Alpha158 + Kronos features.
2. Compare headline metrics against the non-augmented baseline.
3. Append results to this report under a new "Kronos augmentation results" section.
4. Write either "Kronos earned its keep — keep it" or "Kronos didn't help — drop it".

If the augmented run doesn't land by morning (background task crashed, Kronos inference was slower than expected, etc.), you'll find a clear status at the bottom of this file.

---

*End of pre-Kronos report.*

### Kronos feature gen — bug caught and fixed

First attempt crashed at step 20/158 — `pd.DataFrame.to_parquet` hit a non-existent dir on the first incremental flush (my mkdir was at the end of `generate()` instead of the top). Fixed in `examples/nse_kronos_features.py:211` and relaunched at 01:30 IST. Completed 04:33 IST after 3.04 hours of MPS inference.

Output: `outputs/kronos_features/features_liquid100.parquet` — 63,382 rows, 158 dates × 468 stocks, 3 columns (`kronos_fwd5_ret`, `kronos_fwd5_vol`, `kronos_dir_conf`).

---

## Kronos augmentation results — verdict: **DROP IT**

Apples-to-apples A/B on the matched 2020-2023 train / 2024 valid / 2025-2026 test window:

| Metric | Baseline (Alpha158 only) | Augmented (Alpha158 + Kronos) | Delta |
|---|---|---|---|
| **Rank IC mean** | +0.0139 | +0.0082 | **-40.5%** |
| IC IR | +0.3086 | +0.2166 | -29.8% |
| **Strategy Sharpe (post-cost)** | +0.27 | +0.03 | **-87.6%** |
| **Annualised excess vs NIFTY50** | **+4.3%** | **-1.6%** | -136% (sign-flipped) |
| Max drawdown | -29.7% | -27.5% | small improvement |

Kronos features made the model **worse** across every signal-quality metric. The strategy went from beating NIFTY 50 by +4.3% to losing to it by -1.6%.

LightGBM did *use* the Kronos features (the importance table shows 65 splits each on `kronos_fwd5_ret` and `kronos_fwd5_vol`, gain of ~10 each). The features just pointed the wrong way.

### Why Kronos didn't help (honest forensics)

1. **Same-horizon redundancy**. Kronos's 5-day predicted return is forecasting the *same* horizon as the LightGBM label (5-day forward close return). It's a noisy upstream pre-prediction of the target. A proper feature engineering pattern would be: forecast a *different* horizon (20-day) so Kronos provides leading-indicator info, not a noisy version of the label.

2. **Forward-filled staleness**. Features were computed every 10 trading days then forward-filled to daily. Each Kronos value is therefore "stale" for 9 of 10 days. A 5-day-ahead forecast that's already 9 days old is meaningless.

3. **Zero-shot domain mismatch**. Kronos was pretrained on 45+ global exchanges, but never specifically on NSE. The model's prior may not match Indian microstructure (circuit limits, T+1 settlement, retail-flow-driven volatility patterns). Finetuning Kronos on NSE data is the only honest way to test if it has any signal here at all — that's a 2-3 day GPU job, not feasible overnight.

4. **Sample_count=1**. We averaged a single forecast path per stock to keep compute tractable. Kronos's authors recommend 5-10 paths averaged. With `sample_count=1`, the directional confidence feature (`kronos_dir_conf`) is essentially binary noise — explaining its near-zero feature importance (5 splits, 0.44 gain).

### What to do with this finding

**Recommendation: drop Kronos from the production stack.** Stick with `outputs/nse_baseline_500_matched/` (or the longer-window `nse_baseline_500/` if you accept survivorship inflation) as your daily-decision model.

If you want to revisit Kronos later, the *right* experiment is:
- Finetune Kronos-small on NSE data via `finetune/qlib_data_preprocess.py` + `train_predictor.py` (2-3 days on a rented A100/RTX 4090)
- Re-run feature generation with `pred_len=20` (different horizon than the 5-day label)
- Use `sample_count=10` so the directional confidence feature is meaningful
- Compute features daily, not biweekly (run during market-closed hours overnight)

Without all four changes, Kronos isn't worth the compute.

This is a good failed experiment — clear answer, fast to interpret, no ambiguity. The +4.3% excess from the plain Alpha158 + LightGBM baseline is your real production signal.

---

## Final state at hand-off

**Production model**: `outputs/nse_baseline_500_matched/` (matched window, +4.3% excess)
**Production daily runner**: `examples/run_daily.sh` — already wired to the longer-window model. To use the matched baseline instead, edit `MODEL_DIR=outputs/nse_baseline_500_matched` in that file.

I deliberately left the longer-window model wired in by default because it picked saner stocks (real liquid mid/large caps in the 2026-04-23 decision). But for honest performance reporting, the matched-window model's 4.3% number is the truth.

**Augmented model** (do NOT use): `outputs/nse_baseline_augmented/` — kept for reference, do not use for live decisions.

**Decisions emitted tonight**: `outputs/decisions/2026-04-23.{json,txt}` (long-window model). Run the daily script tomorrow morning to get fresh ones.

**Paper portfolio**: `outputs/current_portfolio.csv` initialised with 20 BUYs from 2026-04-23. Run `mark` daily to track. Run `report` weekly.

You have a working stack. It is not a money-printing machine. It is a respectable retail-quant baseline that needs 3+ months of paper trading before any of it touches real capital. Sleep well.

---

## Update — 2026-04-26: expanded universe to 750 stocks × 20 years

User requested: "20 years of history, more than 500 stocks, both NSE and BSE, then incremental for daily."

### Loader changes
- Default index switched to **NIFTY Total Market** (750 stocks = NIFTY 500 + NIFTY Microcap 250) — the broadest official NSE index, single CSV fetch, no dedup needed.
- Default `--start` moved to **2005-01-01** (full 20 years of daily history).
- Each ticker fetched on `.NS` first, falls back to `.BO` if NSE returns nothing → genuine "both NSE and BSE" coverage without duplicate dual-listings.
- New `--incremental` flag: only fetches bars after each CSV's last date (re-pulls last 7 days for late-adjustment safety). Daily cron-friendly: ~2 min instead of ~20.
- Two benchmarks now loaded: `NIFTY50` (^NSEI) and `SENSEX` (^BSESN).
- `examples/run_daily.sh` updated to use `--incremental` for daily runs.

### Download results (2026-04-26 morning)
- Universe assembled: 750 NSE Total Market stocks + 15 BSE-only candidates + 2 benchmarks = 767 input
- Successfully fetched: 752 via NSE, 8 via BSE fallback, 5 empty (newly-listed names without enough history)
- Total CSVs: **763** | RELIANCE/TCS/INFY = 5260 rows each (full 21 years) | 360ONE = 1632 rows (listed 2019)

### Two new models trained on 750-stock universe

| Model | Train window | Test window | Rank IC | Sharpe (post-cost) | Excess vs NIFTY50 | MDD |
|---|---|---|---|---|---|---|
| `nse_baseline_750_matched` | 2020-06 → 2023-12 (3.5y) | 2025-2026 | +0.005 | +0.155 | **+1.70%** | -34% |
| `nse_baseline_750_long` ⭐ | 2008-01 → 2022-12 (15y) | 2024-2026 | +0.066 | **+1.465** | **+31.6%** | **-25%** |

### Key finding: more history saved the bigger universe

Adding microcap names alone (matched-window) **hurt performance** — from +4.3% to +1.7% excess. Reason: microcaps add cross-sectional noise without enough liquidity to actually trade.

But with **15 years of training data** (2008-2022), the model learned more robust patterns and the 750-universe long-window model is the best-performing stack we've trained: **+31.6% excess return, Sharpe 1.46 post-cost, MDD -25%**.

⚠ Same caveats apply to this number as the original +21%:
- Survivorship bias likely inflates by 5-10% (today's NIFTY Total Market constituents only)
- Test window (2024-2026) was a strong Indian bull-market period
- Microcap "tradeable" assumption is generous
- Real-money expectation: probably **+10-15% excess** post all corrections, vs the **+4-5%** of the older 500-stock matched model

Both numbers beat NIFTY 50 buy-and-hold. The long-window model is now the production default in `run_daily.sh`.

### Production model now: `outputs/nse_baseline_750_long/`

Edit `examples/run_daily.sh` if you want to point at a different one. Today's decision (2026-04-24) is regenerated using the new model and saved at `outputs/decisions/2026-04-24.{json,txt}` — top picks now include SCI (₹374Cr turnover), TRITURBINE (₹269Cr), COFORGE (₹414Cr), AVANTIFEED, KPITTECH, MPHASIS, OLAELEC. All meaningfully liquid.

### What's still NOT done

Same list as before — still no Kite executor (deliberate), still no FinBERT sentiment (defer), still no live IC dashboard. Just more data and a better model on top of the same plumbing.
