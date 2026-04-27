"""Tests for examples/nse_kite_check.py — focused on the cron-friendly
exit-code contract:

  rc=0  token valid OR --skip-if-missing and nothing configured
  rc=2  token configured but rejected by Kite (alertable)

We never make real network calls; KiteConnect is mocked.
"""
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "examples" / "nse_kite_check.py"


def _run(*args, env=None):
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
    )
    return completed.returncode, completed.stdout, completed.stderr


# -----------------------------------------------------------------------------
# --skip-if-missing contract
# -----------------------------------------------------------------------------

def test_skip_if_missing_exits_zero_with_no_creds(monkeypatch):
    """No env vars + --env source => no creds => --skip-if-missing exits 0."""
    env = {"PATH": "/usr/bin:/bin"}  # deliberately empty of KITE_* vars
    rc, stdout, _stderr = _run("--env", "--skip-if-missing", env=env)
    assert rc == 0, f"expected 0, got {rc}; stdout={stdout!r}"
    assert "skipping" in stdout.lower()


def test_no_skip_flag_errors_on_missing_creds():
    """Without --skip-if-missing, missing creds is a hard error (rc != 0)."""
    env = {"PATH": "/usr/bin:/bin"}
    rc, _stdout, stderr = _run("--env", env=env)
    assert rc != 0
    assert "missing" in stderr.lower() or "abort" in stderr.lower()


# -----------------------------------------------------------------------------
# Token-rejected path (rc=2 contract — what the cron alerts on)
# -----------------------------------------------------------------------------

def test_rejected_token_exits_with_code_2(tmp_path):
    """When KiteConnect raises (e.g. TokenException), script must exit 2."""
    fake_module = tmp_path / "kiteconnect.py"
    fake_module.write_text(
        "class KiteConnect:\n"
        "    def __init__(self, api_key): pass\n"
        "    def set_access_token(self, t): pass\n"
        "    def profile(self): raise RuntimeError('token expired')\n"
        "    def margins(self): pass\n"
        "    def holdings(self): pass\n"
    )
    env = {
        "PATH": "/usr/bin:/bin",
        "KITE_API_KEY": "fake_key",
        "KITE_ACCESS_TOKEN": "fake_token",
        "PYTHONPATH": str(tmp_path),
    }
    rc, stdout, _stderr = _run("--env", env=env)
    assert rc == 2, f"expected 2 on rejection, got {rc}; stdout={stdout!r}"
    assert "rejected" in stdout.lower() or "token" in stdout.lower()


# -----------------------------------------------------------------------------
# Happy path with mocked SDK — token valid, prints summary, exits 0
# -----------------------------------------------------------------------------

def test_valid_token_prints_summary_and_exits_zero(tmp_path):
    fake_module = tmp_path / "kiteconnect.py"
    fake_module.write_text(
        "class KiteConnect:\n"
        "    def __init__(self, api_key): pass\n"
        "    def set_access_token(self, t): pass\n"
        "    def profile(self):\n"
        "        return {'user_id': 'TEST01', 'user_name': 'Test User',\n"
        "                'email': 't@example.com', 'broker': 'ZERODHA',\n"
        "                'exchanges': ['NSE']}\n"
        "    def margins(self):\n"
        "        return {'equity': {'available': {'cash': 1000.0}, 'utilised': {'debits': 0}, 'net': 1000.0}}\n"
        "    def holdings(self):\n"
        "        return [{'tradingsymbol': 'INFY', 'quantity': 1, 'average_price': 1450,\n"
        "                 'last_price': 1500, 'pnl': 50}]\n"
    )
    env = {
        "PATH": "/usr/bin:/bin",
        "KITE_API_KEY": "fake_key",
        "KITE_ACCESS_TOKEN": "fake_token",
        "PYTHONPATH": str(tmp_path),
    }
    rc, stdout, _stderr = _run("--env", env=env)
    assert rc == 0, f"expected 0, got {rc}"
    payload = json.loads(stdout)
    assert payload["user"]["client_id"] == "TEST01"
    assert payload["holdings_count"] == 1
