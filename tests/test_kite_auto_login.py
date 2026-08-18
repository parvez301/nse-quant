"""Tests for kite_auto_login_lambda/handler.py.

Three things must hold or the daily token silently stops arriving:

  1. TOTP matches RFC 6238 (else every 2FA step is rejected).
  2. The redirect chain stops AT request_token and never follows the final
     hop into /kite-callback — that would burn the single-use token.
  3. Every failure path publishes an SNS alert, so a broken auto-login
     degrades to the old manual flow instead of a silent no-token day.

No network calls: urllib and boto3 are both stubbed.
"""
import base64
import importlib
import json
import sys
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
LAMBDA_DIR = REPO_ROOT / "kite_auto_login_lambda"

ENV = {
    "KITE_SECRET_NAME": "nse-quant/kite",
    "SNS_TOPIC_ARN": "arn:aws:sns:ap-south-1:1234:nse",
    "KITE_LOGIN_URL": "https://trade.example.com/kite-login",
}

COMPLETE_SECRET = {
    "api_key": "apikey123",
    "api_secret": "apisecret456",
    "kite_user_id": "AB1234",
    "kite_password": "hunter2",
    "totp_secret": "JBSWY3DPEHPK3PXP",
    "client_id": "AB1234",
}


@pytest.fixture()
def handler(monkeypatch):
    """Import the Lambda module fresh with env vars in place."""
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.syspath_prepend(str(LAMBDA_DIR))
    sys.modules.pop("handler", None)
    module = importlib.import_module("handler")
    yield module
    sys.modules.pop("handler", None)


# -----------------------------------------------------------------------------
# TOTP — must be bit-identical to what Google Authenticator shows
# -----------------------------------------------------------------------------

def test_totp_matches_rfc6238_sha1_vectors(handler):
    """RFC 6238 Appendix B reference vectors, SHA1, 8->6 digit truncation."""
    secret = base64.b32encode(b"12345678901234567890").decode()
    # (unix time, expected 8-digit code from the RFC) -> last 6 digits
    for unixTime, rfcCode in [
        (59, "94287082"),
        (1111111109, "07081804"),
        (1111111111, "14050471"),
        (1234567890, "89005924"),
        (2000000000, "69279037"),
    ]:
        assert handler.compute_totp(secret, atUnixTime=unixTime) == rfcCode[-6:]


def test_totp_accepts_unpadded_and_spaced_secret(handler):
    """Zerodha's enrolment screen shows the seed spaced and unpadded."""
    padded = base64.b32encode(b"12345678901234567890").decode()
    unpadded = padded.rstrip("=")
    spaced = " ".join(unpadded[i:i + 4] for i in range(0, len(unpadded), 4))

    assert handler.compute_totp(unpadded, atUnixTime=59) == "287082"
    assert handler.compute_totp(spaced.lower(), atUnixTime=59) == "287082"


def test_totp_rolls_over_at_step_boundary(handler):
    """Same 30s window -> same code; next window -> different code."""
    secret = base64.b32encode(b"12345678901234567890").decode()
    assert handler.compute_totp(secret, atUnixTime=30) == handler.compute_totp(
        secret, atUnixTime=59
    )
    assert handler.compute_totp(secret, atUnixTime=59) != handler.compute_totp(
        secret, atUnixTime=60
    )


def test_seconds_until_next_window(handler):
    assert handler.seconds_until_next_totp_window(atUnixTime=0) == 30
    assert handler.seconds_until_next_totp_window(atUnixTime=29) == 1
    assert handler.seconds_until_next_totp_window(atUnixTime=30) == 30


# -----------------------------------------------------------------------------
# Redirect chain — the token must be captured, never consumed
# -----------------------------------------------------------------------------

def _redirect(location):
    """A urllib HTTPError shaped like a 302 with a Location header."""
    error = urllib.error.HTTPError(
        url="https://kite.zerodha.com/x", code=302, msg="Found",
        hdrs=None, fp=None,
    )
    error.headers = {"location": location}
    return error


def test_follow_stops_at_request_token_without_fetching_callback(handler):
    """The hop carrying request_token must NOT be requested.

    Fetching it would hit the dashboard's /kite-callback, which exchanges the
    token itself — leaving our own exchange to fail on an already-used token.
    """
    fetched = []

    def fake_open(request, timeout=None):
        fetched.append(request.full_url)
        if "connect/login" in request.full_url:
            raise _redirect("https://kite.zerodha.com/connect/finish?sess=1")
        if "connect/finish" in request.full_url:
            raise _redirect(
                "https://trade.example.com/kite-callback"
                "?request_token=TOKEN_ABC&action=login&status=success"
            )
        raise AssertionError(f"unexpected fetch of {request.full_url}")

    opener = MagicMock()
    opener.open.side_effect = fake_open

    token = handler.follow_until_request_token(
        opener, "https://kite.zerodha.com/connect/login?api_key=k&v=3"
    )

    assert token == "TOKEN_ABC"
    assert not any("kite-callback" in url for url in fetched), (
        f"callback URL was fetched, burning the token: {fetched}"
    )


