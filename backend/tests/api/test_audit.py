from __future__ import annotations

from app.auth.sessions import SessionService
from app.services.audit import AuditService
from tests.conftest import AppHarness


async def _session(harness: AppHarness):
    token = harness.client.cookies.get("clinicpilot_session")
    assert token
    service = SessionService(harness.session_factory, harness.clock, harness.settings)
    record = await service.resolve(token)
    assert record is not None
    return record


def test_audit_requires_authentication(harness: AppHarness) -> None:
    assert harness.client.get("/demo/api/audit").status_code == 401


async def test_audit_returns_only_the_current_session(harness: AppHarness, login) -> None:
    assert login(harness.client).status_code == 303
    session = await _session(harness)
    audit = AuditService(harness.session_factory, harness.clock)
    await audit.record(
        demo_session_id=session.id,
        conversation_id="conversation-1",
        turn_id="turn-1",
        event_type="model_call",
        name="chat.completions",
        status="ok",
        payload={"model": "test-model", "usage": {"total_tokens": 12}},
    )

    response = harness.client.get("/demo/api/audit")

    assert response.status_code == 200
    body = response.json()
    assert len(body["events"]) == 1
    event = body["events"][0]
    assert event["event_type"] == "model_call"
    assert event["payload"]["model"] == "test-model"
    assert body["pricing"]["version"] == "deepseek-public-2025-09"
