"""Read-only smoke test for the Zerodha Kite Connect integration.

Pulls api_key + access_token from AWS Secrets Manager (or env), then calls
profile / margins / holdings to confirm the token is valid. Touches no orders.

Usage:
    python examples/nse_kite_check.py
    python examples/nse_kite_check.py --secret nse-quant/kite
    KITE_API_KEY=... KITE_ACCESS_TOKEN=... python examples/nse_kite_check.py --env
"""
from __future__ import annotations

import argparse
import json
import os
import sys


def _load_creds_from_secret(secret_name: str) -> dict:
    import boto3
    sm = boto3.client("secretsmanager")
    raw = sm.get_secret_value(SecretId=secret_name)["SecretString"]
    return json.loads(raw)


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
    args = p.parse_args()

    creds = _load_creds_from_env() if args.env else _load_creds_from_secret(args.secret)
    api_key = creds.get("api_key")
    access_token = creds.get("access_token")
    if not api_key or not access_token:
        sys.exit("[abort] api_key or access_token missing — log in via /kite-login first")

    try:
        from kiteconnect import KiteConnect
    except ImportError:
        sys.exit("[abort] kiteconnect not installed. Run: pip install kiteconnect")

    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(access_token)

    try:
        profile = kite.profile()
        margins = kite.margins()
        holdings = kite.holdings()
    except Exception as exc:
        sys.exit(f"[abort] kite call failed (token expired?): {exc}")

    print(json.dumps(_summarise(profile, margins, holdings), indent=2, default=str))


if __name__ == "__main__":
    main()
