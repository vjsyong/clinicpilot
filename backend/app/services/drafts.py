"""Booking draft persistence, validation, versioning, and authorization."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.contracts import (
    PATIENT_ID,
    BookingDraftView,
    BookingView,
    Clock,
    DraftStatus,
    DraftUpdate,
)
from app.db.models import BookingDraft, Clinic, Conversation, Doctor, Treatment
from app.services.catalog import (
    LocalTimeError,
    clinic_timezone,
    doctor_offers,
    resolve_local_utc,
)
from app.services.errors import (
    ConfirmationRequiredError,
    DraftIncompleteError,
    NotFoundError,
)
from app.settings import Settings

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_MAX_NOTES = 2000

_SLOT_FIELDS = ("doctor_id", "treatment_id", "local_date", "local_time")
_REQUIRED_FIELDS = ("doctor_id", "treatment_id", "local_date", "local_time")
_ALLOWED_FIELDS = {*_SLOT_FIELDS, "notes"}


class DraftService:
    """Implements ``app.contracts.DraftStore``."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        clock: Clock,
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._settings = settings

    async def get(self, conversation_id: str) -> BookingDraftView | None:
        session = self._session_factory()
        try:
            draft = _latest_draft(session, conversation_id, include_booked=True)
            if draft is None:
                return None
            return _view(session, draft)
        finally:
            session.close()

    async def update(self, conversation_id: str, changes: dict[str, Any]) -> DraftUpdate:
        session = self._session_factory()
        try:
            now = self._clock.now()
            conversation = session.get(Conversation, conversation_id)
            if conversation is None:
                raise NotFoundError("Conversation not found.")
            if conversation.patient_id != PATIENT_ID:
                raise NotFoundError("Conversation not found.")

            draft = _latest_active_draft(session, conversation_id)
            unknown = sorted(set(changes) - _ALLOWED_FIELDS)
            if unknown:
                return DraftUpdate(
                    draft=_view(session, draft) if draft is not None else None,
                    missing_fields=_missing(draft),
                    changed=False,
                    errors=[f"Unsupported draft field: {field}" for field in unknown],
                )

            candidate = _candidate(draft)
            for field in _ALLOWED_FIELDS:
                if field in changes:
                    candidate[field] = _normalize(field, changes[field])

            errors, _doctor, _treatment, timezone = _validate(session, candidate, now)
            candidate["timezone"] = timezone
            missing = _missing_values(
                candidate["doctor_id"],
                candidate["treatment_id"],
                candidate["local_date"],
                candidate["local_time"],
                candidate["timezone"],
            )
            if errors:
                return DraftUpdate(
                    draft=_view(session, draft) if draft is not None else None,
                    missing_fields=missing,
                    changed=False,
                    errors=errors,
                )

            candidate["starts_at_utc"] = _starts_at(candidate, timezone)
            if draft is None and not _has_slot_values(candidate):
                return DraftUpdate(
                    draft=None,
                    missing_fields=missing,
                    changed=False,
                )
            changed = draft is None or _differs(draft, candidate, timezone)
            if not changed:
                return DraftUpdate(
                    draft=_view(session, draft) if draft is not None else None,
                    missing_fields=missing,
                    changed=False,
                )

            status = (
                DraftStatus.AWAITING_CONFIRMATION.value
                if not missing
                else DraftStatus.COLLECTING_DETAILS.value
            )
            if draft is None:
                draft = BookingDraft(
                    id=str(uuid.uuid4()),
                    conversation_id=conversation_id,
                    version=1,
                    status=status,
                    created_at=now,
                    updated_at=now,
                )
                session.add(draft)
            else:
                draft.version += 1
                draft.status = status
                draft.updated_at = now
                draft.confirmation_message_id = None
                draft.confirmation_version = None
                draft.authorized_turn_id = None

            draft.doctor_id = candidate["doctor_id"]
            draft.treatment_id = candidate["treatment_id"]
            draft.local_date = candidate["local_date"]
            draft.local_time = candidate["local_time"]
            draft.timezone = candidate["timezone"]
            draft.starts_at_utc = candidate["starts_at_utc"]
            draft.notes = candidate["notes"]
            session.commit()

            return DraftUpdate(
                draft=_view(session, draft),
                missing_fields=missing,
                changed=True,
            )
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    async def abandon(self, conversation_id: str) -> None:
        session = self._session_factory()
        try:
            draft = _latest_active_draft(session, conversation_id)
            if draft is None:
                return
            draft.status = DraftStatus.CANCELLED.value
            draft.confirmation_message_id = None
            draft.confirmation_version = None
            draft.authorized_turn_id = None
            draft.updated_at = self._clock.now()
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    async def mark_presented(
        self, conversation_id: str, assistant_message_id: str, version: int
    ) -> None:
        session = self._session_factory()
        try:
            draft = _latest_active_draft(session, conversation_id)
            if draft is None:
                return
            if draft.version != version:
                return
            if draft.status != DraftStatus.AWAITING_CONFIRMATION.value:
                return
            draft.confirmation_message_id = assistant_message_id
            draft.confirmation_version = version
            draft.updated_at = self._clock.now()
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    async def clear_presented(self, conversation_id: str) -> None:
        session = self._session_factory()
        try:
            draft = _latest_active_draft(session, conversation_id)
            if draft is None:
                return
            draft.confirmation_message_id = None
            draft.confirmation_version = None
            draft.updated_at = self._clock.now()
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    async def authorize(self, conversation_id: str, turn_id: str) -> BookingDraftView:
        session = self._session_factory()
        try:
            draft = _latest_active_draft(session, conversation_id)
            if draft is None:
                raise NotFoundError("Booking draft not found.")
            if _missing(draft):
                raise DraftIncompleteError()
            if draft.status != DraftStatus.AWAITING_CONFIRMATION.value:
                raise ConfirmationRequiredError(
                    "The booking summary must be awaiting confirmation."
                )
            if draft.confirmation_message_id is None or draft.confirmation_version != draft.version:
                raise ConfirmationRequiredError(
                    "The current booking summary has not been presented."
                )
            draft.authorized_turn_id = turn_id
            draft.status = DraftStatus.BOOKING_IN_PROGRESS.value
            draft.updated_at = self._clock.now()
            session.commit()
            return _view(session, draft)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    async def mark_booked(self, conversation_id: str, booking: BookingView) -> None:
        session = self._session_factory()
        try:
            draft = _latest_active_draft(session, conversation_id)
            if draft is None:
                raise NotFoundError("Booking draft not found.")
            draft.booking_id = booking.booking_id
            draft.status = DraftStatus.BOOKED.value
            draft.updated_at = self._clock.now()
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    async def mark_failed(self, conversation_id: str) -> None:
        session = self._session_factory()
        try:
            draft = _latest_active_draft(session, conversation_id)
            if draft is None:
                return
            draft.status = (
                DraftStatus.AWAITING_CONFIRMATION.value
                if not _missing(draft)
                else DraftStatus.COLLECTING_DETAILS.value
            )
            draft.authorized_turn_id = None
            draft.updated_at = self._clock.now()
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


