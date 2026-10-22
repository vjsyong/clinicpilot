from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from app.auth.sessions import SessionService
from app.clock import FrozenClock
from app.contracts import PATIENT_ID, DraftStatus
from app.db.models import BookingDraft, PatientBooking
from app.db.session import create_session_factory
from app.services.bookings import BookingService
from app.services.catalog import resolve_local_utc
from app.services.conversations import ConversationService
from app.services.drafts import DraftService
from app.services.errors import (
    ConfirmationRequiredError,
    DraftVersionConflictError,
    ForbiddenError,
    IdempotencyConflictError,
    InvalidBookingDetailsError,
)
from app.services.hashing import booking_request_hash
from sqlalchemy import func, select
from tests.conftest import DBHarness


def _drafts(db: DBHarness, clock: FrozenClock) -> DraftService:
    return DraftService(db.session_factory, clock, db.settings)


def _bookings(db: DBHarness, clock: FrozenClock) -> BookingService:
    return BookingService(db.session_factory, clock, db.settings)


async def _new_conversation(
    db: DBHarness, clock: FrozenClock, patient_id: str = PATIENT_ID
) -> tuple[Any, str]:
    sessions = SessionService(db.session_factory, clock, db.settings)
    _token, session = await sessions.create_session()
    conversations = ConversationService(db.session_factory, clock)
    conversation_id = await conversations.create_conversation(session.id, patient_id)
    return session, conversation_id


async def _complete(
    drafts: DraftService,
    conversation_id: str,
    *,
    doctor: str = "D104",
    treatment: str = "T005",
    local_date: str = "2026-11-17",
    local_time: str = "15:00",
):
    update = await drafts.update(
        conversation_id,
        {
            "doctor_id": doctor,
            "treatment_id": treatment,
            "local_date": local_date,
            "local_time": local_time,
        },
    )
    assert update.errors == []
    assert update.draft is not None
    assert update.draft.status == DraftStatus.AWAITING_CONFIRMATION.value
    return update.draft


async def _authorized(
    drafts: DraftService, conversation_id: str, *, message_id: str = "assistant-1"
):
    draft = await _complete(drafts, conversation_id)
    await drafts.mark_presented(conversation_id, message_id, draft.version)
    return await drafts.authorize(conversation_id, "turn-1")


@pytest.mark.asyncio
async def test_draft_progresses_from_collecting_to_awaiting(
    db: DBHarness, frozen_clock: FrozenClock
) -> None:
    _session, conversation_id = await _new_conversation(db, frozen_clock)
    drafts = _drafts(db, frozen_clock)

    first = await drafts.update(conversation_id, {"doctor_id": "D104"})
    assert first.changed is True
    assert first.draft is not None
    assert first.draft.version == 1
    assert first.draft.status == DraftStatus.COLLECTING_DETAILS.value
    assert first.missing_fields == ["treatment_id", "local_date", "local_time"]
    assert first.draft.doctor_name == "Dr. James Wilson"
    assert first.draft.clinic_id == "C001"
    assert first.draft.timezone == "America/New_York"

    second = await drafts.update(conversation_id, {"treatment_id": "T005"})
    assert second.draft is not None
    assert second.draft.version == 2
    assert second.draft.status == DraftStatus.COLLECTING_DETAILS.value

    third = await drafts.update(
        conversation_id, {"local_date": "2026-11-17", "local_time": "15:00"}
    )
    assert third.draft is not None
    assert third.draft.version == 3
    assert third.draft.status == DraftStatus.AWAITING_CONFIRMATION.value
    assert third.draft.missing_fields == []
    assert third.draft.treatment_name == "Joint & Pain Consultation"
    assert third.draft.timezone == "America/New_York"
    assert third.draft.starts_at_utc == datetime(2026, 11, 17, 20, 0, tzinfo=UTC)

    unchanged = await drafts.update(
        conversation_id, {"local_date": "2026-11-17", "local_time": "15:00"}
    )
    assert unchanged.changed is False
    assert unchanged.draft is not None
    assert unchanged.draft.version == 3


@pytest.mark.asyncio
async def test_correction_bumps_version_and_requires_reconfirmation(
    db: DBHarness, frozen_clock: FrozenClock
) -> None:
    _session, conversation_id = await _new_conversation(db, frozen_clock)
    drafts = _drafts(db, frozen_clock)
    draft = await _complete(drafts, conversation_id)
    await drafts.mark_presented(conversation_id, "assistant-1", draft.version)

    corrected = await drafts.update(conversation_id, {"local_date": "2026-11-18"})
    assert corrected.changed is True
    assert corrected.draft is not None
    assert corrected.draft.version == draft.version + 1
    assert corrected.draft.status == DraftStatus.AWAITING_CONFIRMATION.value

    with pytest.raises(ConfirmationRequiredError):
        await drafts.authorize(conversation_id, "turn-2")

    await drafts.mark_presented(conversation_id, "assistant-2", corrected.draft.version)
    authorized = await drafts.authorize(conversation_id, "turn-2")
    assert authorized.status == DraftStatus.BOOKING_IN_PROGRESS.value


