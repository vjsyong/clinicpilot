"""Canonical booking projections and user-facing success text.

Both the persistence layer and the recovery paths build the same representation
from persisted data. Nothing in this module calls a model or generates booking
status from prose.
"""

from __future__ import annotations

from app.contracts import PATIENT_ID, BookingDraftView, BookingView, DraftStatus
from app.db.models import Clinic, Doctor, PatientBooking, Treatment


def booking_view_from_models(
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


def booking_view_from_draft(draft: BookingDraftView) -> BookingView | None:
    """Project a fully booked draft without trusting generated text.

    The draft and booking row are committed in the same transaction, so a draft
    marked booked with a booking id is sufficient evidence that the booking was
    persisted. It does not prove the row is still active: callers that report
    success must exclude tombstoned bookings. Missing canonical fields make the
    projection unavailable rather than inventing values.
    """
    required = (
        draft.booking_id,
        draft.doctor_id,
        draft.doctor_name,
        draft.treatment_id,
        draft.treatment_name,
        draft.clinic_id,
        draft.clinic_name,
        draft.local_date,
        draft.local_time,
        draft.timezone,
        draft.starts_at_utc,
    )
    if draft.status != DraftStatus.BOOKED.value or not all(required):
        return None
    assert draft.booking_id is not None
    assert draft.doctor_id is not None
    assert draft.doctor_name is not None
    assert draft.treatment_id is not None
    assert draft.treatment_name is not None
    assert draft.clinic_id is not None
    assert draft.clinic_name is not None
    assert draft.local_date is not None
    assert draft.local_time is not None
    assert draft.timezone is not None
    assert draft.starts_at_utc is not None
    return BookingView(
        booking_id=draft.booking_id,
        patient_id=PATIENT_ID,
        doctor_id=draft.doctor_id,
        doctor_name=draft.doctor_name,
        treatment_id=draft.treatment_id,
        treatment_name=draft.treatment_name,
        clinic_id=draft.clinic_id,
        clinic_name=draft.clinic_name,
        local_date=draft.local_date,
        local_time=draft.local_time,
        timezone=draft.timezone,
        starts_at_utc=draft.starts_at_utc,
        status="Confirmed",
        notes=draft.notes,
    )


def booking_success_text(booking: BookingView, *, updated: bool = False) -> str:
    """Deterministic success text built only from the persisted record."""
    lines = [
        "Booking updated." if updated else "Booking confirmed.",
        f"- Booking ID: {booking.booking_id}",
        f"- Doctor: {booking.doctor_name} ({booking.doctor_id})",
        f"- Treatment: {booking.treatment_name} ({booking.treatment_id})",
        f"- Clinic: {booking.clinic_name} ({booking.clinic_id})",
        f"- Appointment: {booking.local_date} at {booking.local_time} ({booking.timezone})",
        f"- Status: {booking.status}",
    ]
    if booking.notes:
        lines.append(f"- Notes: {booking.notes}")
    return "\n".join(lines)
