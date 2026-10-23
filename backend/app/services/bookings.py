"""Booking reads and transactional, idempotent booking creation."""

from __future__ import annotations

from datetime import UTC, date, datetime, time

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.contracts import PATIENT_ID, BookingView, Clock, DraftStatus
from app.db.models import (
    BookingDraft,
    Clinic,
    Conversation,
    Doctor,
    PatientBooking,
    Treatment,
)
from app.services.booking_views import booking_view_from_models
from app.services.catalog import (
    LocalTimeError,
    doctor_offers,
    resolve_local_utc,
)
from app.services.errors import (
    ConfirmationRequiredError,
    DraftIncompleteError,
    DraftVersionConflictError,
    ForbiddenError,
    IdempotencyConflictError,
    InvalidBookingDetailsError,
    NotFoundError,
)
from app.services.hashing import canonical_booking_hash
from app.settings import Settings


class BookingService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        clock: Clock,
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._settings = settings

    async def list_bookings(self, patient_id: str = PATIENT_ID) -> list[BookingView]:
        session = self._session_factory()
        try:
            rows = session.execute(
                select(PatientBooking, Doctor, Treatment, Clinic)
                .join(Doctor, PatientBooking.doctor_id == Doctor.doctor_id)
                .join(Treatment, PatientBooking.treatment_id == Treatment.treatment_id)
                .join(Clinic, Doctor.clinic_id == Clinic.clinic_id)
                .where(
                    PatientBooking.patient_id == patient_id,
                    PatientBooking.deleted_at.is_(None),
                )
            ).all()
            views = [
                booking_view_from_models(booking, doctor, treatment, clinic)
                for booking, doctor, treatment, clinic in rows
            ]
        finally:
            session.close()

        now = self._clock.now()
        upcoming = sorted(
            [
                view
                for view in views
                if view.starts_at_utc >= now and view.status.lower() != "cancelled"
            ],
            key=lambda view: view.starts_at_utc,
        )
        other = sorted(
            [
                view
                for view in views
                if view.starts_at_utc < now or view.status.lower() == "cancelled"
            ],
            key=lambda view: view.starts_at_utc,
            reverse=True,
        )
        return upcoming + other

    async def delete_booking(self, booking_id: str, *, reason: str | None = None) -> BookingView:
        session = self._session_factory()
        try:
            booking = session.get(PatientBooking, booking_id)
            if booking is None or booking.patient_id != PATIENT_ID:
                raise NotFoundError("Booking not found.")
            doctor = session.get(Doctor, booking.doctor_id)
            treatment = session.get(Treatment, booking.treatment_id)
            if doctor is None or treatment is None:
                raise InvalidBookingDetailsError("The booking references missing data.")
            clinic = session.get(Clinic, doctor.clinic_id)
            now = self._clock.now()
            changed = False
            if booking.deleted_at is None:
                booking.deleted_at = now
                booking.deleted_reason = (reason or "Deleted from the workbench")[:500]
                changed = True
            drafts = session.scalars(
                select(BookingDraft).where(
                    or_(
                        BookingDraft.booking_id == booking_id,
                        BookingDraft.editing_booking_id == booking_id,
                    )
                )
            ).all()
            for draft in drafts:
                if draft.status == DraftStatus.CANCELLED.value:
                    continue
                draft.status = DraftStatus.CANCELLED.value
                draft.confirmation_message_id = None
                draft.confirmation_version = None
                draft.authorized_turn_id = None
                draft.updated_at = now
                changed = True
            if changed:
                session.commit()
            return booking_view_from_models(booking, doctor, treatment, clinic)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    async def create_from_draft(
        self,
        draft_id: str,
        draft_version: int,
        idempotency_key: str,
    ) -> tuple[BookingView, bool]:
        session = self._session_factory()
        try:
            draft = session.get(BookingDraft, draft_id)
            if draft is None:
                raise NotFoundError("Booking draft not found.")
            conversation = session.get(Conversation, draft.conversation_id)
            if conversation is None or conversation.patient_id != PATIENT_ID:
                raise ForbiddenError("Booking drafts are restricted to the demo patient.")

            if draft.version != draft_version:
                raise DraftVersionConflictError()

            expected_key = f"booking:{draft.id}:v{draft.version}"
            if idempotency_key != expected_key:
                raise IdempotencyConflictError(
                    "The idempotency key does not match this draft version."
                )

            editing_id = draft.editing_booking_id
            if editing_id is not None:
                existing = session.get(PatientBooking, editing_id)
                if existing is None or existing.deleted_at is not None:
                    raise NotFoundError("The booking being edited no longer exists.")
                if draft.status == DraftStatus.BOOKED.value and draft.booking_id == editing_id:
                    doctor = session.get(Doctor, existing.doctor_id)
                    treatment = session.get(Treatment, existing.treatment_id)
                    if doctor is None or treatment is None:
                        raise InvalidBookingDetailsError(
                            "The edited booking references missing data."
                        )
                    return (
                        booking_view_from_models(
                            existing,
                            doctor,
                            treatment,
                            session.get(Clinic, doctor.clinic_id),
                        ),
                        False,
                    )
                if (
                    draft.status != DraftStatus.BOOKING_IN_PROGRESS.value
                    or draft.authorized_turn_id is None
                ):
                    raise ConfirmationRequiredError()
                now = self._clock.now()
                doctor, treatment = _validate_draft(session, draft, now)
                assert draft.doctor_id is not None
                assert draft.treatment_id is not None
                assert draft.local_date is not None
                assert draft.local_time is not None
                assert draft.starts_at_utc is not None
                assert draft.timezone is not None
                existing.doctor_id = draft.doctor_id
                existing.treatment_id = draft.treatment_id
                existing.booking_date = date.fromisoformat(draft.local_date)
                existing.booking_time = time.fromisoformat(draft.local_time)
                existing.starts_at_utc = draft.starts_at_utc
                existing.timezone = draft.timezone
                existing.notes = draft.notes
                existing.status = "Confirmed"
                existing.request_hash = _canonical_hash_for_draft(draft)
                draft.status = DraftStatus.BOOKED.value
                draft.booking_id = editing_id
                draft.updated_at = now
                session.commit()
                return (
                    booking_view_from_models(
                        existing,
                        doctor,
                        treatment,
                        session.get(Clinic, doctor.clinic_id),
                    ),
                    False,
                )

            existing = _booking_by_key(session, idempotency_key)
            if existing is not None:
                view, _created = self._recover(session, existing, draft)
                self._record_recovery(session, draft, existing, view)
                return view, False

            if draft.booking_id is not None:
                existing = session.get(PatientBooking, draft.booking_id)
                if existing is not None:
                    view, _created = self._recover(session, existing, draft)
                    self._record_recovery(session, draft, existing, view)
                    return view, False

            if (
                draft.status != DraftStatus.BOOKING_IN_PROGRESS.value
                or draft.authorized_turn_id is None
            ):
                raise ConfirmationRequiredError()

            now = self._clock.now()
            doctor, treatment = _validate_draft(session, draft, now)
            request_hash = _canonical_hash_for_draft(draft)

            booking = self._insert_booking(session, draft, idempotency_key, request_hash, now)
            session.flush()
            view = booking_view_from_models(
                booking,
                doctor,
                treatment,
                session.get(Clinic, doctor.clinic_id),
            )
            draft.status = DraftStatus.BOOKED.value
            draft.booking_id = booking.booking_id
            draft.updated_at = now
            session.commit()
            return view, True
        except IntegrityError as exc:
            session.rollback()
            recovered = _booking_by_key(session, idempotency_key)
            if recovered is not None and draft is not None:
                view, _created = self._recover(session, recovered, draft)
                self._record_recovery(session, draft, recovered, view)
                return view, False
            raise InvalidBookingDetailsError(
                "The booking could not be saved because it conflicts with an existing record."
            ) from exc
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _insert_booking(
        self,
        session: Session,
        draft: BookingDraft,
        idempotency_key: str,
        request_hash: str,
        now: datetime,
    ) -> PatientBooking:
        assert draft.local_date is not None
        assert draft.local_time is not None
        assert draft.starts_at_utc is not None
        assert draft.timezone is not None
        booking = PatientBooking(
            booking_id=_next_booking_id(session),
            patient_id=PATIENT_ID,
            doctor_id=draft.doctor_id,
            treatment_id=draft.treatment_id,
            booking_date=date.fromisoformat(draft.local_date),
            booking_time=time.fromisoformat(draft.local_time),
            status="Confirmed",
            notes=draft.notes,
            starts_at_utc=draft.starts_at_utc,
            timezone=draft.timezone,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            created_at=now,
        )
        session.add(booking)
        return booking

    def _record_recovery(
        self,
        session: Session,
        draft: BookingDraft,
        booking: PatientBooking,
        view: BookingView,
    ) -> None:
        changed = False
        if draft.status != DraftStatus.BOOKED.value:
            draft.status = DraftStatus.BOOKED.value
            changed = True
        if draft.booking_id != view.booking_id:
            draft.booking_id = view.booking_id
            changed = True
        canonical_hash = _canonical_hash_for_draft(draft)
        if booking.request_hash != canonical_hash:
            booking.request_hash = canonical_hash
            changed = True
        if changed:
            draft.updated_at = self._clock.now()
            session.commit()

    @staticmethod
    def _recover(
        session: Session, booking: PatientBooking, draft: BookingDraft
    ) -> tuple[BookingView, bool]:
        if booking.deleted_at is not None:
            raise IdempotencyConflictError(
                "That booking was cancelled. Start a new booking instead."
            )
        if not _booking_matches_draft(booking, draft):
            raise IdempotencyConflictError()
        doctor = session.get(Doctor, booking.doctor_id)
        treatment = session.get(Treatment, booking.treatment_id)
        if doctor is None or treatment is None:
            raise InvalidBookingDetailsError("The recorded booking references missing data.")
        clinic = session.get(Clinic, doctor.clinic_id)
        return booking_view_from_models(booking, doctor, treatment, clinic), False


