"""Kite token expiry monitor — alerts before the 08:00 IST decision cron.

Kite Connect access tokens expire daily at 06:00 IST and CANNOT be
programmatically refreshed (Zerodha requires a fresh OAuth + 2FA login).
The best we can do is page the operator early enough to log in before
the morning decision cron at 08:00 IST and the post-close cron at
16:00 IST need the token.

As of 2026-07-20 this is the *verifier* rather than the only line of defence:
KiteAutoLogin runs 15 min earlier (06:15 IST) and mints the token unattended.
This monitor still runs so an auto-login failure degrades to the manual flow
instead of a silent no-token day. See docs/kite_auto_login.md.

Triggered by EventBridge at 01:00 UTC (= 06:30 IST) Mon-Fri. Alerts if:
  * the token has already expired, OR
  * the token will expire within 90 minutes (i.e. before 08:00 IST cron).
"""

import datetime
import json
import os

import boto3


KITE_SECRET_NAME = os.environ["KITE_SECRET_NAME"]
SNS_TOPIC_ARN = os.environ["SNS_TOPIC_ARN"]
KITE_LOGIN_URL = os.environ.get("KITE_LOGIN_URL", "/kite-login on the dashboard")
WARN_MINUTES = int(os.environ.get("WARN_MINUTES", "90"))

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


def _alert(subject: str, message: str) -> None:
    boto3.client("sns").publish(
        TopicArn=SNS_TOPIC_ARN, Subject=subject[:99], Message=message
    )


def _parse_ist(s: str) -> datetime.datetime | None:
    """Accepts 'YYYY-MM-DD HH:MM IST' or ISO-8601 with offset."""
    s = s.strip()
    try:
        if s.endswith(" IST"):
            return datetime.datetime.strptime(s[:-4].strip(), "%Y-%m-%d %H:%M").replace(tzinfo=IST)
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(IST)
    except ValueError:
        return None


def handler(event, context):
    sm = boto3.client("secretsmanager")
    try:
        raw = sm.get_secret_value(SecretId=KITE_SECRET_NAME)["SecretString"]
        secret = json.loads(raw)
    except Exception as e:
        _alert(
            "[NSE] Kite token monitor: secret read failed",
            f"Couldn't read {KITE_SECRET_NAME}: {e}",
        )
        return {"alerted": True, "reason": "read_failed", "error": str(e)}

    expiresAtRaw = secret.get("access_token_expires_at_ist")
    if not expiresAtRaw:
        _alert(
            "[NSE] Kite token: no expiry recorded",
            (
                f"Secret {KITE_SECRET_NAME} has no access_token_expires_at_ist field. "
                f"This usually means the token has never been minted via OAuth callback.\n\n"
                f"Re-login at: {KITE_LOGIN_URL}"
            ),
        )
        return {"alerted": True, "reason": "no_expiry"}

    expiresAt = _parse_ist(expiresAtRaw)
    if expiresAt is None:
        _alert(
            "[NSE] Kite token: malformed expiry field",
            f"access_token_expires_at_ist = {expiresAtRaw!r} could not be parsed.",
        )
        return {"alerted": True, "reason": "parse_failed", "raw": expiresAtRaw}

    nowIst = datetime.datetime.now(IST)
    minutesUntilExpiry = (expiresAt - nowIst).total_seconds() / 60

    if minutesUntilExpiry < 0:
        _alert(
            "[NSE] Kite token EXPIRED — re-login before 08:00 IST cron",
            (
                f"Token expired at: {expiresAt.isoformat()}\n"
                f"Now (IST):        {nowIst.isoformat()}\n"
                f"Overdue by:       {int(-minutesUntilExpiry)} minutes\n\n"
                f"Until you re-login, the post-close live-IC step will silently skip "
                f"(0 IC samples accumulate). The 90-day paper-trade clock keeps "
                f"counting, but you lose evidence quality each day.\n\n"
                f"Re-login at: {KITE_LOGIN_URL}\n\n"
                f"Takes ~60 seconds (Zerodha OAuth + 2FA)."
            ),
        )
        return {
            "alerted": True,
            "reason": "expired",
            "minutes_overdue": int(-minutesUntilExpiry),
        }

    if minutesUntilExpiry < WARN_MINUTES:
        _alert(
            f"[NSE] Kite token expiring in {int(minutesUntilExpiry)} min",
            (
                f"Token expires at: {expiresAt.isoformat()}\n"
                f"Now (IST):        {nowIst.isoformat()}\n"
                f"Time left:        {int(minutesUntilExpiry)} minutes\n\n"
                f"Re-login at: {KITE_LOGIN_URL}"
            ),
        )
        return {
            "alerted": True,
            "reason": "expiring_soon",
            "minutes_until_expiry": int(minutesUntilExpiry),
        }

    return {
        "alerted": False,
        "minutes_until_expiry": int(minutesUntilExpiry),
        "expires_at": expiresAt.isoformat(),
    }
