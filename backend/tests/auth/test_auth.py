from __future__ import annotations

from app.auth.sessions import hash_token
from app.db.models import DemoSession
from sqlalchemy import select
from tests.conftest import ORIGIN, TEST_PASSWORD, AppHarness, DBHarness


def _cookie_token(harness: AppHarness) -> str:
    token = harness.client.cookies.get("clinicpilot_session")
    assert token
    return token


def test_wrong_password_is_rejected(harness: AppHarness, login) -> None:
    response = login(harness.client, password="not-the-password")
    assert response.status_code == 401
    assert "Incorrect password." in response.text
    assert 'data-testid="login-error"' in response.text
    assert "clinicpilot_session" not in response.headers.get("set-cookie", "")


def test_login_sets_scoped_cookie_and_serves_workbench(
    harness: AppHarness, login, frontend_dist
) -> None:
    response = login(harness.client)
    assert response.status_code == 303
    assert response.headers["location"] == "./"
    cookie = response.headers["set-cookie"].lower()
    assert "clinicpilot_session=" in cookie
    assert "path=/demo/" in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "secure" not in cookie

    page = harness.client.get("/demo/")
    assert page.status_code == 200
    assert 'id="clinicpilot-config"' in page.text
    assert '"prefix":"/demo/"' in page.text
    assert page.text.count('id="clinicpilot-config"') == 1


def test_login_page_redirects_when_already_signed_in(harness: AppHarness, login) -> None:
    assert login(harness.client).status_code == 303
    response = harness.client.get("/demo/login", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "./"


def test_login_next_is_sanitized(harness: AppHarness, login) -> None:
    external = login(harness.client, next_value="https://evil.example/steal")
    assert external.status_code == 303
    assert external.headers["location"] == "./"

    harness.client.cookies.clear()
    inside = login(harness.client, next_value="/demo/")
    assert inside.status_code == 303
    assert inside.headers["location"] == "/demo/"

    harness.client.cookies.clear()
    outside = login(harness.client, next_value="/other/")
    assert outside.status_code == 303
    assert outside.headers["location"] == "./"


def test_logout_revokes_session(harness: AppHarness, login, db: DBHarness) -> None:
    assert login(harness.client).status_code == 303
    token = _cookie_token(harness)

    response = harness.client.post("/demo/logout", headers=ORIGIN, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "./login"

    with db.session_factory() as session:
        record = session.scalar(
            select(DemoSession).where(DemoSession.token_hash == hash_token(token))
        )
        assert record is not None
        assert record.revoked_at is not None

    page = harness.client.get("/demo/", follow_redirects=False)
    assert page.status_code == 303
    assert page.headers["location"] == "./login"


def test_login_throttling(harness: AppHarness, login) -> None:
    for _ in range(5):
        response = login(harness.client, password="wrong")
        assert response.status_code == 401

    blocked = login(harness.client, password=TEST_PASSWORD)
    assert blocked.status_code == 429
    assert blocked.headers["retry-after"] == "300"
    assert "Too many failed attempts" in blocked.text


def test_unauthenticated_api_returns_json_401(harness: AppHarness) -> None:
    response = harness.client.post(
        "/demo/api/chat",
        json={"message_id": "m1", "message": "hello", "patient_id": "P001"},
    )
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "unauthorized"
    assert body["error"]["retryable"] is False
    assert body["request_id"]


def test_unauthenticated_page_redirects_to_login(harness: AppHarness) -> None:
    response = harness.client.get("/demo/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "./login"


def test_wrong_prefix_is_404(harness: AppHarness) -> None:
    response = harness.client.get("/not-the-prefix/")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"

    redirect = harness.client.get("/demo", follow_redirects=False)
    assert redirect.status_code == 308
    assert redirect.headers["location"] == "/demo/"


def test_cookie_write_without_origin_is_forbidden(harness: AppHarness, login) -> None:
    assert login(harness.client).status_code == 303
    response = harness.client.post(
        "/demo/api/chat",
        json={"message_id": "m1", "message": "hello", "patient_id": "P001"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"

    allowed = harness.client.post(
        "/demo/api/chat",
        json={"message_id": "m1", "message": "hello", "patient_id": "P001"},
        headers=ORIGIN,
    )
    assert allowed.status_code == 200


def test_security_headers_present(harness: AppHarness) -> None:
    response = harness.client.get("/demo/login")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "script-src 'self'" in response.headers["content-security-policy"]
    assert "'unsafe-inline'" in response.headers["content-security-policy"]


def test_authenticated_assets_are_served_and_scoped(
    harness: AppHarness, login, frontend_dist
) -> None:
    assert login(harness.client).status_code == 303
    asset = harness.client.get("/demo/assets/app.js")
    assert asset.status_code == 200
    assert "clinicpilot" in asset.text

    traversal = harness.client.get("/demo/assets/%2e%2e%2f%2e%2e%2fetc%2fpasswd")
    assert traversal.status_code == 404


def test_unauthenticated_assets_are_rejected(harness: AppHarness, frontend_dist) -> None:
    response = harness.client.get("/demo/assets/app.js")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_expired_session_is_rejected(harness: AppHarness, login) -> None:
    assert login(harness.client).status_code == 303
    harness.clock.advance(hours=9)
    response = harness.client.get("/demo/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "./login"
