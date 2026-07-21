"""Kite auto-login — mints a fresh daily access_token without human touch.

Zerodha invalidates the Kite Connect access_token every morning (~06:00 IST)
and offers no refresh-token flow for personal API subscriptions. The sanctioned
recovery is a manual OAuth + 2FA login at /kite-login on the dashboard.

This Lambda automates that by driving Zerodha's own web-login endpoints:

    POST /api/login   {user_id, password}          -> request_id
    POST /api/twofa   {user_id, request_id, totp}  -> session cookies
    GET  /connect/login?api_key=..&v=3             -> 302 chain -> request_token
    POST /session/token {api_key, request_token, checksum} -> access_token

The TOTP is computed locally (RFC 6238) from the External-TOTP seed the
operator enrolled in Google Authenticator, so the same seed drives both the
phone and this function.

    ---------------------------------------------------------------------
    OPERATOR NOTE: automated login is NOT permitted by the Kite Connect
    terms of service. SEBI requires the second factor be supplied by a
    human per session. Running this risks revocation of the API
    subscription. It exists because the operator made that trade-off
    knowingly. `AUTO_LOGIN_ENABLED=false` disables it without a redeploy.
    ---------------------------------------------------------------------

Triggered by EventBridge at 00:45 UTC (= 06:15 IST) Mon-Fri — after the
06:00 IST expiry, and 15 min before KiteTokenMonitor verifies the result at
06:30 IST. If this function fails, the monitor still pages the operator with
the manual login link, so a silent failure cannot cost a trading day.

Everything here is stdlib: urllib + http.cookiejar for the session, hmac +
struct for the TOTP. No Docker bundling, no third-party deps.
"""

import base64
import datetime
import hashlib
import hmac
import http.cookiejar
import json
import os
import struct
import time
import urllib.error
import urllib.parse
import urllib.request

import boto3


KITE_SECRET_NAME = os.environ["KITE_SECRET_NAME"]
SNS_TOPIC_ARN = os.environ["SNS_TOPIC_ARN"]
KITE_LOGIN_URL = os.environ.get("KITE_LOGIN_URL", "/kite-login on the dashboard")
AUTO_LOGIN_ENABLED = os.environ.get("AUTO_LOGIN_ENABLED", "true").lower() == "true"

KITE_WEB_BASE = "https://kite.zerodha.com"
KITE_API_LOGIN = f"{KITE_WEB_BASE}/api/login"
KITE_API_TWOFA = f"{KITE_WEB_BASE}/api/twofa"
KITE_CONNECT_LOGIN = f"{KITE_WEB_BASE}/connect/login"
KITE_TOKEN_URL = "https://api.kite.trade/session/token"

# Zerodha rejects requests without a browser-shaped UA on the web endpoints.
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "X-Kite-Version": "3",
}

MAX_REDIRECT_HOPS = 10
HTTP_TIMEOUT_SECONDS = 15

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


# ---------------------------------------------------------------------------
# RFC 6238 TOTP — same algorithm Google Authenticator runs on the phone
# ---------------------------------------------------------------------------

def compute_totp(base32Secret: str, atUnixTime: float | None = None,
                 stepSeconds: int = 30, digits: int = 6) -> str:
    """Six-digit SHA1 TOTP. Mirrors pyotp.TOTP(secret).now() exactly."""
    normalized = base32Secret.strip().replace(" ", "").upper()
    # Base32 requires the input length to be a multiple of 8; enrolment QR
    # payloads routinely ship unpadded, so pad before decoding.
    padding = "=" * (-len(normalized) % 8)
    keyBytes = base64.b32decode(normalized + padding, casefold=True)

    counter = int((time.time() if atUnixTime is None else atUnixTime) // stepSeconds)
    digest = hmac.new(keyBytes, struct.pack(">Q", counter), hashlib.sha1).digest()

    offset = digest[-1] & 0x0F
    truncated = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(truncated % (10 ** digits)).zfill(digits)


def seconds_until_next_totp_window(atUnixTime: float | None = None,
                                   stepSeconds: int = 30) -> float:
    """How long until the current TOTP code rolls over."""
    now = time.time() if atUnixTime is None else atUnixTime
    return stepSeconds - (now % stepSeconds)


# ---------------------------------------------------------------------------
# HTTP plumbing — cookie-bearing session with manual redirect control
# ---------------------------------------------------------------------------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Surfaces 3xx as HTTPError so we can read Location ourselves.

    We must not blindly follow the final hop: it lands on the app's registered
    redirect URL (the dashboard's /kite-callback), which would consume the
    single-use request_token before we get to exchange it.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def build_session() -> urllib.request.OpenerDirector:
    cookieJar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cookieJar),
        _NoRedirect(),
    )


