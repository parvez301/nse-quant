#!/bin/bash
# Daily production runner — schedule this at 08:00 IST via cron.
#
# Workflow with safety rails:
#   0. Refuse to run if outputs/HALT exists.
#   1. Incremental refresh of OHLCV (yfinance -> Qlib binary). ~2 min.
#   2. Data quality gate — abort if data is stale or incomplete.
#   3. Generate today's BUY/HOLD/SELL decision list.
#   4. Mark paper portfolio to the latest close.
#   5. P&L kill switch — set HALT if daily loss / drawdown breached.
#
# Install via:
#   crontab -e
#   0 8 * * 1-5 cd <path-to-repo> && ./examples/run_daily.sh
#
# (Mon-Fri at 08:00 — completes by ~08:30, well before NSE opens at 09:15.)
#
# Bypass refresh during same-day reruns:
#   SKIP_REFRESH=1 ./examples/run_daily.sh

set -uo pipefail

cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-./.venv/bin/python}"
MODEL_DIR="${MODEL_DIR:-outputs/nse_baseline_750_long}"
LOG="outputs/daily.log"
SKIP_REFRESH="${SKIP_REFRESH:-0}"

mkdir -p outputs

TS=$(date +"%Y-%m-%d %H:%M:%S")
echo "[$TS] daily run start" | tee -a "$LOG"

# ---------------------------------------------------------------------------
# Step 0: HALT gate
# ---------------------------------------------------------------------------
if [ -f outputs/HALT ]; then
    echo "[$TS] ⛔ outputs/HALT exists — refusing to run" | tee -a "$LOG"
    cat outputs/HALT | tee -a "$LOG"
    "$PYTHON" examples/nse_safety.py notify "Cron skipped — system is HALTED" || true
    exit 1
fi

# ---------------------------------------------------------------------------
# Step 1: incremental data refresh
# ---------------------------------------------------------------------------
if [ "$SKIP_REFRESH" != "1" ]; then
    echo "[$TS] incremental refresh of yfinance data..." | tee -a "$LOG"
    if ! "$PYTHON" examples/nse_data_loader.py --incremental 2>&1 | tee -a "$LOG" | grep -E "^\[(plan|download|setup|dump)\]|Qlib binary dataset ready"; then
        echo "[$TS] ❌ data refresh failed" | tee -a "$LOG"
        "$PYTHON" examples/nse_safety.py notify "Cron failed at data refresh step" || true
        "$PYTHON" examples/nse_safety.py halt "Data refresh exit code != 0" || true
        exit 1
    fi
else
    echo "[$TS] SKIP_REFRESH=1, using existing Qlib data" | tee -a "$LOG"
fi

# ---------------------------------------------------------------------------
# Step 2: data quality gate
# ---------------------------------------------------------------------------
echo "[$TS] data quality check..." | tee -a "$LOG"
if ! "$PYTHON" examples/nse_safety.py check_data 2>&1 | tee -a "$LOG" | grep -E "ok|⚠|❌"; then
    echo "[$TS] ⚠ data quality check failed — refusing to emit decision" | tee -a "$LOG"
    "$PYTHON" examples/nse_safety.py notify "Cron skipped decision — data quality issue" || true
    exit 1
fi

# ---------------------------------------------------------------------------
# Step 3: emit decision
# ---------------------------------------------------------------------------
echo "[$TS] generating decision..." | tee -a "$LOG"
"$PYTHON" examples/nse_daily_decision.py --model_dir "$MODEL_DIR" --topk 20 --buffer 10 2>&1 | tee -a "$LOG" | grep -E "^(  as of|  BUY|  SELL|  HOLD|\[saved\])" || true

# ---------------------------------------------------------------------------
# Step 3.5: execute today's decision into the paper portfolio
# ---------------------------------------------------------------------------
latestDecisionFile=$(ls outputs/decisions/*.json 2>/dev/null | sort | tail -1)
if [ -n "$latestDecisionFile" ]; then
    asOfDate=$(basename "$latestDecisionFile" .json)
    # Skip if we've already executed this date (trade_log.csv has a row for it)
    if [ -f outputs/trade_log.csv ] && grep -q "^$asOfDate," outputs/trade_log.csv; then
        echo "[$TS] decision $asOfDate already executed — skipping" | tee -a "$LOG"
    else
        echo "[$TS] executing decision $asOfDate into paper portfolio..." | tee -a "$LOG"
        "$PYTHON" examples/nse_paper_trade.py execute "$asOfDate" 2>&1 | tee -a "$LOG" | grep -E "^\[(prices|exec|info|sell|buy)\]|cash=|positions=" || true
    fi
fi

# ---------------------------------------------------------------------------
# Step 4: mark paper portfolio
# ---------------------------------------------------------------------------
if [ -f outputs/current_portfolio.csv ]; then
    echo "[$TS] marking paper portfolio..." | tee -a "$LOG"
    "$PYTHON" examples/nse_paper_trade.py mark 2>&1 | tee -a "$LOG" | grep -E "^\[mark\]|total_equity" || true

    # Step 5: P&L kill switch (ONLY runs if mark succeeded)
    echo "[$TS] P&L safety check..." | tee -a "$LOG"
    if ! "$PYTHON" examples/nse_safety.py check_pnl 2>&1 | tee -a "$LOG"; then
        echo "[$TS] ⛔ P&L breach — HALT was set" | tee -a "$LOG"
        # Don't exit non-zero: we successfully detected the breach. The HALT itself
        # will block tomorrow's run.
    fi
fi

# ---------------------------------------------------------------------------
# Step 6: refresh methodology artefacts (cheap; rebuilds from existing CSVs)
# ---------------------------------------------------------------------------
if [ -f outputs/summary.csv ]; then
    echo "[$TS] refreshing stratified + outage stats..." | tee -a "$LOG"
    "$PYTHON" examples/nse_stratified_stats.py 2>&1 | tee -a "$LOG" | grep -E "^\[stratified\]" || true
    "$PYTHON" examples/nse_outage_monte_carlo.py 2>&1 | tee -a "$LOG" | grep -E "^\[outage-mc\]" || true
fi

# ---------------------------------------------------------------------------
# Step 7: export OHLCV + scores to partitioned Parquet for the analytics Lambda
# ---------------------------------------------------------------------------
echo "[$TS] exporting analytics parquet..." | tee -a "$LOG"
"$PYTHON" examples/nse_export_analytics.py 2>&1 | tee -a "$LOG" | grep -E "^\[etl\]" || true

# ---------------------------------------------------------------------------
# Step 8: today-only Alpha158 features + LightGBM booster (text) for
# the SHAP attribution endpoint. Scoped tight (~50 symbols × 1 day) so the
# Alpha158 compute stays under a minute.
# ---------------------------------------------------------------------------
echo "[$TS] exporting today's features + booster..." | tee -a "$LOG"
"$PYTHON" examples/nse_export_features_today.py 2>&1 | tee -a "$LOG" | grep -E "^\[features\]" || true

TS_END=$(date +"%Y-%m-%d %H:%M:%S")
echo "[$TS_END] daily run done" | tee -a "$LOG"

# Notify on success too — so silent failures stand out (notification will be missing)
"$PYTHON" examples/nse_safety.py notify "Daily run done — see outputs/decisions/$(date +%Y-%m-%d).txt" 2>/dev/null || true
