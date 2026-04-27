"""Dead-man's-switch — fires daily after the cron should have finished.

If outputs/last_run.json is older than ~2 hours (i.e. today's cron didn't run
or didn't get to write its heartbeat), publish to SNS so we hear about it.

Triggered by EventBridge at 04:00 UTC Mon-Fri (= 09:30 IST), ~90 min after
the daily cron's expected finish at 02:45 UTC.
"""

import datetime
import json
import os

import boto3


STATE_BUCKET = os.environ["STATE_BUCKET"]
SNS_TOPIC_ARN = os.environ["SNS_TOPIC_ARN"]
STALE_AFTER_MINUTES = int(os.environ.get("STALE_AFTER_MINUTES", "120"))


def _alert(subject: str, message: str) -> None:
    boto3.client("sns").publish(
        TopicArn=SNS_TOPIC_ARN, Subject=subject[:99], Message=message
    )


def handler(event, context):
    s3 = boto3.client("s3")
    nowUtc = datetime.datetime.now(datetime.timezone.utc)

    try:
        obj = s3.get_object(Bucket=STATE_BUCKET, Key="outputs/last_run.json")
    except s3.exceptions.NoSuchKey:
        _alert(
            "[NSE] DEAD MAN: no last_run.json in state bucket",
            "The state bucket has never seen a successful cron heartbeat.",
        )
        return {"alerted": True, "reason": "no_last_run"}

    data = json.loads(obj["Body"].read())
    finishedAtRaw = data.get("finished_at")
    if not finishedAtRaw:
        _alert(
            "[NSE] DEAD MAN: last_run.json missing finished_at",
            f"Contents: {data}",
        )
        return {"alerted": True, "reason": "no_finished_at"}

    finishedAt = datetime.datetime.fromisoformat(finishedAtRaw.replace("Z", "+00:00"))
    ageMinutes = (nowUtc - finishedAt).total_seconds() / 60

    if ageMinutes > STALE_AFTER_MINUTES:
        _alert(
            f"[NSE] DEAD MAN: cron stale by {int(ageMinutes)} min",
            (
                f"Last successful cron heartbeat: {finishedAtRaw}\n"
                f"Now (UTC): {nowUtc.isoformat()}\n"
                f"Age: {ageMinutes:.0f} minutes (threshold: {STALE_AFTER_MINUTES})\n"
                f"Exit code of last run: {data.get('exit_code')}\n\n"
                f"Check ECS task logs in CloudWatch group NseQuantStack-CronLogs*."
            ),
        )
        return {"alerted": True, "reason": "stale", "age_minutes": ageMinutes}

    if data.get("exit_code", 0) != 0:
        _alert(
            f"[NSE] cron last run exited {data['exit_code']}",
            f"Heartbeat at {finishedAtRaw} succeeded in writing, but exit code is non-zero.\nFull payload: {data}",
        )
        return {"alerted": True, "reason": "nonzero_exit"}

    return {"alerted": False, "age_minutes": ageMinutes}