def _latest_draft(
    session: Session, conversation_id: str, *, include_booked: bool
) -> BookingDraft | None:
    excluded = [DraftStatus.CANCELLED.value]
    if not include_booked:
        excluded.append(DraftStatus.BOOKED.value)
    return session.scalar(
        select(BookingDraft)
        .where(
            BookingDraft.conversation_id == conversation_id,
            BookingDraft.status.not_in(excluded),
        )
        .order_by(BookingDraft.created_at.desc(), BookingDraft.id.desc())
        .limit(1)
    )


def _latest_active_draft(session: Session, conversation_id: str) -> BookingDraft | None:
    return _latest_draft(session, conversation_id, include_booked=False)


def _candidate(draft: BookingDraft | None) -> dict[str, Any]:
    if draft is None:
        return {
            "doctor_id": None,
            "treatment_id": None,
            "local_date": None,
            "local_time": None,
            "timezone": None,
            "notes": None,
        }
    return {
        "doctor_id": draft.doctor_id,
        "treatment_id": draft.treatment_id,
        "local_date": draft.local_date,
        "local_time": draft.local_time,
        "timezone": draft.timezone,
        "notes": draft.notes,
    }


def _normalize(field: str, value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    value = value.strip()
    if field == "notes":
        return value or None
    return value or None


def _validate(
    session: Session, candidate: dict[str, Any], now: datetime
) -> tuple[list[str], Doctor | None, Treatment | None, str | None]:
    errors: list[str] = []
    doctor: Doctor | None = None
    treatment: Treatment | None = None
    timezone = candidate["timezone"]

    doctor_id = candidate["doctor_id"]
    if doctor_id is not None:
        doctor = session.get(Doctor, doctor_id)
        if doctor is None:
            errors.append(f"Doctor {doctor_id} was not found.")
        else:
            try:
                timezone = clinic_timezone(doctor.clinic_id)
            except LocalTimeError as exc:
                errors.append(str(exc))
                timezone = None
    else:
        timezone = None

    treatment_id = candidate["treatment_id"]
    if treatment_id is not None:
        treatment = session.get(Treatment, treatment_id)
        if treatment is None:
            errors.append(f"Treatment {treatment_id} was not found.")

    if (
        doctor is not None
        and treatment is not None
        and not doctor_offers(doctor.doctor_id, treatment.treatment_id)
    ):
        errors.append(f"{doctor.full_name} does not offer {treatment.treatment_name}.")

    local_date = candidate["local_date"]
    if local_date is not None and not _DATE_RE.fullmatch(local_date):
        errors.append("Use a date in YYYY-MM-DD format.")
    elif local_date is not None:
        try:
            datetime.strptime(local_date, "%Y-%m-%d")
        except ValueError:
            errors.append("Use a valid calendar date in YYYY-MM-DD format.")

    local_time = candidate["local_time"]
    if local_time is not None and not _TIME_RE.fullmatch(local_time):
        errors.append("Use a 24-hour time in HH:MM format.")

    notes = candidate["notes"]
    if notes is not None and len(notes) > _MAX_NOTES:
        errors.append(f"Notes must be {_MAX_NOTES} characters or fewer.")

    if not errors and local_date is not None and local_time is not None and timezone is not None:
        try:
            starts_at = resolve_local_utc(local_date, local_time, timezone)
        except LocalTimeError as exc:
            errors.append(str(exc))
        else:
            if starts_at <= now:
                errors.append("The requested appointment time is in the past.")

    return errors, doctor, treatment, timezone


def _has_slot_values(candidate: dict[str, Any]) -> bool:
    return bool(candidate["notes"]) or any(candidate[field] for field in _SLOT_FIELDS)


def _starts_at(candidate: dict[str, Any], timezone: str | None) -> datetime | None:
    local_date = candidate["local_date"]
    local_time = candidate["local_time"]
    if local_date is None or local_time is None or timezone is None:
        return None
    try:
        return resolve_local_utc(local_date, local_time, timezone)
    except LocalTimeError:
        return None


def _differs(draft: BookingDraft, candidate: dict[str, Any], timezone: str | None) -> bool:
    candidate_start = _starts_at(candidate, timezone)
    return any(
        [
            draft.doctor_id != candidate["doctor_id"],
            draft.treatment_id != candidate["treatment_id"],
            draft.local_date != candidate["local_date"],
            draft.local_time != candidate["local_time"],
            draft.timezone != timezone,
            draft.notes != candidate["notes"],
            draft.starts_at_utc != candidate_start,
        ]
    )


def _missing(draft: BookingDraft | None) -> list[str]:
    if draft is None:
        return list(_REQUIRED_FIELDS)
    return _missing_values(
        draft.doctor_id,
        draft.treatment_id,
        draft.local_date,
        draft.local_time,
        draft.timezone,
    )


def _missing_values(
    doctor_id: str | None,
    treatment_id: str | None,
    local_date: str | None,
    local_time: str | None,
    timezone: str | None,
) -> list[str]:
    values = {
        "doctor_id": doctor_id,
        "treatment_id": treatment_id,
        "local_date": local_date,
        "local_time": local_time,
    }
    missing = [field for field, value in values.items() if not value]
    if not timezone:
        missing.append("timezone")
    return missing


def _view(session: Session, draft: BookingDraft) -> BookingDraftView:
    doctor: Doctor | None = None
    treatment: Treatment | None = None
    clinic: Clinic | None = None
    if draft.doctor_id:
        doctor = session.get(Doctor, draft.doctor_id)
    if draft.treatment_id:
        treatment = session.get(Treatment, draft.treatment_id)
    if doctor is not None:
        clinic = session.get(Clinic, doctor.clinic_id)
    return BookingDraftView(
        draft_id=draft.id,
        version=draft.version,
        status=draft.status,
        doctor_id=draft.doctor_id,
        doctor_name=doctor.full_name if doctor else None,
        treatment_id=draft.treatment_id,
        treatment_name=treatment.treatment_name if treatment else None,
        clinic_id=clinic.clinic_id if clinic else None,
        clinic_name=clinic.clinic_name if clinic else None,
        local_date=draft.local_date,
        local_time=draft.local_time,
        timezone=draft.timezone,
        starts_at_utc=draft.starts_at_utc,
        notes=draft.notes,
        missing_fields=_missing(draft),
    )
