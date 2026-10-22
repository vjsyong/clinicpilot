from __future__ import annotations

import hashlib

import httpx
from app.agent.controller import AgentController
from app.agent.tools import RestBookingApi
from app.api.bookings import router as bookings_router
from app.api.errors import install_error_handlers
from app.clock import FrozenClock
from app.contracts import PATIENT_ID, DraftStatus, TurnContext
from app.db.models import BookingDraft, DemoSession, PatientBooking
from app.services.conversations import ConversationService
from app.services.drafts import DraftService
from fastapi import FastAPI
from sqlalchemy import select
from tests.agent.fakes import (
    FakeIndex,
    FakeModelClient,
    text_response,
    tool_call,
    tool_response,
)
from tests.conftest import DBHarness


def _ctx(conversation_id: str, text: str, turn_id: str, clock: FrozenClock) -> TurnContext:
    return TurnContext(
        conversation_id=conversation_id,
        turn_id=turn_id,
        demo_session_id="1",
        patient_id=PATIENT_ID,
        user_text=text,
        now=clock.now(),
    )


async def test_real_draft_service_presents_then_authorizes_once(
    db: DBHarness, frozen_clock: FrozenClock
) -> None:
    with db.session_factory() as session:
        session.add(
            DemoSession(
                id=1,
                token_hash=hashlib.sha256(b"agent-test").hexdigest(),
                created_at=frozen_clock.now(),
                expires_at=frozen_clock.now(),
            )
        )
        session.commit()

    conversations = ConversationService(db.session_factory, frozen_clock)
    drafts = DraftService(db.session_factory, frozen_clock, db.settings)
    conversation_id = await conversations.create_conversation(1, PATIENT_ID)

    internal_app = FastAPI()
    internal_app.state.settings = db.settings
    internal_app.state.clock = frozen_clock
    internal_app.state.session_factory = db.session_factory
    install_error_handlers(internal_app)
    internal_app.include_router(bookings_router)

    model = FakeModelClient(
        [
            tool_response(
                tool_call(
                    "update_booking_draft",
                    '{"doctor_id":"D101","treatment_id":"T001",'
                    '"local_date":"2026-11-05","local_time":"09:00"}',
                )
            ),
            text_response("The details are ready."),
            text_response("Booking it now."),
        ]
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=internal_app),
        base_url=db.settings.internal_api_base_url,
    ) as client:
        api = RestBookingApi(db.settings, client=client)
        controller = AgentController(
            settings=db.settings,
            clock=frozen_clock,
            model_client=model,
            index=FakeIndex(),
            drafts=drafts,
            conversations=conversations,
            booking_api=api,
            patient_context_loader=lambda _patient_id: "P001 allergies: Penicillin",
        )

        first = await controller.handle_turn(
            _ctx(
                conversation_id,
                "Book a general checkup with Dr. Sarah Jenkins on 2026-11-05 at 09:00.",
                "turn-1",
                frozen_clock,
            )
        )

        assert first.booking_draft is not None
        assert first.booking_draft.status == DraftStatus.AWAITING_CONFIRMATION.value
        assert "Booking summary:" in first.assistant_message
        assert first.events == []

        second = await controller.handle_turn(
            _ctx(conversation_id, "yes please", "turn-2", frozen_clock)
        )

        assert len(second.events) == 1
        assert second.events[0].type == "booking_created"
        assert second.events[0].booking is not None
        assert second.booking_draft is not None
        assert second.booking_draft.status == DraftStatus.BOOKED.value
        booking_id = second.events[0].booking.booking_id
        assert booking_id in second.assistant_message
        assert await conversations.last_assistant_message_id(conversation_id) is not None

    with db.session_factory() as session:
        draft_row = session.scalars(
            select(BookingDraft).where(BookingDraft.conversation_id == conversation_id)
        ).one()
        assert draft_row.status == DraftStatus.BOOKED.value
        assert draft_row.booking_id == booking_id
        assert draft_row.authorized_turn_id == "turn-2"
        booking_row = session.get(PatientBooking, booking_id)
        assert booking_row is not None
        assert booking_row.idempotency_key == (f"booking:{draft_row.id}:v{draft_row.version}")
