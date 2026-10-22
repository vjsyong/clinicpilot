from __future__ import annotations

from tests.conftest import AppHarness

INTERNAL_HOST = {"host": "127.0.0.1:8000"}


def test_healthz_is_internal_and_live(harness: AppHarness) -> None:
    response = harness.client.get("/healthz", headers=INTERNAL_HOST)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_reports_ready(harness: AppHarness) -> None:
    response = harness.client.get("/readyz", headers=INTERNAL_HOST)
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_readyz_503_when_index_not_ready(harness: AppHarness) -> None:
    class NotReady:
        def ready(self) -> bool:
            return False

    harness.app.state.knowledge_index = NotReady()
    response = harness.client.get("/readyz", headers=INTERNAL_HOST)
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


def test_health_routes_are_not_public(harness: AppHarness) -> None:
    for path in ("/healthz", "/readyz"):
        response = harness.client.get(path, headers={"host": "dk.seanyong.xyz"})
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"


def test_cloudflare_headers_cannot_reach_health_routes(harness: AppHarness) -> None:
    response = harness.client.get(
        "/readyz",
        headers={"host": "127.0.0.1:8000", "cf-ray": "audit-probe"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