def _post_form(opener, url: str, fields: dict) -> dict:
    body = urllib.parse.urlencode(fields).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            **BROWSER_HEADERS,
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with opener.open(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise RuntimeError(f"POST {url} -> HTTP {exc.code}: {detail}") from exc


def extract_request_token(url: str) -> str | None:
    query = urllib.parse.urlparse(url).query
    values = urllib.parse.parse_qs(query).get("request_token")
    return values[0] if values else None


def follow_until_request_token(opener, startUrl: str) -> str:
    """Walk the /connect/login redirect chain, stopping at request_token."""
    currentUrl = startUrl
    for _hop in range(MAX_REDIRECT_HOPS):
        found = extract_request_token(currentUrl)
        if found:
            return found

        request = urllib.request.Request(currentUrl, headers=BROWSER_HEADERS)
        try:
            with opener.open(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
                # A 200 means the chain terminated without ever handing us a
                # token — usually an interstitial consent screen, which means
                # the app is not authorised for this account yet.
                raise RuntimeError(
                    f"redirect chain ended at HTTP {response.status} with no "
                    f"request_token (url={currentUrl}). If this is the first "
                    f"run, authorise the app once manually at {KITE_LOGIN_URL}."
                )
        except urllib.error.HTTPError as exc:
            if exc.code not in (301, 302, 303, 307, 308):
                detail = exc.read().decode("utf-8", "replace")[:400]
                raise RuntimeError(
                    f"GET {currentUrl} -> HTTP {exc.code}: {detail}"
                ) from exc
            location = exc.headers.get("location")
            if not location:
                raise RuntimeError(f"HTTP {exc.code} with no Location header")
            currentUrl = urllib.parse.urljoin(currentUrl, location)

    raise RuntimeError(f"exceeded {MAX_REDIRECT_HOPS} redirects without a request_token")


# ---------------------------------------------------------------------------
# Kite login flow
# ---------------------------------------------------------------------------

def kite_web_login(opener, userId: str, password: str, totpSecret: str) -> None:
    """Authenticate against the Kite web session (password + TOTP)."""
    loginResponse = _post_form(
        opener, KITE_API_LOGIN, {"user_id": userId, "password": password}
    )
    if loginResponse.get("status") != "success":
        raise RuntimeError(f"password step rejected: {loginResponse.get('message')!r}")

    requestId = (loginResponse.get("data") or {}).get("request_id")
    if not requestId:
        raise RuntimeError(f"no request_id in login response: {loginResponse}")

    # If the code is about to roll over, wait it out — a code that expires
    # in-flight is the single most common cause of a spurious 2FA failure.
    if seconds_until_next_totp_window() < 2.0:
        time.sleep(2.5)

    twofaResponse = _post_form(
        opener,
        KITE_API_TWOFA,
        {
            "user_id": userId,
            "request_id": requestId,
            "twofa_value": compute_totp(totpSecret),
            "twofa_type": "totp",
        },
    )
    if twofaResponse.get("status") != "success":
        raise RuntimeError(f"TOTP step rejected: {twofaResponse.get('message')!r}")


def exchange_request_token(apiKey: str, apiSecret: str, requestToken: str) -> dict:
    """Trade request_token for access_token. checksum = sha256(key+token+secret)."""
    checksum = hashlib.sha256(
        f"{apiKey}{requestToken}{apiSecret}".encode("utf-8")
    ).hexdigest()
    body = urllib.parse.urlencode(
        {"api_key": apiKey, "request_token": requestToken, "checksum": checksum}
    ).encode("utf-8")
    request = urllib.request.Request(
        KITE_TOKEN_URL,
        data=body,
        method="POST",
        headers={
            "X-Kite-Version": "3",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise RuntimeError(f"token exchange -> HTTP {exc.code}: {detail}") from exc

    data = payload.get("data") or {}
    if not data.get("access_token"):
        raise RuntimeError(f"token exchange returned no access_token: {payload}")
    return data


def next_kite_expiry_ist(nowUtc: datetime.datetime) -> datetime.datetime:
    """Kite invalidates tokens at 06:00 IST daily. Mirrors ui_lambda's logic."""
    ist = nowUtc.astimezone(IST)
    expiry = ist.replace(hour=6, minute=0, second=0, microsecond=0)
    if ist >= expiry:
        expiry += datetime.timedelta(days=1)
    return expiry


# ---------------------------------------------------------------------------
# Lambda entrypoint
# ---------------------------------------------------------------------------

def _alert(subject: str, message: str) -> None:
    boto3.client("sns").publish(
        TopicArn=SNS_TOPIC_ARN, Subject=subject[:99], Message=message
    )


def handler(event, context):
    if not AUTO_LOGIN_ENABLED:
        return {"ok": False, "skipped": "AUTO_LOGIN_ENABLED=false"}

    secretsClient = boto3.client("secretsmanager")
    try:
        raw = secretsClient.get_secret_value(SecretId=KITE_SECRET_NAME)["SecretString"]
        secret = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        _alert(
            "[NSE] Kite auto-login: secret read failed",
            f"Couldn't read {KITE_SECRET_NAME}: {exc}",
        )
        return {"ok": False, "reason": "secret_read_failed", "error": str(exc)}

    required = ("api_key", "api_secret", "kite_user_id", "kite_password", "totp_secret")
    missing = [field for field in required if not secret.get(field, "").strip()]
    if missing:
        _alert(
            "[NSE] Kite auto-login: credentials incomplete",
            (
                f"Secret {KITE_SECRET_NAME} is missing: {', '.join(missing)}\n\n"
                f"Auto-login is disabled until these are populated. "
                f"Log in manually at: {KITE_LOGIN_URL}"
            ),
        )
        return {"ok": False, "reason": "missing_fields", "missing": missing}

    try:
        opener = build_session()
        kite_web_login(
            opener,
            secret["kite_user_id"].strip(),
            secret["kite_password"],
            secret["totp_secret"],
        )
        connectUrl = (
            f"{KITE_CONNECT_LOGIN}"
            f"?api_key={urllib.parse.quote(secret['api_key'].strip())}&v=3"
        )
        requestToken = follow_until_request_token(opener, connectUrl)
        sessionData = exchange_request_token(
            secret["api_key"].strip(), secret["api_secret"].strip(), requestToken
        )
    except Exception as exc:  # noqa: BLE001
        _alert(
            "[NSE] Kite auto-login FAILED — log in manually before 08:00 IST",
            (
                f"Auto-login raised: {exc}\n\n"
                f"The 06:30 IST token monitor will confirm whether a valid token "
                f"still exists. If not, the 08:00 IST decision cron will run "
                f"without live Kite data and the live-IC step will skip.\n\n"
                f"Manual login: {KITE_LOGIN_URL}\n\n"
                f"If the TOTP step is what failed, check that the External TOTP "
                f"seed in the secret still matches the one enrolled on the phone "
                f"— re-enrolling on Zerodha rotates the seed and silently breaks "
                f"this function."
            ),
        )
        return {"ok": False, "reason": "login_failed", "error": str(exc)}

    nowUtc = datetime.datetime.now(datetime.timezone.utc)
    validUntilIst = next_kite_expiry_ist(nowUtc).strftime("%Y-%m-%d %H:%M IST")

    payload = dict(secret)
    payload["access_token"] = sessionData["access_token"]
    payload["public_token"] = sessionData.get("public_token", "")
    payload["client_id"] = sessionData.get("user_id") or secret.get("client_id", "")
    payload["access_token_set_at"] = nowUtc.isoformat()
    payload["access_token_expires_at_ist"] = validUntilIst
    payload["access_token_source"] = "auto_login"
    secretsClient.put_secret_value(
        SecretId=KITE_SECRET_NAME, SecretString=json.dumps(payload)
    )

    return {
        "ok": True,
        "client_id": payload["client_id"],
        "expires_at_ist": validUntilIst,
    }