@pytest.mark.asyncio
async def test_draft_validation_rejects_bad_values(
    db: DBHarness, frozen_clock: FrozenClock
) -> None:
    _session, conversation_id = await _new_conversation(db, frozen_clock)
    drafts = _drafts(db, frozen_clock)

    unknown = await drafts.update(conversation_id, {"doctor_id": "D999"})
    assert unknown.changed is False
    assert unknown.draft is None
    assert any("D999" in error for error in unknown.errors)

    await drafts.update(conversation_id, {"doctor_id": "D101"})
    incompatible = await drafts.update(conversation_id, {"treatment_id": "T002"})
    assert incompatible.changed is False
    assert incompatible.draft is not None
    assert incompatible.draft.version == 1
    assert any("does not offer" in error for error in incompatible.errors)

    missing_treatment = await drafts.update(conversation_id, {"treatment_id": "T999"})
    assert any("T999" in error for error in missing_treatment.errors)

    bad_date = await drafts.update(conversation_id, {"local_date": "11/17/2026"})
    assert any("YYYY-MM-DD" in error for error in bad_date.errors)

    bad_time = await drafts.update(conversation_id, {"local_time": "3pm"})
    assert any("HH:MM" in error for error in bad_time.errors)

    past = await drafts.update(
        conversation_id,
        {
            "treatment_id": "T001",
            "local_date": "2026-10-01",
            "local_time": "10:00",
        },
    )
    assert any("past" in error for error in past.errors)

    nonexistent = await drafts.update(
        conversation_id,
        {
            "treatment_id": "T001",
            "local_date": "2027-03-14",
            "local_time": "02:30",
        },
    )
    assert any("does not exist" in error for error in nonexistent.errors)

    ambiguous = await drafts.update(
        conversation_id,
        {
            "treatment_id": "T001",
            "local_date": "2026-11-01",
            "local_time": "01:30",
        },
    )
    assert any("ambiguous" in error for error in ambiguous.errors)


@pytest.mark.asyncio
async def test_interruption_clears_presented_confirmation(
    db: DBHarness, frozen_clock: FrozenClock
) -> None:
    _session, conversation_id = await _new_conversation(db, frozen_clock)
    drafts = _drafts(db, frozen_clock)
    draft = await _complete(drafts, conversation_id)
    await drafts.mark_presented(conversation_id, "assistant-1", draft.version)

    await drafts.clear_presented(conversation_id)
    with pytest.raises(ConfirmationRequiredError):
        await drafts.authorize(conversation_id, "turn-1")

    await drafts.mark_presented(conversation_id, "assistant-2", draft.version)
    authorized = await drafts.authorize(conversation_id, "turn-2")
    assert authorized.status == DraftStatus.BOOKING_IN_PROGRESS.value


