#!/bin/bash
# Cloud entrypoint for the 4-hourly clean-26 options tracker.
# Syncs the F&O archive + qlib store down, fetches any new NSE bhavcopy
# days incrementally, recomputes the tracker JSON, and pushes state back.
set -uo pipefail
cd /app

export PYTHON=/usr/local/bin/python
stateBucket="${STATE_BUCKET:?STATE_BUCKET must be set}"
echo "[tracker] started $(date -u +%FT%TZ) bucket=$stateBucket"

mkdir -p data/fo_bhavcopy data/qlib_data outputs/options

aws s3 sync "s3://$stateBucket/data/qlib_data" data/qlib_data --no-progress --only-show-errors
aws s3 sync "s3://$stateBucket/data/fo_bhavcopy" data/fo_bhavcopy --no-progress --only-show-errors

# Incremental: fetch the last ~10 calendar days; cached days cost nothing.
fetchStart=$($PYTHON - <<'PY'
import datetime; print((datetime.date.today() - datetime.timedelta(days=10)).isoformat())
PY
)
$PYTHON examples/nse_options_fetch.py --start "$fetchStart" --end "$(date +%F)" || true

exitCode=0
$PYTHON examples/nse_options_clean_tracker.py || exitCode=$?
echo "[tracker] tracker exit=$exitCode"

aws s3 sync data/fo_bhavcopy "s3://$stateBucket/data/fo_bhavcopy" --no-progress --only-show-errors
aws s3 cp outputs/options/clean_tracker.json "s3://$stateBucket/outputs/options/clean_tracker.json" --only-show-errors || exitCode=$?

echo "[tracker] done exit=$exitCode"
exit $exitCode