def test_follow_raises_when_chain_ends_without_token(handler):
    """A 200 terminal page means the app was never authorised for this account."""
    response = MagicMock()
    response.status = 200
    response.__enter__ = lambda self: self
    response.__exit__ = lambda self, *a: False

    opener = MagicMock()
    opener.open.return_value = response

    with pytest.raises(RuntimeError, match="no request_token"):
        handler.follow_until_request_token(opener, "https://kite.zerodha.com/connect/login")


def test_follow_gives_up_after_max_hops(handler):
    opener = MagicMock()
    opener.open.side_effect = lambda *a, **k: (_ for _ in ()).throw(
        _redirect("https://kite.zerodha.com/loop")
    )

    with pytest.raises(RuntimeError, match="exceeded"):
        handler.follow_until_request_token(opener, "https://kite.zerodha.com/start")


def test_extract_request_token(handler):
    assert handler.extract_request_token("https://x/cb?request_token=T1&status=success") == "T1"
    assert handler.extract_request_token("https://x/cb?status=success") is None
    assert handler.extract_request_token("https://kite.zerodha.com/connect/login") is None


# -----------------------------------------------------------------------------
# Login flow
# -----------------------------------------------------------------------------

def test_web_login_posts_totp_with_request_id(handler):
    posted = []

    def fake_post(opener, url, fields):
        posted.append((url, fields))
        if url == handler.KITE_API_LOGIN:
            return {"status": "success", "data": {"request_id": "REQ99"}}
        return {"status": "success", "data": {}}

    with patch.object(handler, "_post_form", side_effect=fake_post):
        handler.kite_web_login(MagicMock(), "AB1234", "hunter2", "JBSWY3DPEHPK3PXP")

    loginUrl, loginFields = posted[0]
    twofaUrl, twofaFields = posted[1]
    assert loginUrl == handler.KITE_API_LOGIN
    assert loginFields == {"user_id": "AB1234", "password": "hunter2"}
    assert twofaUrl == handler.KITE_API_TWOFA
    assert twofaFields["request_id"] == "REQ99"
    assert twofaFields["twofa_type"] == "totp"
    assert twofaFields["twofa_value"].isdigit() and len(twofaFields["twofa_value"]) == 6


def test_web_login_raises_on_bad_password(handler):
    with patch.object(
        handler, "_post_form",
        return_value={"status": "error", "message": "Invalid user id or password"},
    ):
        with pytest.raises(RuntimeError, match="password step rejected"):
            handler.kite_web_login(MagicMock(), "AB1234", "wrong", "JBSWY3DPEHPK3PXP")


def test_web_login_raises_on_bad_totp(handler):
    def fake_post(opener, url, fields):
        if url == handler.KITE_API_LOGIN:
            return {"status": "success", "data": {"request_id": "REQ99"}}
        return {"status": "error", "message": "Invalid TOTP"}

    with patch.object(handler, "_post_form", side_effect=fake_post):
        with pytest.raises(RuntimeError, match="TOTP step rejected"):
            handler.kite_web_login(MagicMock(), "AB1234", "hunter2", "JBSWY3DPEHPK3PXP")


def test_exchange_uses_sha256_checksum(handler):
    import hashlib
    import urllib.parse as parse

    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["body"] = request.data.decode()
        response = MagicMock()
        response.read.return_value = json.dumps(
            {"data": {"access_token": "AT1", "public_token": "PT1", "user_id": "AB1234"}}
        ).encode()
        response.__enter__ = lambda self: self
        response.__exit__ = lambda self, *a: False
        return response

    with patch.object(handler.urllib.request, "urlopen", side_effect=fake_urlopen):
        data = handler.exchange_request_token("apikey123", "apisecret456", "TOKEN_ABC")

    assert data["access_token"] == "AT1"
    fields = parse.parse_qs(captured["body"])
    expected = hashlib.sha256(b"apikey123TOKEN_ABCapisecret456").hexdigest()
    assert fields["checksum"][0] == expected


# -----------------------------------------------------------------------------
# handler() — secret round-trip and alert-on-every-failure contract
# -----------------------------------------------------------------------------

