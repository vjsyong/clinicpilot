from __future__ import annotations

import asyncio
from typing import Any

from app.auth.sessions import SessionService
from app.contracts import PATIENT_ID, ProviderError
from app.services.conversations import ConversationService
from app.services.hashing import chat_request_hash
from fastapi.testclient import TestClient
from tests.conftest import ORIGIN, AppHarness


def _send(client: TestClient, **overrides: Any) -> Any:
    body = {
        "conversation_id": None,
        "message_id": "m1",
        "message": "hello",
        "patient_id": "P001",
    }
    body.update(overrides)
    return client.post("/demo/api/chat", json=body, headers=ORIGIN)


async def _conversation_with_in_progress_turn(harness: AppHarness, text: str = "pending") -> str:
    token = harness.client.cookies.get("clinicpilot_session")
    assert token
    sessions = SessionService(harness.session_factory, harness.clock, harness.settings)
    record = await sessions.resolve(token)
    assert record is not None
    conversations = ConversationService(harness.session_factory, harness.clock)
    conversation_id = await conversations.create_conversation(record.id, PATIENT_ID)
    await conversations.start_turn(
        conversation_id, "m-inflight", chat_request_hash(text, PATIENT_ID)
    )
    return conversation_id


def test_chat_creates_conversation_and_replays_stored_response(harness: AppHarness, login) -> None:
    assert login(harness.client).status_code == 303

    first = _send(harness.client)
    assert first.status_code == 200
    payload = first.json()
    assert payload["conversation_id"]
    assert payload["message_id"] == "m1"
    assert payload["assistant_message"] == "echo: hello"
    assert len(harness.controller.calls) == 1

    replay = _send(harness.client, conversation_id=payload["conversation_id"])
    assert replay.status_code == 200
    assert replay.json() == payload
    assert len(harness.controller.calls) == 1


def test_duplicate_message_id_with_different_text_conflicts(harness: AppHarness, login) -> None:
    assert login(harness.client).status_code == 303
    first = _send(harness.client)
    assert first.status_code == 200
    conversation_id = first.json()["conversation_id"]

    conflict = _send(
        harness.client,
        conversation_id=conversation_id,
        message_id="m1",
        message="different text",
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "message_id_conflict"
    assert conflict.json()["error"]["retryable"] is False


def test_in_progress_turn_returns_retryable_conflict(harness: AppHarness, login) -> None:
    assert login(harness.client).status_code == 303
    conversation_id = asyncio.run(_conversation_with_in_progress_turn(harness))

    response = _send(
        harness.client,
        conversation_id=conversation_id,
        message_id="m-inflight",
        message="pending",
    )
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "turn_in_progress"
    assert error["retryable"] is True
    assert harness.controller.calls == []


def test_foreign_session_conversation_is_404(harness: AppHarness, login) -> None:
    assert login(harness.client).status_code == 303
    first = _send(harness.client)
    conversation_id = first.json()["conversation_id"]

    secondary = TestClient(harness.client.app)
    try:
        assert login(secondary).status_code == 303
        response = _send(
            secondary,
            conversation_id=conversation_id,
            message_id="m2",
            message="foreign",
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"
    finally:
        secondary.close()


def test_wrong_patient_is_forbidden(harness: AppHarness, login) -> None:
    assert login(harness.client).status_code == 303
    response = _send(harness.client, patient_id="P002")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_provider_error_maps_to_retryable_502(harness: AppHarness, login) -> None:
    assert login(harness.client).status_code == 303

    class FailingController:
        async def handle_turn(self, ctx: Any, emit: Any = None) -> Any:
            raise ProviderError("upstream unavailable")

    harness.app.state.controller = FailingController()
    response = _send(harness.client)
    assert response.status_code == 502
    error = response.json()["error"]
    assert error["code"] == "provider_error"
    assert error["retryable"] is True


def test_unexpected_error_maps_to_internal_error(harness: AppHarness, login) -> None:
    assert login(harness.client).status_code == 303

    class ExplodingController:
        async def handle_turn(self, ctx: Any, emit: Any = None) -> Any:
            raise RuntimeError("secret internals should not leak")

    harness.app.state.controller = ExplodingController()
    response = _send(harness.client)
    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "internal_error"
    assert "secret internals" not in response.text


def test_chat_defaults_to_the_local_model(harness: AppHarness, login) -> None:
    assert login(harness.client).status_code == 303
    response = _send(harness.client)
    assert response.status_code == 200
    assert harness.controller.calls[-1].model == "local"


def test_chat_rejects_deepseek_without_a_key(harness: AppHarness, login) -> None:
    assert login(harness.client).status_code == 303
    response = _send(harness.client, model="deepseek")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "provider_not_configured"
    assert harness.controller.calls == []


def test_chat_forwards_the_selected_provider(harness: AppHarness, login) -> None:
    assert login(harness.client).status_code == 303
    harness.app.state.provider_settings.set_key("sk-test-key")
    response = _send(harness.client, model="deepseek")
    assert response.status_code == 200
    assert harness.controller.calls[-1].model == "deepseek"


def test_replay_does_not_require_the_selected_provider(harness: AppHarness, login) -> None:
    assert login(harness.client).status_code == 303
    first = _send(harness.client)
    assert first.status_code == 200
    replay = _send(
        harness.client,
        conversation_id=first.json()["conversation_id"],
        model="deepseek",
    )
    assert replay.status_code == 200
    assert replay.json() == first.json()
