from __future__ import annotations

from app.auth.sessions import SessionService
from app.contracts import PATIENT_ID, ChatResponse, SourceRef
from app.services.conversations import ConversationService, _title
from app.services.hashing import chat_request_hash
from fastapi.testclient import TestClient
from tests.conftest import ORIGIN, AppHarness


async def _session(harness: AppHarness):
    token = harness.client.cookies.get("clinicpilot_session")
    assert token
    service = SessionService(harness.session_factory, harness.clock, harness.settings)
    record = await service.resolve(token)
    assert record is not None
    return record


async def _seed_conversation(harness: AppHarness, *, user_text: str = "What are the hours?") -> str:
    record = await _session(harness)
    conversations = ConversationService(harness.session_factory, harness.clock)
    conversation_id = await conversations.create_conversation(record.id, PATIENT_ID)
    started = await conversations.start_turn(
        conversation_id, "m-1", chat_request_hash(user_text, PATIENT_ID)
    )
    assert started.turn_id is not None
    messages = [
        {"role": "user", "content": user_text, "_cp_message_id": started.turn_id},
        {
            "role": "assistant",
            "content": None,
            "_cp_message_id": "assistant-tool-call",
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "search_knowledge", "arguments": '{"query":"hours"}'},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call-1",
            "content": '{"ok":true,"results":[{"source_file":"clinics.csv","record_id":"C001"}]}',
        },
        {
            "role": "assistant",
            "content": "C001 is open on weekdays.",
            "_cp_message_id": "assistant-1",
        },
    ]
    await conversations.save_messages(conversation_id, messages, harness.clock.now())
    response = ChatResponse(
        conversation_id=conversation_id,
        message_id="m-1",
        assistant_message="C001 is open on weekdays.",
        sources=[SourceRef(source_file="clinics.csv", record_id="C001")],
    )
    await conversations.finish_turn(started.turn_id, response)
    return conversation_id


async def test_list_and_read_conversation_transcript(harness: AppHarness, login) -> None:
    assert login(harness.client).status_code == 303
    conversation_id = await _seed_conversation(harness)

    listed = harness.client.get("/demo/api/conversations")
    assert listed.status_code == 200
    payload = listed.json()
    assert len(payload) == 1
    assert payload[0]["id"] == conversation_id
    assert payload[0]["title"] == "What are the hours?"
    assert payload[0]["turn_count"] == 1
    assert payload[0]["active_turn_id"] is None

    detail = harness.client.get(f"/demo/api/conversations/{conversation_id}")
    assert detail.status_code == 200
    transcript = detail.json()
    assert transcript["conversation"]["id"] == conversation_id
    turn = transcript["turns"][0]
    assert turn["user"] == "What are the hours?"
    assert turn["assistant"] == "C001 is open on weekdays."
    assert turn["status"] == "completed"
    assert turn["sources"] == [{"source_file": "clinics.csv", "record_id": "C001"}]
    assert turn["tools"][0]["name"] == "search_knowledge"
    assert turn["tools"][0]["summary"] == "1 source"
    assert turn["tools"][0]["sources"] == [{"source_file": "clinics.csv", "record_id": "C001"}]


async def test_delete_conversation(harness: AppHarness, login) -> None:
    assert login(harness.client).status_code == 303
    conversation_id = await _seed_conversation(harness)

    deleted = harness.client.delete(f"/demo/api/conversations/{conversation_id}", headers=ORIGIN)
    assert deleted.status_code == 204
    assert harness.client.get(f"/demo/api/conversations/{conversation_id}").status_code == 404
    assert harness.client.get("/demo/api/conversations").json() == []


async def test_conversations_are_session_scoped(harness: AppHarness, login) -> None:
    assert login(harness.client).status_code == 303
    conversation_id = await _seed_conversation(harness)

    secondary = TestClient(harness.client.app)
    try:
        assert login(secondary).status_code == 303
        assert secondary.get("/demo/api/conversations").json() == []
        assert secondary.get(f"/demo/api/conversations/{conversation_id}").status_code == 403
        response = secondary.delete(f"/demo/api/conversations/{conversation_id}", headers=ORIGIN)
        assert response.status_code == 403
    finally:
        secondary.close()


def test_conversations_require_authentication(harness: AppHarness) -> None:
    assert harness.client.get("/demo/api/conversations").status_code == 401
    assert harness.client.get("/demo/api/conversations/unknown").status_code == 401


def test_title_uses_first_substantive_turn_and_word_boundary() -> None:
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "Hello."},
        {"role": "user", "content": "What is my last measured blood pressure?"},
    ]
    assert _title(messages) == "What is my last measured blood pressure?"

    long_title = _title([{"role": "user", "content": "word " * 40}])
    assert long_title.endswith("...")
    assert len(long_title) <= 67
    assert "  " not in long_title