def _stub_boto(secretPayload):
    """Returns (boto3_client_factory, secrets_mock, sns_mock)."""
    secretsMock = MagicMock()
    secretsMock.get_secret_value.return_value = {
        "SecretString": json.dumps(secretPayload)
    }
    snsMock = MagicMock()

    def clientFactory(service, *args, **kwargs):
        return snsMock if service == "sns" else secretsMock

    return clientFactory, secretsMock, snsMock


def test_handler_writes_token_and_preserves_other_secret_fields(handler):
    clientFactory, secretsMock, snsMock = _stub_boto(COMPLETE_SECRET)

    with patch.object(handler.boto3, "client", side_effect=clientFactory), \
         patch.object(handler, "build_session", return_value=MagicMock()), \
         patch.object(handler, "kite_web_login"), \
         patch.object(handler, "follow_until_request_token", return_value="TOKEN_ABC"), \
         patch.object(
             handler, "exchange_request_token",
             return_value={"access_token": "AT1", "public_token": "PT1", "user_id": "AB1234"},
         ):
        result = handler.handler({}, None)

    assert result["ok"] is True
    written = json.loads(secretsMock.put_secret_value.call_args.kwargs["SecretString"])
    assert written["access_token"] == "AT1"
    assert written["access_token_source"] == "auto_login"
    assert written["access_token_expires_at_ist"].endswith("06:00 IST")
    # Credentials must survive the write — clobbering them bricks tomorrow's run.
    for field in ("api_key", "api_secret", "kite_user_id", "kite_password", "totp_secret"):
        assert written[field] == COMPLETE_SECRET[field]
    snsMock.publish.assert_not_called()


def test_handler_alerts_and_does_not_write_when_login_fails(handler):
    clientFactory, secretsMock, snsMock = _stub_boto(COMPLETE_SECRET)

    with patch.object(handler.boto3, "client", side_effect=clientFactory), \
         patch.object(handler, "build_session", return_value=MagicMock()), \
         patch.object(handler, "kite_web_login", side_effect=RuntimeError("TOTP step rejected")):
        result = handler.handler({}, None)

    assert result["ok"] is False and result["reason"] == "login_failed"
    secretsMock.put_secret_value.assert_not_called()
    snsMock.publish.assert_called_once()
    message = snsMock.publish.call_args.kwargs["Message"]
    assert ENV["KITE_LOGIN_URL"] in message, "alert must carry the manual fallback link"


def test_handler_alerts_on_missing_credentials(handler):
    incomplete = {**COMPLETE_SECRET, "totp_secret": "", "kite_password": ""}
    clientFactory, secretsMock, snsMock = _stub_boto(incomplete)

    with patch.object(handler.boto3, "client", side_effect=clientFactory):
        result = handler.handler({}, None)

    assert result["ok"] is False and result["reason"] == "missing_fields"
    assert set(result["missing"]) == {"totp_secret", "kite_password"}
    secretsMock.put_secret_value.assert_not_called()
    snsMock.publish.assert_called_once()


def test_handler_alerts_on_secret_read_failure(handler):
    secretsMock = MagicMock()
    secretsMock.get_secret_value.side_effect = RuntimeError("AccessDenied")
    snsMock = MagicMock()

    with patch.object(
        handler.boto3, "client",
        side_effect=lambda service, *a, **k: snsMock if service == "sns" else secretsMock,
    ):
        result = handler.handler({}, None)

    assert result["ok"] is False and result["reason"] == "secret_read_failed"
    snsMock.publish.assert_called_once()


def test_kill_switch_short_circuits_before_any_aws_call(handler, monkeypatch):
    """AUTO_LOGIN_ENABLED=false must disable auto-login without a redeploy."""
    monkeypatch.setattr(handler, "AUTO_LOGIN_ENABLED", False)
    boto3Mock = MagicMock()

    with patch.object(handler.boto3, "client", boto3Mock):
        result = handler.handler({}, None)

    assert result["ok"] is False
    assert "AUTO_LOGIN_ENABLED" in result["skipped"]
    boto3Mock.assert_not_called()


def test_expiry_is_next_0600_ist(handler):
    import datetime

    ist = handler.IST
    # 06:15 IST Monday -> expires 06:00 IST Tuesday
    monday = datetime.datetime(2026, 7, 20, 6, 15, tzinfo=ist)
    assert handler.next_kite_expiry_ist(monday) == datetime.datetime(
        2026, 7, 21, 6, 0, tzinfo=ist
    )
    # 05:00 IST -> expires 06:00 IST same day
    early = datetime.datetime(2026, 7, 20, 5, 0, tzinfo=ist)
    assert handler.next_kite_expiry_ist(early) == datetime.datetime(
        2026, 7, 20, 6, 0, tzinfo=ist
    )
