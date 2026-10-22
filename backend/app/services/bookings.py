"""Booking reads and transactional, idempotent booking creation."""

from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import select
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
                .where(PatientBooking.patient_id == patient_id)
            ).all()
            views = [
                _booking_view(booking, doctor, treatment, clinic)
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

    async def create_from_draft(
        self,
        draft_id: str,
        draft_version: int,
        idempotency_key: str,
        request_hash: str,
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

            existing = _booking_by_key(session, idempotency_key)
            if existing is not None:
                view, _created = self._recover(session, existing, request_hash)
                self._record_recovery(session, draft, view)
                return view, False

            if draft.booking_id is not None:
                existing = session.get(PatientBooking, draft.booking_id)
                if existing is not None:
                    view, _created = self._recover(session, existing, request_hash)
                    self._record_recovery(session, draft, view)
                    return view, False

            if (
                draft.status != DraftStatus.BOOKING_IN_PROGRESS.value
                or draft.authorized_turn_id is None
            ):
                raise ConfirmationRequiredError()

            now = self._clock.now()
            doctor, treatment = _validate_draft(session, draft, now)

            booking = self._insert_booking(session, draft, idempotency_key, request_hash, now)
            session.flush()
            view = _booking_view(
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
            if recovered is not None:
                view, _created = self._recover(session, recovered, request_hash)
                if draft is not None:
                    self._record_recovery(session, draft, view)
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

    def _record_recovery(self, session: Session, draft: BookingDraft, view: BookingView) -> None:
        changed = False
        if draft.status != DraftStatus.BOOKED.value:
            draft.status = DraftStatus.BOOKED.value
            changed = True
        if draft.booking_id != view.booking_id:
            draft.booking_id = view.booking_id
            changed = True
        if changed:
            draft.updated_at = self._clock.now()
            session.commit()

    @staticmethod
    def _recover(
        session: Session, booking: PatientBooking, request_hash: str
    ) -> tuple[BookingView, bool]:
        if booking.request_hash != request_hash:
            raise IdempotencyConflictError()
        doctor = session.get(Doctor, booking.doctor_id)
        treatment = session.get(Treatment, booking.treatment_id)
        if doctor is None or treatment is None:
            raise InvalidBookingDetailsError("The recorded booking references missing data.")
        clinic = session.get(Clinic, doctor.clinic_id)
        return _booking_view(booking, doctor, treatment, clinic), False


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


def _booking_view(
    booking: PatientBooking,
    doctor: Doctor,
    treatment: Treatment,
    clinic: Clinic | None,
) -> BookingView:
    clinic_id = clinic.clinic_id if clinic is not None else doctor.clinic_id
    clinic_name = clinic.clinic_name if clinic is not None else ""
    return BookingView(
        booking_id=booking.booking_id,
        patient_id=booking.patient_id,
        doctor_id=doctor.doctor_id,
        doctor_name=doctor.full_name,
        treatment_id=treatment.treatment_id,
        treatment_name=treatment.treatment_name,
        clinic_id=clinic_id,
        clinic_name=clinic_name,
        local_date=booking.booking_date.isoformat(),
        local_time=booking.booking_time.strftime("%H:%M"),
        timezone=booking.timezone,
        starts_at_utc=booking.starts_at_utc,
        status=booking.status,
        notes=booking.notes,
    )
