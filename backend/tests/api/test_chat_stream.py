from __future__ import annotations

import json
from typing import Any

import pytest
from app.contracts import SourceRef, TurnResult
from app.services.conversations import ConversationService
from fastapi.testclient import TestClient
from tests.conftest import ORIGIN, AppHarness


class StreamingController:
    def __init__(self, harness: AppHarness) -> None:
        self.calls = 0
        self.conversations = ConversationService(harness.session_factory, harness.clock)

    async def handle_turn(self, ctx: Any, emit: Any = None) -> TurnResult:
        self.calls += 1
        if emit is not None:
            await emit("status", {"stage": "thinking"})
            await emit(
                "tool_start",
                {"id": "call-1", "name": "search_knowledge", "args": {"query": "hours"}},
            )
            await emit(
                "tool_end",
                {
                    "id": "call-1",
                    "name": "search_knowledge",
                    "ok": True,
                    "summary": "1 source",
                    "sources": [{"source_file": "clinics.csv", "record_id": "C001"}],
                },
            )
            await emit("content", {"delta": "C001 is open weekdays."})
        await self.conversations.save_messages(
            ctx.conversation_id,
            [
                {"role": "user", "content": ctx.user_text, "_cp_message_id": ctx.turn_id},
                {
                    "role": "assistant",
                    "content": None,
                    "_cp_message_id": "assistant-tool-call",
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {
                                "name": "search_knowledge",
                                "arguments": '{"query":"hours"}',
                            },
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": "call-1",
                    "content": (
                        '{"ok":true,"results":[{"source_file":"clinics.csv","record_id":"C001"}]}'
                    ),
                },
                {
                    "role": "assistant",
                    "content": "C001 is open weekdays.",
                    "_cp_message_id": "assistant-1",
                },
            ],
            ctx.now,
        )
        return TurnResult(
            assistant_message="C001 is open weekdays.",
            sources=[SourceRef(source_file="clinics.csv", record_id="C001")],
        )


def _body(message_id: str = "m-stream", message: str = "What are the hours?") -> dict[str, Any]:
    return {
        "conversation_id": None,
        "message_id": message_id,
        "message": message,
        "patient_id": "P001",
    }


