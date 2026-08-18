# DSRD Phase 1 — The Backtest Judge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Walk-forward backtest of the DSRD short-strangle strategy over the Phase 0 archive, judged against the spec's pre-registered pass criteria (§7), producing `outputs/options/judge/{headline.json,report.md}`.

**Architecture:** Pure-logic modules (`sigma`, `strikes`, `filters`, `score`, `costs`, `margin`, `underlying`) feed a monthly-cycle engine (`backtest.py`) that iterates expiry-to-expiry cycles derived from the data itself. Stop-loss grid tunes on 2019–2022 cycles; the verdict comes only from 2023→present. Runner script assembles the report and exits nonzero when the judge FAILS.

**Tech Stack:** Python stdlib + numpy (qlib binary reads) + yfinance (NIFTY benchmark only). No pandas in the engine.

**Spec:** `docs/superpowers/specs/2026-08-18-dsrd-options-design.md` — with one amendment locked here: **judge capital is ₹5,00,000** (₹1,00,000 cannot margin a single stock strangle; the runner reports ₹1L infeasibility as finding #0).

## Global Constraints

- Descriptive variable names; canonical row schema from the Phase 0 plan.
- **Never use qlib closes as rupee-level spot** (they are back-adjusted, factor files are all 1.0). Spot = `underlying_close` (UDiFF era) else near-month FUT settle from the same day's archive rows. qlib adjusted closes feed only scale-invariant indicators (RSI, HV).
- All dates ISO strings in data structures; `datetime.date` at function boundaries.
- Tests: `.venv/bin/pytest tests/test_options_<module>.py -q`; commit per task on green.
- Strategy constants (single source: `options/config.py`): rate 0.07; delta band [0.10, 0.20] ideal 0.15; min strike distance 8%; profit target 80% of premium (exit when combined premium ≤ 0.20× entry); stop grid {1:1 → 2.0×, 1:1.5 → 2.5×, 1:2 → 3.0×, none}; max positions 3; margin budget 70% of capital; score floor 75.

---

### Task 1: `options/config.py` + `options/underlying.py` — constants, spot, RSI, HV

**Files:** Create `options/config.py`, `options/underlying.py`; Test `tests/test_options_underlying.py`

**Interfaces (Produces):**
- `config.py`: module-level constants `RISK_FREE_RATE=0.07`, `DELTA_BAND=(0.10, 0.20)`, `IDEAL_DELTA=0.15`, `MIN_STRIKE_DISTANCE=0.08`, `PROFIT_TARGET_REMAINING=0.20`, `STOP_MULTIPLIERS={"1:1": 2.0, "1:1.5": 2.5, "1:2": 3.0, "none": None}`, `MAX_POSITIONS=3`, `MARGIN_BUDGET_FRACTION=0.70`, `SCORE_FLOOR=75.0`, `JUDGE_CAPITAL=500_000.0`
- `spot_for_symbol(day_rows: list[dict]) -> float | None` — rows pre-filtered to one symbol+day; `underlying_close` of any row if set, else settle of the FUT row with the nearest expiry; None if neither.
- `class AdjustedCloseStore(qlib_root: pathlib.Path)` with `.closes_upto(symbol: str, iso_date: str) -> list[float]` — calendar-aligned qlib series (symbol lowercased, `<f4` binary, first float = calendar start index, NaNs dropped from the tail window), truncated at iso_date inclusive; `[]` when symbol file missing.
- `rsi14(closes: list[float]) -> float | None` — Wilder smoothing, None if < 15 closes.
- `historical_volatility(closes: list[float], window: int = 20) -> float | None` — annualized (√252) std of log returns over the last `window` returns; None if insufficient.

**Key test cases (write first, verify fail, implement, verify pass, commit):**
```python
def test_spot_prefers_underlying_close():   # UDiFF row wins over FUT settle
def test_spot_falls_back_to_nearest_fut():  # legacy rows: two FUTs, nearest expiry settle returned
def test_rsi14_reference():                 # 14 gains of 1 then 14 losses -> known Wilder value; all-up series -> 100
def test_rsi14_insufficient_returns_none():
def test_hv_of_constant_series_is_zero():
def test_adjusted_close_store_reads_reliance(tmp_or_real):  # against real qlib store: last close ≈ 1327.3 on 2026-08-10
```
Commit: `feat(options): spot resolution + RSI/HV indicators`

---

### Task 2: `options/sigma.py` — expected-move bands

**Files:** Create `options/sigma.py`; Test `tests/test_options_sigma.py`

**Interfaces (Produces):**
- `expected_move(spot, implied_vol, days_to_expiry) -> float` = `spot * implied_vol * sqrt(days_to_expiry / 365)`
- `sigma_bands(spot, implied_vol, days_to_expiry) -> dict` with keys `lower_1s, upper_1s, lower_2s, upper_2s`
- `classify_strangle(bands: dict, call_strike: float, put_strike: float) -> str` — `"A+"` both strikes outside 2σ, `"A"` both outside 1σ, `"B"` exactly one inside 1σ, `"reject"` both inside 1σ (spec quality filter).

Tests pin `expected_move(1000, 0.25, 365) == 250`, band symmetry, all four grades. Commit: `feat(options): sigma bands and strangle grading`

---

### Task 3: `options/strikes.py` — delta-based strangle selection

**Files:** Create `options/strikes.py`; Test `tests/test_options_strikes.py`

**Interfaces:**
- Consumes `implied_volatility`, `bs_delta` (greeks), config constants.
- Produces `select_strangle(symbol_day_rows: list[dict], spot: float, expiry: str, trading_date: datetime.date) -> dict | None`: keys `call_row, put_row, call_delta, put_delta, call_iv, put_iv, entry_premium_per_share` (= call settle + put settle). Rules per leg: candidates = rows of that kind+expiry with settle > 0, oi > 0, IV inversion succeeds, |delta| within `DELTA_BAND`, strike distance from spot ≥ `MIN_STRIKE_DISTANCE`; choose |delta| nearest `IDEAL_DELTA`; if the delta band yields nothing, fall back to the nearest-|delta|-to-0.15 candidate among those with |delta| < 0.10 and distance ≥ 8% (further OTM, never nearer); None when either leg unfillable.

Tests build a synthetic ladder (spot 1000, strikes 800–1200 step 50, premiums from `bs_price` at 30% vol, DTE 30) and assert: chosen strikes ≥ 8% away, deltas in band, symmetric selection; a ladder with no put candidates returns None; zero-OI rows are skipped. Commit: `feat(options): delta-based strangle selection`

---

### Task 4: `options/filters.py` + `options/score.py` + `data/options_blackouts.yaml`

**Files:** Create all three; Test `tests/test_options_filters.py`, `tests/test_options_score.py`

**Interfaces:**
- `rsi_regime(rsi_value: float | None) -> str` — `"bullish"` > 55, `"bearish"` < 45, else `"neutral"` (None → `"neutral"`).
- `in_earnings_window(cycle_start: datetime.date, cycle_end: datetime.date) -> bool` — True when the cycle overlaps any `[quarter_end + 7d, quarter_end + 45d]` window (quarter ends: Mar 31, Jun 30, Sep 30, Dec 31). Documented proxy: SEBI's 45-day results deadline; over-exclusion acceptable (spec §4).
- `load_blackouts(yaml_path) -> list[tuple[date, date]]`; `in_blackout(cycle_start, cycle_end, blackout_ranges) -> bool` (overlap test).
- `trade_score(liquidity_rank: float, rsi_value: float | None, call_delta: float, put_delta: float, sigma_grade: str, earnings_clear: bool) -> float` (0–100): liquidity 25 × rank(0..1); RSI 20 − 0.8×|rsi−50| floored at 0 (None → 10); delta quality per leg 12.5 − 100×||δ|−0.15| floored at 0; sigma grade A+ → 15, A → 10, B → 5, reject → 0; earnings clear → 15 else 0.
- `data/options_blackouts.yaml`: Budget days (2019-02-01, 2019-07-05, then each Feb 1 2020–2026) as 3-day ranges, general elections 2019-04-11→2019-05-23 and 2024-04-19→2024-06-04.

Tests: regime boundaries (55.1 bullish, 45.0 neutral); earnings window overlap true for a cycle spanning mid-April, false for one inside Feb 15–Mar 31; blackout hit for a cycle covering 2024-05-02; score: perfect inputs → 100, reject-grade sigma in-window → ≤ 45. Commit: `feat(options): entry filters, blackout calendar, trade scoring`

---

### Task 5: `options/costs.py` + `options/margin.py`

**Files:** Create both; Test `tests/test_options_costs.py`

**Interfaces:**
- `leg_transaction_costs(premium_value: float, is_sell: bool, stressed: bool, premium_per_share: float, lot_size: int) -> dict` itemized: brokerage flat 20.0; stt = 0.001 × premium_value on sells only; exchange = 0.00053 × premium_value; gst = 0.18 × (brokerage + exchange); sebi = premium_value × 10 / 1e7; stamp = 0.00003 × premium_value on buys only; slippage = `max(0.05, 0.015 × premium_per_share) × lot_size`, ×2 when `stressed`. Plus key `total`.
- `strangle_entry_costs(call_value, put_value, call_per_share, put_per_share, lot_size) -> float` (two sell legs, not stressed); `strangle_exit_costs(..., stressed: bool) -> float` (two buy legs).
- `strangle_margin(spot: float, call_strike: float, put_strike: float, lot_size: int) -> float` — per leg `lot_size × max(0.20 × spot − otm_amount, 0.10 × spot)`; strangle = max(call_leg, put_leg) + 0.05 × spot × lot_size (second-leg exposure add-on). Documented SPAN proxy per spec §6.
- `lot_size_estimate(known_lot: int | None, spot: float) -> int` — known value passes through; else `max(1, round(750_000 / spot / 25) × 25)` (₹7.5L notional heuristic for the legacy era).

Tests pin an exact itemized breakdown for a ₹10,000 premium leg (hand-computed in the test), assert stressed slippage doubles, margin for spot 1000 / strikes 1100/900 / lot 500 = `max(500×(200−100), 500×(200−100)) + 25_000 = 75_000`, and lot heuristic returns 750 for spot 1000. Commit: `feat(options): retail cost model and SPAN-proxy margin`

---

### Task 6: `options/backtest.py` — the walk-forward engine

**Files:** Create `options/backtest.py`; Test `tests/test_options_backtest.py`

**Interfaces:**
- `monthly_expiry_dates(archive_root, start_date, end_date) -> list[str]` — distinct expiry dates shared by ≥ 50 symbols across the archive (data-derived; robust to NSE's expiry-day changes), sorted.
- `build_cycles(expiry_dates, archive_trading_days) -> list[dict]` — per consecutive expiry pair: `entry_date` = first Friday strictly after previous expiry that has an archive file (fallback: first trading day after that Friday), `deadline_date` = last Tuesday before expiry with a file (fallback: last file day before expiry), `expiry`.
- `class StranglePosition` — symbol, entry data (rows, premium/share, lot, margin, score, grade), `mark(day_rows) -> None` (carry-forward on missing legs), `check_exit(stop_multiplier) -> str | None` returning `"target"|"stop"|None`.
- `run_cycle(cycle, archive_root, close_store, capital_state, options_config) -> list[dict]` — trade log rows: entry/exit dates+prices, premium collected, costs, margin, P&L, exit reason, grade, score, breach flag (spot beyond ±10% strikes at any mark).
- `run_backtest(archive_root, qlib_root, start_date, end_date, stop_key: str, use_earnings_filter: bool, capital: float) -> dict` — `{"trades": [...], "monthly_returns": {...}, "equity_curve": [(iso_date, equity)], "config": {...}}`. Candidate ranking per entry day: score desc; admit while margin used ≤ 70% × capital and open positions < 3. P&L accounting: short premium collected at entry settle − entry costs; exit at day settle (stop exits stressed) − exit costs; equity = capital + realized + Σ(entry_premium − current_premium) × lot.
- `summary_stats(monthly_returns: dict, equity_curve) -> dict` — CAGR, total return, max drawdown, win rate, mean monthly return, Sharpe (monthly × √12, rf 7%/12), Sortino, profit factor, t-stat of mean monthly excess vs FD.

**Engine test (synthetic, hand-computable):** build a 2-symbol, 2-cycle synthetic archive via the Task-pattern `_zip_bytes`/`fetch_day` fixture writer where symbol A stays flat (both cycles collect full premium via target/time exit — P&L positive and exactly computable) and symbol B gaps 15% through its call strike in cycle 2 (stop fires at 2.0×, stressed exit costs applied, breach flag set). Assert trade log P&L to the rupee, equity curve monotonicity in cycle 1, and stop-exit accounting in cycle 2. Also unit-test `monthly_expiry_dates` and `build_cycles` on fixtures. Commit: `feat(options): walk-forward strangle backtest engine`

---

### Task 7: `examples/nse_options_backtest.py` — tuning, judgment, report

**Files:** Create `examples/nse_options_backtest.py`; Test `tests/test_options_judge_report.py` (report assembly only, engine mocked)

**Interfaces:**
- `run_judgment(archive_root, qlib_root, output_dir) -> dict`:
  1. Tuning: `run_backtest` per stop variant on 2019-01-01→2022-12-31, both earnings-filter variants; select stop by Sharpe (earnings filter per spec default ON for the headline, both reported).
  2. Judged window 2023-01-01→present with the selected stop.
  3. Benchmarks: NIFTY buy-and-hold monthly returns via yfinance `^NSEI` (cached to `outputs/options/nsei_monthly.json`; if download fails, read cache; if neither, mark criterion 2 `"unavailable"` — never fabricate); FD = 7%/12 monthly.
  4. Criteria §7: (1) judged CAGR > 0.07, (2) judged Sharpe ≥ NIFTY Sharpe same window, (3) max DD < 30%, (4) March-2020 cycle from the TUNING run: equity floor of Feb–Apr 2020 > 60% of starting capital (reported alongside, window predates judgment by construction), (5) monthly excess t-stat > 2 on judged window. PASS = all five.
  5. Finding #0: margin of the median judged trade vs ₹1,00,000 — states whether ₹1L supports even one strangle.
  6. Writes `outputs/options/judge/headline.json` (criteria, verdict, stats per window/variant, config) + `report.md` (tables: per-year returns, top/bottom symbols, breach frequency, with/without RSI+earnings variants) + `equity_judged.csv`, `trades_judged.csv`.
- CLI: `--archive-root`, `--qlib-root`, `--out`, `--quick` (single stop variant, for smoke).
- Exit code 0 on PASS, 1 on FAIL (both are valid outcomes; FAIL stops the project per spec).

Commit: `feat(options): the judge — tuning, criteria, report`

---

### Task 8: Full run + verdict

- [ ] Smoke: `--quick` on 2024-01→2024-06 (fast, catches integration errors).
- [ ] Full run in background (`run_in_background`, expect 10–40 min), monitor.
- [ ] Read `headline.json`; sanity-check against report tables (no criterion computed from empty trade lists — a judged window with < 12 monthly observations is an ERROR, not a PASS).
- [ ] Commit `outputs/options/judge/headline.json` + `report.md` (`git add -f`): `chore(options): Phase 1 judge verdict — <PASS|FAIL>`.
- [ ] Report verdict to user with the spec's contingency: FAIL → stop; PASS → Phase 2 proposal.

## Self-review notes

- Spec §7 criteria all mapped (Task 7 step 4); §6 rules split across Tasks 3/4/5/6; §4 earnings proxy in Task 4; reporting extras (breach freq, per-stock, variants) in Task 7's report.md.
- Deviation ledger (all surfaced to user): judge capital ₹5L; March-2020 criterion measured on the tuning run (2020 predates the judged window by design — the spec's §7.4 wording anticipated this); earnings filter is the global quarter-window proxy, not per-stock dates.
- Type consistency: canonical rows flow unchanged from Phase 0; `select_strangle` output keys consumed verbatim by `StranglePosition`; config constants imported, never re-declared.
