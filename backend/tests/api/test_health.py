from __future__ import annotations

from tests.conftest import AppHarness


def test_healthz_is_public_and_live(harness: AppHarness) -> None:
    response = harness.client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_reports_ready(harness: AppHarness) -> None:
    response = harness.client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_readyz_503_when_index_not_ready(harness: AppHarness) -> None:
    class NotReady:
        def ready(self) -> bool:
            return False

    harness.app.state.knowledge_index = NotReady()
    response = harness.client.get("/readyz")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
