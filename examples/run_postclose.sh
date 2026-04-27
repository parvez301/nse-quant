#!/bin/bash
# Post-close runner — schedule at 16:00 IST (Mon–Fri), after NSE closes at 15:30.
#
# This is the second daily cron entry. The 08:00 IST `run_daily.sh` cron sees
# a stale Kite quote (last_price == previous close, market not yet open at
# 09:15 IST), which makes Tier 3's live IC reading trivial. Firing this script
# at 16:00 IST captures the actual intraday move and produces the useful T+0
# IC signal we need for early decay detection.
#
# Install via:
#   crontab -e
#   0 16 * * 1-5 cd <path-to-repo> && ./examples/run_postclose.sh

set -uo pipefail

cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-./.venv/bin/python}"
LOG="outputs/daily.log"

mkdir -p outputs

TS=$(date +"%Y-%m-%d %H:%M:%S")
echo "[$TS] post-close run start" | tee -a "$LOG"

# Tier 3: T+0 live IC snapshot. Skips silently if Kite isn't configured.
"$PYTHON" examples/nse_live_ic.py --skip-if-missing 2>&1 | tee -a "$LOG" | grep -E "^\[live-ic\]" || true

# Tier 4: re-probe the token while we're here, in case it expired since the
# 08:00 cron — useful when the operator forgets to re-login until end of day.
"$PYTHON" examples/nse_kite_check.py --skip-if-missing >/dev/null 2>&1
kiteRc=$?
if [ "$kiteRc" -eq 2 ]; then
    "$PYTHON" examples/nse_safety.py notify \
        "Kite token rejected during post-close run — visit /kite-login" || true
fi

TS_END=$(date +"%Y-%m-%d %H:%M:%S")
echo "[$TS_END] post-close run done" | tee -a "$LOG"
