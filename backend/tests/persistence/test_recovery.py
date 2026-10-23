from __future__ import annotations

import asyncio
from typing import Any

from app.auth.sessions import SessionService
from app.clock import FrozenClock
from app.contracts import PATIENT_ID, ChatTurnStatus, DraftStatus
from app.db.models import BookingDraft, ChatTurn, PatientBooking
from app.main import create_app
from app.services.bookings import BookingService
from app.services.conversations import ConversationService
from app.services.drafts import DraftService
from app.services.hashing import chat_request_hash
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from tests.conftest import DBHarness, FakeController, FakeIndex

SLOTS = {
    "doctor_id": "D104",
    "treatment_id": "T005",
    "local_date": "2026-11-17",
    "local_time": "15:00",
}


def _prepare_turn(db: DBHarness, clock: FrozenClock, *, commit_booking: bool) -> tuple[str, str]:
    sessions = SessionService(db.session_factory, clock, db.settings)
    token, session = asyncio.run(sessions.create_session())
    conversations = ConversationService(db.session_factory, clock)
    conversation_id = asyncio.run(conversations.create_conversation(session.id, PATIENT_ID))
    started = asyncio.run(
        conversations.start_turn(
            conversation_id,
            "client-message",
            chat_request_hash("yes", PATIENT_ID),
        )
    )
    assert started.turn_id is not None
    drafts = DraftService(db.session_factory, clock, db.settings)
    update = asyncio.run(drafts.update(conversation_id, SLOTS))
    assert update.draft is not None
    asyncio.run(drafts.mark_presented(conversation_id, "summary-message", update.draft.version))
    asyncio.run(drafts.authorize(conversation_id, started.turn_id))

    if commit_booking:
        key = f"booking:{update.draft.draft_id}:v{update.draft.version}"
        bookings = BookingService(db.session_factory, clock, db.settings)
        _view, created = asyncio.run(
            bookings.create_from_draft(update.draft.draft_id, update.draft.version, key)
        )
        assert created

    return conversation_id, token


def _send_retry(db: DBHarness, clock: FrozenClock, token: str, conversation_id: str) -> Any:
    asgi = create_app(
        db.settings,
        controller_factory=lambda *_args, **_kwargs: FakeController(),
        index_factory=lambda *_args, **_kwargs: FakeIndex(),
    )
    with TestClient(asgi) as client:
        asgi.app.state.clock = clock
        client.cookies.set("clinicpilot_session", token, path="/demo/")
        return client.post(
            "/demo/api/chat",
            json={
                "conversation_id": conversation_id,
                "message_id": "client-message",
                "message": "yes",
                "patient_id": "P001",
            },
            headers={"Origin": "http://testserver"},
        )


def test_restart_recovers_committed_booking_turn(db: DBHarness, frozen_clock: FrozenClock) -> None:
    conversation_id, token = _prepare_turn(db, frozen_clock, commit_booking=True)

    response = _send_retry(db, frozen_clock, token, conversation_id)

    assert response.status_code == 200
    payload = response.json()
    assert any(event["type"] == "booking_created" for event in payload["events"])
    assert payload["booking_draft"]["status"] == DraftStatus.BOOKED.value
    with db.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(PatientBooking)) == 5
        turn = session.scalar(select(ChatTurn).where(ChatTurn.conversation_id == conversation_id))
        assert turn is not None
        assert turn.status == ChatTurnStatus.COMPLETED.value


def test_restart_releases_uncommitted_in_progress_turn(
    db: DBHarness, frozen_clock: FrozenClock
) -> None:
    conversation_id, token = _prepare_turn(db, frozen_clock, commit_booking=False)

    response = _send_retry(db, frozen_clock, token, conversation_id)

    assert response.status_code == 200
    assert response.json()["assistant_message"] == "echo: yes"
    with db.session_factory() as session:
        turn = session.scalar(select(ChatTurn).where(ChatTurn.conversation_id == conversation_id))
        assert turn is not None
        assert turn.status == ChatTurnStatus.COMPLETED.value
        draft = session.scalar(
            select(BookingDraft).where(BookingDraft.conversation_id == conversation_id)
        )
        assert draft is not None
        assert draft.status == DraftStatus.AWAITING_CONFIRMATION.value
        assert draft.authorized_turn_id is None