@pytest.mark.asyncio
async def test_doctor_change_re_resolves_clinic_timezone(
    db: DBHarness, frozen_clock: FrozenClock
) -> None:
    _session, conversation_id = await _new_conversation(db, frozen_clock)
    drafts = _drafts(db, frozen_clock)
    draft = await _complete(drafts, conversation_id)
    assert draft.timezone == "America/New_York"

    changed = await drafts.update(conversation_id, {"doctor_id": "D103", "treatment_id": "T003"})
    assert changed.errors == []
    assert changed.draft is not None
    assert changed.draft.version == draft.version + 1
    assert changed.draft.clinic_id == "C002"
    assert changed.draft.timezone == "America/Los_Angeles"
    assert changed.draft.starts_at_utc == datetime(2026, 11, 17, 23, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_abandon_and_mark_failed(db: DBHarness, frozen_clock: FrozenClock) -> None:
    _session, conversation_id = await _new_conversation(db, frozen_clock)
    drafts = _drafts(db, frozen_clock)
    draft = await _complete(drafts, conversation_id)
    await drafts.mark_presented(conversation_id, "assistant-1", draft.version)
    await drafts.abandon(conversation_id)
    assert await drafts.get(conversation_id) is None

    _session2, conversation_id2 = await _new_conversation(db, frozen_clock)
    draft2 = await _complete(drafts, conversation_id2)
    await drafts.mark_presented(conversation_id2, "assistant-1", draft2.version)
    await drafts.authorize(conversation_id2, "turn-1")
    await drafts.mark_failed(conversation_id2)
    restored = await drafts.get(conversation_id2)
    assert restored is not None
    assert restored.status == DraftStatus.AWAITING_CONFIRMATION.value
    authorized = await drafts.authorize(conversation_id2, "turn-2")
    assert authorized.status == DraftStatus.BOOKING_IN_PROGRESS.value


@pytest.mark.asyncio
async def test_create_booking_is_idempotent_and_persisted(
    db: DBHarness, frozen_clock: FrozenClock
) -> None:
    _session, conversation_id = await _new_conversation(db, frozen_clock)
    drafts = _drafts(db, frozen_clock)
    bookings = _bookings(db, frozen_clock)
    draft = await _authorized(drafts, conversation_id)
    key = f"booking:{draft.draft_id}:v{draft.version}"
    request_hash = booking_request_hash(draft.draft_id, draft.version)

    view, created = await bookings.create_from_draft(
        draft.draft_id, draft.version, key, request_hash
    )
    assert created is True
    assert view.booking_id == "B1005"
    assert view.patient_id == PATIENT_ID
    assert view.starts_at_utc == datetime(2026, 11, 17, 20, 0, tzinfo=UTC)

    replay, replayed = await bookings.create_from_draft(
        draft.draft_id, draft.version, key, request_hash
    )
    assert replayed is False
    assert replay.booking_id == view.booking_id

    listed = await bookings.list_bookings()
    assert listed[0].booking_id == "B1001"
    assert any(item.booking_id == "B1005" for item in listed)

    with pytest.raises(IdempotencyConflictError):
        await bookings.create_from_draft(
            draft.draft_id, draft.version, key, "different-request-hash"
        )

    booked_view = await drafts.get(conversation_id)
    assert booked_view is not None
    assert booked_view.status == DraftStatus.BOOKED.value

    with db.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(PatientBooking)) == 5
        stored_draft = session.get(BookingDraft, draft.draft_id)
        assert stored_draft is not None
        assert stored_draft.status == DraftStatus.BOOKED.value
        assert stored_draft.booking_id == "B1005"


@pytest.mark.asyncio
async def test_create_requires_confirmation_and_matching_version(
    db: DBHarness, frozen_clock: FrozenClock
) -> None:
    _session, conversation_id = await _new_conversation(db, frozen_clock)
    drafts = _drafts(db, frozen_clock)
    bookings = _bookings(db, frozen_clock)
    draft = await _complete(drafts, conversation_id)
    key = f"booking:{draft.draft_id}:v{draft.version}"
    request_hash = booking_request_hash(draft.draft_id, draft.version)

    with pytest.raises(ConfirmationRequiredError):
        await bookings.create_from_draft(draft.draft_id, draft.version, key, request_hash)

    wrong_version = draft.version + 1
    with pytest.raises(DraftVersionConflictError):
        await bookings.create_from_draft(
            draft.draft_id,
            wrong_version,
            f"booking:{draft.draft_id}:v{wrong_version}",
            booking_request_hash(draft.draft_id, wrong_version),
        )


@pytest.mark.asyncio
async def test_create_rejects_past_pairing_and_unknown_doctor(
    db: DBHarness, frozen_clock: FrozenClock
) -> None:
    _session, conversation_id = await _new_conversation(db, frozen_clock)
    drafts = _drafts(db, frozen_clock)
    bookings = _bookings(db, frozen_clock)
    draft = await _authorized(drafts, conversation_id)
    key = f"booking:{draft.draft_id}:v{draft.version}"
    request_hash = booking_request_hash(draft.draft_id, draft.version)

    frozen_clock.current = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
    with pytest.raises(InvalidBookingDetailsError):
        await bookings.create_from_draft(draft.draft_id, draft.version, key, request_hash)
    frozen_clock.current = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)

    with db.session_factory() as session:
        stored = session.get(BookingDraft, draft.draft_id)
        assert stored is not None
        stored.treatment_id = "T002"
        session.commit()

    with pytest.raises(InvalidBookingDetailsError):
        await bookings.create_from_draft(draft.draft_id, draft.version, key, request_hash)

    with db.session_factory() as session:
        stored = session.get(BookingDraft, draft.draft_id)
        assert stored is not None
        stored.treatment_id = "T005"
        session.commit()

    with db.engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.exec_driver_sql(
            "UPDATE booking_drafts SET doctor_id = 'D999' WHERE id = ?",
            (draft.draft_id,),
        )
        connection.commit()

    with pytest.raises(InvalidBookingDetailsError):
        await bookings.create_from_draft(draft.draft_id, draft.version, key, request_hash)


