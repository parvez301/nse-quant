#!/bin/bash
# Cloud post-close entrypoint — fires at 10:30 UTC (16:00 IST) Mon-Fri,
# after NSE closes at 15:30 IST. Mirrors run_daily_cloud.sh but does only
# the post-close work (Tier 3 live IC + Tier 4 token re-probe), and only
# syncs the artefacts those steps touch — keeping the Fargate runtime
# under a minute.

set -uo pipefail

cd /app

export PYTHON=/usr/local/bin/python
stateBucket="${STATE_BUCKET:?STATE_BUCKET must be set}"
runStartedAt=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
echo "[postclose] run_started_at=$runStartedAt bucket=$stateBucket"

mkdir -p data/qlib_data outputs/decisions

# Pull only what Tier 3 needs: qlib data (for ref close lookups) and the
# decisions dir (to find the latest pick list). Skipping the full outputs
# sync keeps this run cheap (under 30s vs ~3 min for the full daily sync).
echo "[postclose] sync qlib_data + decisions from S3"
aws s3 sync "s3://$stateBucket/data/qlib_data" data/qlib_data --no-progress
aws s3 sync "s3://$stateBucket/outputs/decisions" outputs/decisions --no-progress

# Pull the existing live_ic.csv so we append rather than overwrite
aws s3 cp "s3://$stateBucket/outputs/live_ic.csv" outputs/live_ic.csv \
    --no-progress 2>/dev/null || true

exitCode=0
./examples/run_postclose.sh || exitCode=$?
echo "[postclose] run_postclose.sh exit=$exitCode"

# Push only the artefacts this run touched. Avoid `sync outputs ...` which
# would race with the morning cron's writes.
if [ -f outputs/live_ic.csv ]; then
    aws s3 cp outputs/live_ic.csv "s3://$stateBucket/outputs/live_ic.csv" --no-progress
fi
if [ -f outputs/alerts.log ]; then
    aws s3 cp outputs/alerts.log "s3://$stateBucket/outputs/alerts.log" --no-progress
fi

exit $exitCode
