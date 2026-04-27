#!/bin/bash
# Cloud entrypoint: pull state from S3, run the daily pipeline, push state back.
# Wraps examples/run_daily.sh — no logic duplication. Required env vars:
#   STATE_BUCKET           S3 bucket holding qlib data + outputs
#   SNS_TOPIC_ARN          SNS topic for notifications (optional, soft-fail if unset)
#   AWS_REGION             defaulted by Fargate task

set -uo pipefail

cd /app

export PYTHON=/usr/local/bin/python
stateBucket="${STATE_BUCKET:?STATE_BUCKET must be set}"
runStartedAt=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
echo "[cloud] run_started_at=$runStartedAt bucket=$stateBucket"

mkdir -p data/qlib_data outputs/decisions

echo "[cloud] sync s3://$stateBucket/data/qlib_data -> data/qlib_data"
aws s3 sync "s3://$stateBucket/data/qlib_data" data/qlib_data --no-progress

echo "[cloud] sync s3://$stateBucket/outputs -> outputs"
aws s3 sync "s3://$stateBucket/outputs" outputs --no-progress

# First-run seed: if S3 had no model dir or pit_universe, copy from baked-in image.
if [ ! -f outputs/nse_baseline_750_long/model.pkl ]; then
    echo "[cloud] seeding model dir from image"
    cp -r /app/model_seed/nse_baseline_750_long outputs/
fi
if [ ! -f outputs/pit_universe.parquet ]; then
    echo "[cloud] seeding pit_universe.parquet from image"
    cp /app/model_seed/pit_universe.parquet outputs/
fi

# Run the existing daily script. It already handles HALT, refresh, decision, mark, P&L.
exitCode=0
./examples/run_daily.sh || exitCode=$?
echo "[cloud] run_daily.sh exit=$exitCode"

echo "[cloud] sync data/qlib_data -> s3://$stateBucket/data/qlib_data"
aws s3 sync data/qlib_data "s3://$stateBucket/data/qlib_data" --no-progress --delete

echo "[cloud] sync outputs -> s3://$stateBucket/outputs"
aws s3 sync outputs "s3://$stateBucket/outputs" --no-progress

# Write a heartbeat object the UI uses to show "last run" without scanning.
todayDate=$(date -u +"%Y-%m-%d")
runFinishedAt=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
cat > /tmp/last_run.json <<EOF
{"started_at":"$runStartedAt","finished_at":"$runFinishedAt","exit_code":$exitCode,"date":"$todayDate"}
EOF
aws s3 cp /tmp/last_run.json "s3://$stateBucket/outputs/last_run.json" --no-progress

exit $exitCode