@pytest.mark.asyncio
async def test_booking_service_rejects_foreign_patient(
    db: DBHarness, frozen_clock: FrozenClock
) -> None:
    _session, conversation_id = await _new_conversation(db, frozen_clock, patient_id="P002")
    now = frozen_clock.now()
    draft_id = str(uuid.uuid4())
    starts = resolve_local_utc("2026-11-17", "15:00", "America/New_York")
    with db.session_factory() as session:
        session.add(
            BookingDraft(
                id=draft_id,
                conversation_id=conversation_id,
                version=1,
                status=DraftStatus.BOOKING_IN_PROGRESS.value,
                doctor_id="D104",
                treatment_id="T005",
                local_date="2026-11-17",
                local_time="15:00",
                timezone="America/New_York",
                starts_at_utc=starts,
                notes=None,
                confirmation_message_id="assistant-1",
                confirmation_version=1,
                authorized_turn_id="turn-1",
                booking_id=None,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()

    bookings = _bookings(db, frozen_clock)
    with pytest.raises(ForbiddenError):
        await bookings.create_from_draft(draft_id, 1, f"booking:{draft_id}:v1", "hash")


@pytest.mark.asyncio
async def test_failed_insert_rolls_back_without_partial_booking(
    db: DBHarness,
    frozen_clock: FrozenClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _session, conversation_id = await _new_conversation(db, frozen_clock)
    drafts = _drafts(db, frozen_clock)
    bookings = _bookings(db, frozen_clock)
    draft = await _authorized(drafts, conversation_id)
    key = f"booking:{draft.draft_id}:v{draft.version}"
    request_hash = booking_request_hash(draft.draft_id, draft.version)

    def boom(
        self: BookingService,
        session: Any,
        draft_row: Any,
        idempotency_key: str,
        request_hash_value: str,
        now: datetime,
    ) -> Any:
        BookingService._insert_booking(
            self, session, draft_row, idempotency_key, request_hash_value, now
        )
        session.flush()
        raise RuntimeError("forced failure after flush")

    monkeypatch.setattr(BookingService, "_insert_booking", boom)

    with pytest.raises(RuntimeError):
        await bookings.create_from_draft(draft.draft_id, draft.version, key, request_hash)

    with db.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(PatientBooking)) == 4
        stored = session.get(BookingDraft, draft.draft_id)
        assert stored is not None
        assert stored.status == DraftStatus.BOOKING_IN_PROGRESS.value
        assert stored.booking_id is None


@pytest.mark.asyncio
async def test_restart_engine_retains_booking(db: DBHarness, frozen_clock: FrozenClock) -> None:
    _session, conversation_id = await _new_conversation(db, frozen_clock)
    drafts = _drafts(db, frozen_clock)
    bookings = _bookings(db, frozen_clock)
    draft = await _authorized(drafts, conversation_id)
    key = f"booking:{draft.draft_id}:v{draft.version}"
    view, created = await bookings.create_from_draft(
        draft.draft_id,
        draft.version,
        key,
        booking_request_hash(draft.draft_id, draft.version),
    )
    assert created is True

    db.engine.dispose()
    engine, session_factory = create_session_factory(db.settings)
    try:
        restarted = BookingService(session_factory, frozen_clock, db.settings)
        listed = await restarted.list_bookings()
        assert any(item.booking_id == view.booking_id for item in listed)
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_conversation_store_persists_and_finds_assistant_message_id(
    db: DBHarness, frozen_clock: FrozenClock
) -> None:
    from app.services.conversations import ConversationRecord

    _session, conversation_id = await _new_conversation(db, frozen_clock)
    conversations = ConversationService(db.session_factory, frozen_clock)
    messages = [
        {"role": "user", "content": "hello", "_cp_message_id": "user-1"},
        {"role": "assistant", "content": "hi", "_cp_message_id": "assistant-1"},
        {"role": "tool", "content": "result"},
        {"role": "assistant", "content": "done", "_cp_message_id": "assistant-2"},
    ]
    await conversations.save_messages(conversation_id, messages, frozen_clock.now())

    loaded = await conversations.load_messages(conversation_id)
    assert loaded == messages
    assert await conversations.last_assistant_message_id(conversation_id) == "assistant-2"

    record = await conversations.get_conversation(conversation_id)
    assert isinstance(record, ConversationRecord)
    assert record.id == conversation_id
    assert record.patient_id == PATIENT_ID
