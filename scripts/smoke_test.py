#!/usr/bin/env python3
"""Non-mutating ClinicPilot deployment smoke checks.

Only GET requests are made. The script never logs in, creates a booking, or
changes application state, so it is safe to run against a live deployment and
against a CI container.

Usage:
    python3 scripts/smoke_test.py \
        --base-url http://127.0.0.1:8000 \
        --prefix /demo/

Optional authenticated check (cookie value is read from the environment and
never printed):

    CLINICPILOT_SESSION_COOKIE='clinicpilot_session=...' \
        python3 scripts/smoke_test.py --prefix /<secret>/

Health endpoints are internal-only by contract. Run this from the host or
container network, not through the public Cloudflare hostname.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any


class SmokeFailure(RuntimeError):
    pass


class Response:
    def __init__(self, status: int, content_type: str, body: bytes) -> None:
        self.status = status
        self.content_type = content_type
        self.body = body

    def json(self) -> Any:
        try:
            return json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise SmokeFailure("response body is not valid JSON") from exc


def _get(url: str, *, timeout: float, cookie: str | None = None) -> Response:
    headers = {"Accept": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return Response(
                response.status,
                response.headers.get_content_type(),
                response.read(1_000_000),
            )
    except urllib.error.HTTPError as error:
        return Response(
            error.code,
            error.headers.get_content_type(),
            error.read(1_000_000),
        )


def _normalize_prefix(value: str) -> str:
    slug = value.strip().strip("/")
    if not slug:
        raise SmokeFailure("prefix must not be empty")
    return f"/{slug}/"


def _expect(
    name: str,
    response: Response,
    *,
    status: int,
    json_body: bool = False,
) -> Response:
    if response.status != status:
        raise SmokeFailure(f"{name}: expected HTTP {status}, got {response.status}")
    if json_body and "json" not in response.content_type:
        raise SmokeFailure(
            f"{name}: expected a JSON response, got {response.content_type or 'no content type'}"
        )
    return response


def _error_code(response: Response) -> str:
    body = response.json()
    if not isinstance(body, dict):
        raise SmokeFailure("error response is not a JSON object")
    error = body.get("error")
    if not isinstance(error, dict) or not isinstance(error.get("code"), str):
        raise SmokeFailure("error response is missing error.code")
    return error["code"]


def run(args: argparse.Namespace) -> int:
    base = args.base_url.rstrip("/")
    prefix = _normalize_prefix(args.prefix)
    wrong_prefix = "/__clinicpilot_smoke_wrong_prefix__/"
    cookie = os.environ.get(args.cookie_env, "").strip() or None

    checks: list[str] = []

    health = _expect(
        "liveness", _get(f"{base}/healthz", timeout=args.timeout), status=200
    )
    if "json" in health.content_type:
        payload = health.json()
        if isinstance(payload, dict) and payload.get("status") not in (None, "ok"):
            raise SmokeFailure(
                f"liveness: unexpected status value {payload.get('status')!r}"
            )
    checks.append("healthz -> 200")

    _expect("readiness", _get(f"{base}/readyz", timeout=args.timeout), status=200)
    checks.append("readyz -> 200")

    _expect(
        "login page",
        _get(f"{base}{prefix}login", timeout=args.timeout),
        status=200,
    )
    checks.append("login page -> 200")

    wrong = _expect(
        "wrong prefix",
        _get(f"{base}{wrong_prefix}", timeout=args.timeout),
        status=404,
        json_body=True,
    )
    if _error_code(wrong) != "not_found":
        raise SmokeFailure("wrong prefix: expected error.code=not_found")
    checks.append("wrong prefix -> 404 not_found")

    # Contract: anything outside the runtime prefix, including an unprefixed
    # API path, is a JSON 404 rather than an unauthenticated API.
    unprefixed = _expect(
        "unprefixed API",
        _get(f"{base}/api/bookings", timeout=args.timeout),
        status=404,
        json_body=True,
    )
    if _error_code(unprefixed) != "not_found":
        raise SmokeFailure("unprefixed API: expected error.code=not_found")
    checks.append("unprefixed API -> 404 not_found")

    unauthenticated = _expect(
        "unauthenticated bookings",
        _get(f"{base}{prefix}api/bookings", timeout=args.timeout),
        status=401,
        json_body=True,
    )
    if _error_code(unauthenticated) != "unauthorized":
        raise SmokeFailure("unauthenticated bookings: expected error.code=unauthorized")
    checks.append("unauthenticated bookings -> 401 unauthorized")

    if cookie:
        authenticated = _expect(
            "authenticated bookings",
            _get(f"{base}{prefix}api/bookings", timeout=args.timeout, cookie=cookie),
            status=200,
            json_body=True,
        )
        bookings = authenticated.json()
        if not isinstance(bookings, list):
            raise SmokeFailure("authenticated bookings: expected a JSON list")
        checks.append(f"authenticated bookings -> 200 ({len(bookings)} rows)")

    for check in checks:
        print(f"[ok] {check}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("CLINICPILOT_BASE_URL", "http://127.0.0.1:8000"),
        help="Internal application origin (default: %(default)s)",
    )
    parser.add_argument(
        "--prefix",
        default=os.environ.get("DEMO_PATH_PREFIX", "/demo/"),
        help="Runtime browser prefix (default: %(default)s)",
    )
    parser.add_argument(
        "--cookie-env",
        default="CLINICPILOT_SESSION_COOKIE",
        help="Environment variable holding an optional session Cookie header",
    )
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()

    try:
        return run(args)
    except (SmokeFailure, urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