def _events(text: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for block in text.split("\n\n"):
        event = ""
        data = ""
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data += line[5:].strip()
        if event:
            events.append((event, json.loads(data) if data else {}))
    return events


def test_stream_emits_events_and_persists_the_turn(harness: AppHarness, login) -> None:
    assert login(harness.client).status_code == 303
    harness.app.state.controller = StreamingController(harness)

    with harness.client.stream(
        "POST", "/demo/api/chat/stream", json=_body(), headers=ORIGIN
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())

    events = _events(body)
    names = [name for name, _ in events]
    assert names[0] == "session"
    assert "status" in names
    assert "tool_start" in names
    assert "tool_end" in names
    assert "content" in names
    assert names[-1] == "done"

    session = events[0][1]
    done = events[-1][1]
    assert session["conversation_id"] == done["conversation_id"]
    assert done["assistant_message"] == "C001 is open weekdays."
    assert done["sources"] == [{"source_file": "clinics.csv", "record_id": "C001"}]

    replay = harness.client.get(f"/demo/api/chat/runs/{session['turn_id']}")
    assert replay.status_code == 200
    replay_events = _events(replay.text)
    assert [name for name, _ in replay_events] == names

    transcript = harness.client.get(f"/demo/api/conversations/{session['conversation_id']}")
    assert transcript.status_code == 200
    turn = transcript.json()["turns"][0]
    assert turn["assistant"] == "C001 is open weekdays."
    assert turn["tools"][0]["summary"] == "1 source"


def test_stream_rejects_conflicting_message_id(harness: AppHarness, login) -> None:
    assert login(harness.client).status_code == 303
    harness.app.state.controller = StreamingController(harness)

    with harness.client.stream(
        "POST", "/demo/api/chat/stream", json=_body(), headers=ORIGIN
    ) as response:
        body = "".join(response.iter_text())
    conversation_id = _events(body)[0][1]["conversation_id"]

    conflict = harness.client.post(
        "/demo/api/chat/stream",
        json={**_body(message="different"), "conversation_id": conversation_id},
        headers=ORIGIN,
    )
    assert conflict.status_code == 409
    assert conversation_id


def test_stop_completed_run_reports_not_stopped(harness: AppHarness, login) -> None:
    assert login(harness.client).status_code == 303
    harness.app.state.controller = StreamingController(harness)

    with harness.client.stream(
        "POST", "/demo/api/chat/stream", json=_body(), headers=ORIGIN
    ) as response:
        body = "".join(response.iter_text())
    turn_id = _events(body)[0][1]["turn_id"]

    stopped = harness.client.post(f"/demo/api/chat/runs/{turn_id}/stop", headers=ORIGIN)
    assert stopped.status_code == 200
    assert stopped.json() == {"stopped": False}


def test_stream_runs_are_session_scoped(harness: AppHarness, login) -> None:
    assert login(harness.client).status_code == 303
    harness.app.state.controller = StreamingController(harness)

    with harness.client.stream(
        "POST", "/demo/api/chat/stream", json=_body(), headers=ORIGIN
    ) as response:
        body = "".join(response.iter_text())
    turn_id = _events(body)[0][1]["turn_id"]

    secondary = TestClient(harness.client.app)
    try:
        assert login(secondary).status_code == 303
        assert secondary.get(f"/demo/api/chat/runs/{turn_id}").status_code == 404
        assert (
            secondary.post(f"/demo/api/chat/runs/{turn_id}/stop", headers=ORIGIN).status_code == 404
        )
    finally:
        secondary.close()


def test_regenerate_replaces_the_last_reply_without_duplicating_the_turn(
    harness: AppHarness, login
) -> None:
    assert login(harness.client).status_code == 303
    harness.app.state.controller = StreamingController(harness)

    with harness.client.stream(
        "POST", "/demo/api/chat/stream", json=_body(), headers=ORIGIN
    ) as response:
        body = "".join(response.iter_text())
    session = _events(body)[0][1]

    transcript = harness.client.get(f"/demo/api/conversations/{session['conversation_id']}")
    client_message_id = transcript.json()["turns"][0]["client_message_id"]

    with harness.client.stream(
        "POST",
        "/demo/api/chat/regenerate",
        json={
            "conversation_id": session["conversation_id"],
            "message_id": client_message_id,
        },
        headers=ORIGIN,
    ) as response:
        assert response.status_code == 200
        regenerated = _events("".join(response.iter_text()))

    assert regenerated[0][0] == "session"
    assert regenerated[-1][0] == "done"
    refreshed = harness.client.get(f"/demo/api/conversations/{session['conversation_id']}")
    turns = refreshed.json()["turns"]
    assert len(turns) == 1
    assert turns[0]["assistant"] == "C001 is open weekdays."


@pytest.mark.asyncio
async def test_stopping_an_active_run_fails_the_turn_and_emits_stopped(db, frozen_clock) -> None:
    import asyncio
    from types import SimpleNamespace

    from app.api.chat_stream import ChatRun, _run
    from app.auth.sessions import SessionService
    from app.contracts import PATIENT_ID
    from app.db.models import ChatTurn
    from app.services.conversations import ConversationService
    from app.services.hashing import chat_request_hash

    class SlowController:
        def __init__(self) -> None:
            self.started = asyncio.Event()

        async def handle_turn(self, ctx, emit=None):
            if emit is not None:
                await emit("status", {"stage": "thinking"})
            self.started.set()
            await asyncio.sleep(60)

    sessions = SessionService(db.session_factory, frozen_clock, db.settings)
    _token, session = await sessions.create_session()
    conversations = ConversationService(db.session_factory, frozen_clock)
    conversation_id = await conversations.create_conversation(session.id, PATIENT_ID)
    started = await conversations.start_turn(
        conversation_id, "m-stop", chat_request_hash("hello", PATIENT_ID)
    )
    assert started.turn_id is not None

    controller = SlowController()
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                controller=controller,
                conversation_locks={},
            )
        )
    )
    run = ChatRun(
        turn_id=started.turn_id,
        conversation_id=conversation_id,
        client_message_id="m-stop",
        demo_session_id=session.id,
    )
    task = asyncio.create_task(_run(run, request, conversations, "hello", frozen_clock.now()))
    run.task = task
    await asyncio.wait_for(controller.started.wait(), timeout=2)
    run.cancelled = True
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert run.done is True
    assert any(event == "stopped" for event, _data in run.events)
    with db.session_factory() as stored:
        turn = stored.get(ChatTurn, started.turn_id)
        assert turn is not None
        assert turn.status == "failed"


@pytest.mark.asyncio
async def test_stop_route_cancels_an_active_task() -> None:
    import asyncio
    from types import SimpleNamespace

    from app.api.chat_stream import ChatRun, ChatRunRegistry, stop_chat_run

    registry = ChatRunRegistry()
    run = ChatRun(
        turn_id="turn-stop-route",
        conversation_id="conversation-1",
        client_message_id="message-1",
        demo_session_id=1,
    )
    started = asyncio.Event()

    async def slow() -> None:
        started.set()
        await asyncio.sleep(60)

    task = asyncio.create_task(slow())
    run.task = task
    registry.add(run)
    await started.wait()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(chat_runs=registry)))

    result = await stop_chat_run("turn-stop-route", request, SimpleNamespace(id=1))

    assert result == {"stopped": True}
    assert run.cancelled is True
    await asyncio.gather(task, return_exceptions=True)
    assert task.cancelled() is True


@pytest.mark.asyncio
async def test_stop_route_rejects_another_session() -> None:
    from types import SimpleNamespace

    from app.api.chat_stream import ChatRun, ChatRunRegistry, stop_chat_run
    from app.services.errors import NotFoundError

    registry = ChatRunRegistry()
    run = ChatRun(
        turn_id="turn-stop-owner",
        conversation_id="conversation-1",
        client_message_id="message-1",
        demo_session_id=1,
    )
    registry.add(run)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(chat_runs=registry)))

    with pytest.raises(NotFoundError):
        await stop_chat_run("turn-stop-owner", request, SimpleNamespace(id=2))