def _booking_by_key(session: Session, key: str) -> PatientBooking | None:
    return session.scalar(select(PatientBooking).where(PatientBooking.idempotency_key == key))


def _validate_draft(
    session: Session, draft: BookingDraft, now: datetime
) -> tuple[Doctor, Treatment]:
    if not all(
        [
            draft.doctor_id,
            draft.treatment_id,
            draft.local_date,
            draft.local_time,
            draft.timezone,
            draft.starts_at_utc,
        ]
    ):
        raise DraftIncompleteError()

    assert draft.doctor_id is not None
    assert draft.treatment_id is not None
    assert draft.local_date is not None
    assert draft.local_time is not None
    assert draft.timezone is not None
    assert draft.starts_at_utc is not None

    doctor = session.get(Doctor, draft.doctor_id)
    if doctor is None:
        raise InvalidBookingDetailsError("The selected doctor does not exist.")
    treatment = session.get(Treatment, draft.treatment_id)
    if treatment is None:
        raise InvalidBookingDetailsError("The selected treatment does not exist.")
    if not doctor_offers(doctor.doctor_id, treatment.treatment_id):
        raise InvalidBookingDetailsError(
            f"{doctor.full_name} does not offer {treatment.treatment_name}."
        )
    try:
        date.fromisoformat(draft.local_date)
        time.fromisoformat(draft.local_time)
        resolved = resolve_local_utc(draft.local_date, draft.local_time, draft.timezone)
    except (ValueError, LocalTimeError) as exc:
        raise InvalidBookingDetailsError("The booking date, time, or timezone is invalid.") from exc
    if resolved != draft.starts_at_utc:
        raise InvalidBookingDetailsError(
            "The booking timestamp does not match the selected local time."
        )
    if draft.starts_at_utc <= now:
        raise InvalidBookingDetailsError("The requested appointment time is in the past.")
    return doctor, treatment


