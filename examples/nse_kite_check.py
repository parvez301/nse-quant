"""Read-only smoke test for the Zerodha Kite Connect integration.

Pulls api_key + access_token from AWS Secrets Manager (or env), then calls
profile / margins / holdings to confirm the token is valid. Touches no orders.

Usage:
    python examples/nse_kite_check.py
    python examples/nse_kite_check.py --secret nse-quant/kite
    python examples/nse_kite_check.py --skip-if-missing   # exit 0 if no token
    KITE_API_KEY=... KITE_ACCESS_TOKEN=... python examples/nse_kite_check.py --env

Exit codes:
    0   token valid, profile/margins/holdings round-tripped
    0   --skip-if-missing was set and no token / SDK is configured
    2   token configured but expired / invalid (alertable from cron)
"""
from __future__ import annotations

import argparse
import json
import os
import sys


def _load_creds_from_secret(secret_name: str) -> dict:
    try:
        import boto3
    except ImportError:
        return {}
    try:
        sm = boto3.client("secretsmanager")
        raw = sm.get_secret_value(SecretId=secret_name)["SecretString"]
        return json.loads(raw)
    except Exception:
        return {}


def _load_creds_from_env() -> dict:
    return {
        "api_key": os.environ.get("KITE_API_KEY", ""),
        "access_token": os.environ.get("KITE_ACCESS_TOKEN", ""),
    }


def _summarise(profile: dict, margins: dict, holdings: list[dict]) -> dict:
    eq = (margins or {}).get("equity", {})
    available = eq.get("available", {}) or {}
    used = eq.get("utilised", {}) or {}
    return {
        "user": {
            "client_id": profile.get("user_id"),
            "name": profile.get("user_name"),
            "email": profile.get("email"),
            "broker": profile.get("broker"),
            "segments": profile.get("exchanges"),
        },
        "equity_funds": {
            "available_cash": available.get("cash"),
            "live_balance": available.get("live_balance"),
            "utilised_debits": used.get("debits"),
            "net": eq.get("net"),
        },
        "holdings_count": len(holdings or []),
        "holdings_sample": [
            {
                "symbol": h.get("tradingsymbol"),
                "qty": h.get("quantity"),
                "avg": h.get("average_price"),
                "last": h.get("last_price"),
                "pnl": h.get("pnl"),
            }
            for h in (holdings or [])[:5]
        ],
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--secret", default="nse-quant/kite")
    p.add_argument("--env", action="store_true", help="load creds from KITE_API_KEY / KITE_ACCESS_TOKEN env vars")
    p.add_argument(
        "--skip-if-missing",
        action="store_true",
        help="exit 0 with a skip message if no token / SDK is configured "
             "(use from cron so machines without Kite don't fail the daily run)",
    )
    args = p.parse_args()

    creds = _load_creds_from_env() if args.env else _load_creds_from_secret(args.secret)
    api_key = creds.get("api_key")
    access_token = creds.get("access_token")

    if not api_key or not access_token:
        msg = "[kite-check] api_key or access_token missing — log in via /kite-login first"
        if args.skip_if_missing:
            print("[kite-check] no token configured, skipping (use /kite-login to enable)")
            sys.exit(0)
        sys.exit(msg)

    try:
        from kiteconnect import KiteConnect
    except ImportError:
        if args.skip_if_missing:
            print("[kite-check] kiteconnect SDK not installed, skipping")
            sys.exit(0)
        sys.exit("[abort] kiteconnect not installed. Run: pip install kiteconnect")

    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(access_token)

    try:
        profile = kite.profile()
        margins = kite.margins()
        holdings = kite.holdings()
    except Exception as exc:
        # Token is configured but rejected by Kite — actionable failure
        print(f"[kite-check] token rejected by Kite: {exc}")
        sys.exit(2)

    print(json.dumps(_summarise(profile, margins, holdings), indent=2, default=str))


if __name__ == "__main__":
    main()
