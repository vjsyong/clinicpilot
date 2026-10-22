from __future__ import annotations

from datetime import UTC, datetime

from app.contracts import BookingDraftView, DraftStatus
from app.services.slots import next_step_for_draft, suggest_slots


def _draft(**updates) -> BookingDraftView:
    values = {
        "draft_id": "draft-1",
        "version": 2,
        "status": DraftStatus.COLLECTING_DETAILS.value,
        "doctor_id": "D104",
        "doctor_name": "Dr. James Wilson",
        "treatment_id": "T005",
        "treatment_name": "Joint & Pain Consultation",
        "clinic_id": "C001",
        "clinic_name": "Metro Care Health Clinic",
        "timezone": "America/New_York",
        "missing_fields": ["local_date", "local_time"],
    }
    values.update(updates)
    return BookingDraftView(**values)


def test_afternoon_preference_keeps_the_requested_friday_and_offers_times() -> None:
    now = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
    slots = suggest_slots(_draft(), "Friday afternoon", now)

    assert [slot.local_date for slot in slots] == ["2026-10-23"] * len(slots)
    assert [slot.local_time for slot in slots][:3] == ["14:00", "15:00", "16:00"]
    assert all(slot.timezone == "America/New_York" for slot in slots)
    assert all("Oct 23" in slot.label for slot in slots)


def test_known_date_is_not_replaced_by_a_relative_word() -> None:
    now = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
    slots = suggest_slots(_draft(local_date="2026-10-27"), "Friday afternoon", now)

    assert slots
    assert all(slot.local_date == "2026-10-27" for slot in slots)


def test_closed_day_moves_to_the_next_open_day() -> None:
    now = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)  # Saturday
    slots = suggest_slots(_draft(), "Sunday morning", now)

    assert slots
    assert all(slot.local_date == "2026-10-26" for slot in slots)


def test_next_step_never_offers_confirmation_for_an_incomplete_draft() -> None:
    now = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
    step = next_step_for_draft(_draft(), "Friday", now)

    assert step.kind == "choose_slot"
    assert step.suggestions
    assert step.draft_version is None