def _next_booking_id(session: Session) -> str:
    existing = session.scalars(
        select(PatientBooking.booking_id).where(PatientBooking.booking_id.like("B%"))
    ).all()
    highest = 1000
    for booking_id in existing:
        suffix = booking_id[1:]
        if suffix.isdigit():
            highest = max(highest, int(suffix))
    return f"B{highest + 1}"


def _canonical_hash_for_draft(draft: BookingDraft) -> str:
    if not all(
        [
            draft.doctor_id,
            draft.treatment_id,
            draft.local_date,
            draft.local_time,
            draft.timezone,
            draft.starts_at_utc,
        ]
    ):
        raise DraftIncompleteError()
    assert draft.doctor_id is not None
    assert draft.treatment_id is not None
    assert draft.local_date is not None
    assert draft.local_time is not None
    assert draft.timezone is not None
    assert draft.starts_at_utc is not None
    return canonical_booking_hash(
        patient_id=PATIENT_ID,
        doctor_id=draft.doctor_id,
        treatment_id=draft.treatment_id,
        local_date=draft.local_date,
        local_time=draft.local_time,
        timezone=draft.timezone,
        starts_at_utc=draft.starts_at_utc,
        notes=draft.notes,
    )


def _booking_matches_draft(booking: PatientBooking, draft: BookingDraft) -> bool:
    if not all(
        [
            draft.doctor_id,
            draft.treatment_id,
            draft.local_date,
            draft.local_time,
            draft.timezone,
            draft.starts_at_utc,
        ]
    ):
        return False
    try:
        local_date = date.fromisoformat(draft.local_date)  # type: ignore[arg-type]
        local_time = time.fromisoformat(draft.local_time)  # type: ignore[arg-type]
        draft_start = _as_utc(draft.starts_at_utc)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return (
        booking.patient_id == PATIENT_ID
        and booking.doctor_id == draft.doctor_id
        and booking.treatment_id == draft.treatment_id
        and booking.booking_date == local_date
        and booking.booking_time == local_time
        and booking.timezone == draft.timezone
        and _as_utc(booking.starts_at_utc) == draft_start
        and booking.notes == draft.notes
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
