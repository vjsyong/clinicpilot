"""Server-owned canonical booking summaries.

The model may quote these, but it never composes the confirmation summary.
"""

from __future__ import annotations

from app.contracts import BookingDraftView

CONFIRM_INSTRUCTION = (
    'Reply "yes" to confirm this booking, or tell me what you would like to change.'
)


def canonical_summary(draft: BookingDraftView) -> str:
    """Render the validated draft as the only text eligible for confirmation."""
    doctor = _named(draft.doctor_name, draft.doctor_id, "Doctor not selected")
    treatment = _named(draft.treatment_name, draft.treatment_id, "Treatment not selected")
    clinic = _named(draft.clinic_name, draft.clinic_id, "Clinic not selected")
    date_time = _date_time(draft)

    lines = [
        "Booking summary:",
        f"- Doctor: {doctor}",
        f"- Treatment: {treatment}",
        f"- Clinic: {clinic}",
        f"- Appointment: {date_time}",
        f"- Timezone: {draft.timezone or 'not selected'}",
    ]
    if draft.notes:
        lines.append(f"- Notes: {draft.notes}")
    lines.extend(["", CONFIRM_INSTRUCTION])
    return "\n".join(lines)


def _named(name: str | None, identifier: str | None, fallback: str) -> str:
    if name and identifier:
        return f"{name} ({identifier})"
    if name:
        return name
    if identifier:
        return identifier
    return fallback


def _date_time(draft: BookingDraftView) -> str:
    date = draft.local_date or "date not selected"
    time = draft.local_time or "time not selected"
    if draft.local_date and draft.local_time:
        return f"{date} at {time}"
    return f"{date} / {time}"
