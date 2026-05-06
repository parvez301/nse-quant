#!/usr/bin/env python3
"""End-to-end smoke server for the v2 UI integration.

Spins up an http.server that maps URL paths → ui_lambda.handler.lambda_handler,
but rewires `_get_object` to read directly from local outputs/ on disk
(skipping S3). This validates that the new /api/regime, /api/shap_today,
/api/peers_today, /api/hit_rates, /api/trades/<sym>, /api/rank_history/<sym>
routes plus the existing wiring all return the expected shapes.

Usage:
  ./.venv/bin/python scripts/v2_local_smoke.py

Then open http://localhost:8765/v2 in a browser, or curl the endpoints.
"""
from __future__ import annotations

import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# Stub STATE_BUCKET before importing the handler module
os.environ.setdefault("STATE_BUCKET", "smoke-test")
os.environ.setdefault("AWS_PROFILE", "hireloop")
os.environ.setdefault("AWS_REGION", "ap-south-1")
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-south-1")
os.environ.pop("AWS_DEFAULT_PROFILE", None)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ui_lambda"))
import handler as h  # noqa: E402

OUTPUTS = Path(__file__).resolve().parent.parent / "outputs"


def _local_get_object(key: str):
    """Map S3 key → local file path under outputs/."""
    if not key.startswith("outputs/"):
        return None
    p = OUTPUTS.parent / key
    if not p.is_file():
        return None
    return p.read_bytes()


def _local_list_keys(prefix: str):
    p = OUTPUTS.parent / prefix
    if not p.is_dir():
        return []
    return [str(f.relative_to(OUTPUTS.parent)) for f in p.iterdir() if f.is_file()]


h._get_object = _local_get_object
h._list_keys = _local_list_keys


import urllib.request

ANALYTICS_PROXY_BASE = os.environ.get(
    "ANALYTICS_PROXY_BASE", "https://trade.hireloop.xyz"
)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path_only = self.path.split("?")[0]
        # Proxy /api/analytics/* to production CloudFront so the local smoke
        # exercises the real Parquet timeseries pipeline end-to-end.
        if path_only.startswith("/api/analytics/"):
            try:
                with urllib.request.urlopen(ANALYTICS_PROXY_BASE + self.path, timeout=10) as resp:
                    body = resp.read()
                    ctype = resp.headers.get("content-type", "application/json")
                    code = resp.status
            except Exception as exc:
                body = (f'{{"error": "analytics_proxy_failed", "detail": "{type(exc).__name__}: {exc}"}}').encode("utf-8")
                ctype = "application/json"
                code = 502
            self.send_response(code)
            self.send_header("content-type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        event = {
            "rawPath": self.path,
            "requestContext": {"http": {"method": "GET", "path": path_only}},
            "rawQueryString": self.path.split("?", 1)[1] if "?" in self.path else "",
        }
        result = h.handler(event, None)
        body = result.get("body") or ""
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(int(result["statusCode"]))
        for k, v in (result.get("headers") or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        sys.stderr.write(f"  {self.command} {self.path} → {args[1]}\n")


def main():
    port = int(os.environ.get("SMOKE_PORT", "8765"))
    server = HTTPServer(("127.0.0.1", port), Handler)
    print(f"v2 smoke server on http://127.0.0.1:{port}/v2")
    print("  endpoints to try:")
    print("    /api/regime  /api/shap_today  /api/peers_today  /api/hit_rates")
    print("    /api/decisions  /api/portfolio  /api/equity  /api/paper_trade_clock")
    print("    /api/trades/JBMA  /api/rank_history/BLUEJET")
    print("Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
