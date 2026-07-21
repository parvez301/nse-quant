# Kite auto-login

Mints the daily Kite Connect `access_token` without human touch, replacing the
manual `/kite-login` tap at <https://trade.example.com/kite-login>.

## Read this before enabling

Automated login is **not permitted** by the Kite Connect terms of service. SEBI
requires the second authentication factor be supplied by a human per session,
which is why Zerodha ships no refresh-token flow for personal API subscriptions.

The realistic downside is Zerodha revoking the API subscription — which would
take the daily decision cron, live-IC sampling, and intraday MTM down with it.
This was deployed as a deliberate operator trade-off against ~10 seconds/day of
manual login. If that trade stops looking good, see **Disabling** below.

## How it works

Drives Zerodha's own web-login endpoints, same sequence a browser performs:

| Step | Call | Yields |
|---|---|---|
| 1 | `POST kite.zerodha.com/api/login` `{user_id, password}` | `request_id` |
| 2 | `POST kite.zerodha.com/api/twofa` `{request_id, twofa_value}` | session cookies |
| 3 | `GET  kite.zerodha.com/connect/login?api_key=..&v=3` | 302 chain → `request_token` |
| 4 | `POST api.kite.trade/session/token` `{api_key, request_token, checksum}` | `access_token` |

The TOTP in step 2 is computed locally (RFC 6238, SHA1, 6 digits, 30s step) from
the same External-TOTP seed enrolled in Google Authenticator — the phone and the
Lambda derive identical codes from identical seeds.

Step 3 stops **at** the hop carrying `request_token` rather than following it.
Following it would hit the dashboard's `/kite-callback`, which exchanges the
token itself — and `request_token` is single-use, so our own exchange would then
fail. `tests/test_kite_auto_login.py` pins this behaviour.

Everything is stdlib (`urllib` + `hmac`). No Docker bundling, no `pyotp`.

## Schedule and the safety net

```
06:00 IST   Zerodha invalidates yesterday's token
06:15 IST   KiteAutoLogin        <- mints the new token       (cron 45 0 UTC)
06:30 IST   KiteTokenMonitor     <- verifies, pages on failure (cron  0 1 UTC)
08:00 IST   Decision cron        <- needs a valid token
```

Auto-login is deliberately *not* the only path. `KiteTokenMonitor` still runs 15
minutes later and pages via SNS if no valid token exists, leaving 90 minutes of
runway to log in manually. A broken auto-login degrades to the old manual flow —
it cannot silently cost a trading day.

`KiteAutoLogin` also publishes its own SNS alert on every failure path (secret
unreadable, credentials incomplete, password rejected, TOTP rejected, redirect
chain dead-ended), each carrying the manual login link.

## Populating the secret

Auto-login needs three fields beyond what the manual flow used. Absent any of
them the function alerts and no-ops rather than half-working.

| Field | Source |
|---|---|
| `kite_user_id` | Zerodha client ID, e.g. `AB1234` |
| `kite_password` | Kite **login** password (not the PIN) |
| `totp_secret` | External TOTP seed — Kite → Settings → Password & Security → External TOTP |

Merge them into the existing secret without clobbering `api_key` / `api_secret`:

```bash
unset AWS_DEFAULT_PROFILE && export AWS_PROFILE=myprofile
export AWS_REGION=ap-south-1

# Read current, merge new fields, write back. Never hand-retype api_secret.
aws secretsmanager get-secret-value --secret-id nse-quant/kite \
  --query SecretString --output text > /tmp/kite.json

python3 - <<'PY'
import json, getpass
secret = json.load(open("/tmp/kite.json"))
secret["kite_user_id"] = input("Zerodha client ID: ").strip()
secret["kite_password"] = getpass.getpass("Kite login password: ")
secret["totp_secret"] = getpass.getpass("External TOTP seed: ").replace(" ", "")
json.dump(secret, open("/tmp/kite.json", "w"))
PY

aws secretsmanager put-secret-value --secret-id nse-quant/kite \
  --secret-string file:///tmp/kite.json

shred -u /tmp/kite.json 2>/dev/null || rm -P /tmp/kite.json
```

The Lambda preserves every pre-existing field when it writes the token back, so
credentials survive each daily run. `tests/test_kite_auto_login.py` asserts this.

## First run

The redirect chain only yields a `request_token` once the app is authorised for
the account. If it has never been authorised, step 3 dead-ends on a consent
screen and the function alerts with `no request_token`. Fix by logging in
manually **once** at `/kite-login` and approving; automated runs work after.

Verify without waiting for the cron:

```bash
aws lambda invoke --function-name <KiteAutoLogin fn name> \
  --cli-binary-format raw-in-base64-out --payload '{}' /dev/stdout
```

Expect `{"ok": true, "client_id": "AB1234", "expires_at_ist": "... 06:00 IST"}`.
Then confirm the token actually works end-to-end:

```bash
python examples/nse_kite_check.py --secret nse-quant/kite
```

## Disabling

No teardown needed — flip the env var and redeploy:

```bash
make deploy AWS_PROFILE=myprofile KITE_AUTO_LOGIN=false
```

The function short-circuits before touching AWS or Zerodha. Manual `/kite-login`
and `KiteTokenMonitor` are untouched by this and keep working either way.

## When it breaks

| Alert says | Cause | Fix |
|---|---|---|
| `TOTP step rejected` | Seed rotated — re-enrolling External TOTP on Zerodha issues a **new** seed and silently orphans the stored one | Re-copy the seed into the secret |
| `password step rejected` | Password changed, or account locked from failed attempts | Update `kite_password`; unlock via Zerodha |
| `no request_token` | App not authorised for this account | Log in manually once at `/kite-login` |
| `credentials incomplete` | A required field is empty | See *Populating the secret* |
| Nothing, but token still stale | Function disabled, or EventBridge rule removed | Check `AUTO_LOGIN_ENABLED`; check CloudWatch logs for `KiteAutoLogin` |
