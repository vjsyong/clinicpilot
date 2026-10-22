"""Conservative recovery for turns interrupted by a process stop.

The MVP runs one backend worker. At startup, any turn still marked in progress
belongs to a previous process. If its authorized draft has a committed booking,
the original response is reconstructed from persisted canonical data; otherwise
the turn is made retryable without repeating a write.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.contracts import ChatResponse, ChatTurnStatus, Clock, DraftStatus, Event
from app.db.models import BookingDraft, ChatTurn, PatientBooking
from app.services.booking_views import booking_success_text, booking_view_from_draft
from app.services.drafts import draft_view

logger = logging.getLogger("clinicpilot.recovery")


def recover_interrupted_turns(session_factory: sessionmaker[Session], clock: Clock) -> int:
    """Recover or release every turn left in progress by a previous process."""
    session = session_factory()
    recovered = 0
    try:
        turns = session.scalars(
            select(ChatTurn).where(ChatTurn.status == ChatTurnStatus.IN_PROGRESS.value)
        ).all()
        for turn in turns:
            if _recover_turn(session, turn, clock):
                recovered += 1
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return recovered


def _recover_turn(session: Session, turn: ChatTurn, clock: Clock) -> bool:
    draft = session.scalar(
        select(BookingDraft)
        .where(
            BookingDraft.conversation_id == turn.conversation_id,
            BookingDraft.authorized_turn_id == turn.id,
        )
        .order_by(BookingDraft.created_at.desc())
        .limit(1)
    )
    if draft is None:
        _fail_turn(turn, clock)
        return False

    booking_row = _committed_booking(session, draft)
    if booking_row is None:
        _release_draft(draft, session, clock)
        _fail_turn(turn, clock)
        return False

    draft.status = DraftStatus.BOOKED.value
    draft.booking_id = booking_row.booking_id
    draft.updated_at = clock.now()
    view = draft_view(session, draft)
    booking = booking_view_from_draft(view)
    if booking is None:
        logger.warning(
            "Interrupted turn %s has booking %s but no complete draft projection.",
            turn.id,
            booking_row.booking_id,
        )
        _fail_turn(turn, clock)
        return False

    response = ChatResponse(
        conversation_id=turn.conversation_id,
        message_id=turn.client_message_id,
        assistant_message=booking_success_text(booking),
        sources=[],
        booking_draft=view,
        events=[Event(type="booking_created", booking=booking)],
    )
    turn.status = ChatTurnStatus.COMPLETED.value
    turn.response_json = response.model_dump_json()
    turn.updated_at = clock.now()
    return True


def _committed_booking(session: Session, draft: BookingDraft) -> PatientBooking | None:
    if draft.booking_id is not None:
        booking = session.get(PatientBooking, draft.booking_id)
        if booking is not None:
            return booking
    key = f"booking:{draft.id}:v{draft.version}"
    return session.scalar(select(PatientBooking).where(PatientBooking.idempotency_key == key))


def _release_draft(draft: BookingDraft, session: Session, clock: Clock) -> None:
    view = draft_view(session, draft)
    draft.status = (
        DraftStatus.AWAITING_CONFIRMATION.value
        if not view.missing_fields
        else DraftStatus.COLLECTING_DETAILS.value
    )
    draft.authorized_turn_id = None
    draft.updated_at = clock.now()


def _fail_turn(turn: ChatTurn, clock: Clock) -> None:
    turn.status = ChatTurnStatus.FAILED.value
    turn.response_json = None
    turn.updated_at = clock.now()
