"""Deterministic, clinic-local appointment suggestions.

Suggestions are guidance, not verified clinician availability. They keep the
conversation moving when the patient gives a day or a window but not an exact
slot, and they never satisfy the confirmation boundary on their own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.contracts import BookingDraftView, DraftStatus, NextStep, SlotSuggestion
from app.services.catalog import LocalTimeError, clinic_timezone, resolve_local_utc

_WEEKDAYS = {
    "monday": 0,
    "mon": 0,
    "tuesday": 1,
    "tue": 1,
    "tues": 1,
    "wednesday": 2,
    "wed": 2,
    "thursday": 3,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "friday": 4,
    "fri": 4,
    "saturday": 5,
    "sat": 5,
    "sunday": 6,
    "sun": 6,
}
_ISO_DATE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
_WINDOWS = {
    "morning": (9, 12),
    "afternoon": (14, 17),
    "evening": (16, 18),
}

# Opening windows by clinic and weekday (Monday=0). These are guidance only;
# the clinic's operating hours remain informational per the contract.
_HOURS: dict[str, dict[int, tuple[time, time]]] = {
    "C001": {
        0: (time(8, 0), time(18, 0)),
        1: (time(8, 0), time(18, 0)),
        2: (time(8, 0), time(18, 0)),
        3: (time(8, 0), time(18, 0)),
        4: (time(8, 0), time(18, 0)),
        5: (time(9, 0), time(13, 0)),
    },
    "C002": {
        0: (time(9, 0), time(17, 0)),
        1: (time(9, 0), time(17, 0)),
        2: (time(9, 0), time(17, 0)),
        3: (time(9, 0), time(17, 0)),
        4: (time(9, 0), time(17, 0)),
    },
}


@dataclass(frozen=True)
class _Window:
    start: int
    end: int
    preferred: tuple[int, ...]


def suggest_slots(
    draft: BookingDraftView | None,
    user_text: str,
    now: datetime,
    *,
    limit: int = 3,
) -> list[SlotSuggestion]:
    if draft is None or draft.status == DraftStatus.BOOKED.value:
        return []
    if draft.local_date and draft.local_time:
        return []

    timezone = _timezone_for(draft)
    zone = ZoneInfo(timezone)
    local_now = _as_local(now, zone)
    target = _target_date(draft, user_text, local_now)
    window = _window_for(user_text)
    suggestions: list[SlotSuggestion] = []
    clinic_id = draft.clinic_id or "C001"

    for day_offset in range(10):
        candidate = target + timedelta(days=day_offset)
        hours = _HOURS.get(clinic_id, _HOURS["C001"]).get(candidate.weekday())
        if hours is None:
            continue
        open_at, close_at = hours
        for hour, minute in _candidate_times(window, open_at, close_at):
            if candidate == local_now.date() and time(hour, minute) <= local_now.time():
                continue
            try:
                resolve_local_utc(candidate.isoformat(), f"{hour:02d}:{minute:02d}", timezone)
            except LocalTimeError:
                continue
            suggestions.append(
                SlotSuggestion(
                    local_date=candidate.isoformat(),
                    local_time=f"{hour:02d}:{minute:02d}",
                    timezone=timezone,
                    label=_label(candidate, hour, minute, timezone),
                )
            )
            if len(suggestions) >= limit:
                return suggestions
    return suggestions


def next_step_for_draft(
    draft: BookingDraftView | None,
    user_text: str,
    now: datetime,
) -> NextStep:
    if draft is None:
        return NextStep(
            kind="collect_details",
            missing_fields=["doctor_id", "treatment_id", "local_date", "local_time"],
            message=(
                "Tell me the doctor, treatment, date, and time you would like, "
                "and I can prepare the booking."
            ),
        )
    if draft.status == DraftStatus.BOOKED.value:
        return NextStep(
            kind="completed",
            booking_id=draft.booking_id,
            message="This booking is already confirmed.",
        )
    if draft.status == DraftStatus.CANCELLED.value:
        return NextStep(
            kind="collect_details",
            message="That booking draft is closed. Tell me the details for a new booking.",
        )
    missing = list(draft.missing_fields)
    if not draft.doctor_id or not draft.treatment_id:
        return NextStep(
            kind="collect_details",
            missing_fields=missing,
            message=(
                "Choose a doctor and treatment first. I can then suggest "
                "appointment dates and times."
            ),
        )
    if not draft.local_date or not draft.local_time:
        suggestions = suggest_slots(draft, user_text, now)
        return NextStep(
            kind="choose_slot",
            missing_fields=missing,
            suggestions=suggestions,
            message=(
                "I still need a date and time before I can book. "
                "Choose one of these clinic-local times or tell me another."
            ),
        )
    if draft.status == DraftStatus.AWAITING_CONFIRMATION.value:
        return NextStep(
            kind="confirm_booking",
            draft_version=draft.version,
            message="Review the summary, then confirm or change a detail.",
        )
    return NextStep(
        kind="confirm_booking",
        draft_version=draft.version,
        message="Review the summary, then confirm or change a detail.",
    )


def guidance_text(step: NextStep) -> str:
    if step.kind == "choose_slot":
        labels = "; ".join(item.label for item in step.suggestions)
        if labels:
            return f"{step.message}\n\nSuggested clinic-local times: {labels}."
        return step.message or "Tell me the date and time you would like."
    if step.kind == "collect_details":
        missing = ", ".join(_human_field(field) for field in step.missing_fields) or "a few details"
        return f"{step.message or 'I need a little more information.'} Missing: {missing}."
    if step.kind == "confirm_booking":
        return step.message or "Review the summary, then confirm."
    return step.message or ""


def _timezone_for(draft: BookingDraftView) -> str:
    if draft.timezone:
        return draft.timezone
    try:
        return clinic_timezone(draft.clinic_id or "C001")
    except LocalTimeError:
        return "America/New_York"


def _as_local(now: datetime, zone: ZoneInfo) -> datetime:
    aware = now if now.tzinfo is not None else now.replace(tzinfo=zone)
    return aware.astimezone(zone)


def _target_date(draft: BookingDraftView, user_text: str, local_now: datetime) -> date:
    if draft.local_date:
        try:
            parsed = date.fromisoformat(draft.local_date)
            if parsed >= local_now.date():
                return parsed
        except ValueError:
            pass
    text = user_text.casefold()
    if "tomorrow" in text:
        return local_now.date() + timedelta(days=1)
    if "today" in text or "tonight" in text:
        return local_now.date()
    iso = _ISO_DATE.search(text)
    if iso:
        try:
            parsed = date.fromisoformat(iso.group(0))
            if parsed >= local_now.date():
                return parsed
        except ValueError:
            pass
    for word, weekday in _WEEKDAYS.items():
        if re.search(rf"\b{word}\b", text):
            delta = (weekday - local_now.weekday()) % 7
            if delta == 0 and local_now.hour >= 16:
                delta = 7
            return local_now.date() + timedelta(days=delta)
    # A sensible default: today if there is still time, otherwise the next day.
    if local_now.weekday() < 5 and local_now.hour < 15:
        return local_now.date()
    return local_now.date() + timedelta(days=1)


def _window_for(user_text: str) -> _Window:
    text = user_text.casefold()
    for name, (start, end) in _WINDOWS.items():
        if name in text:
            if name == "morning":
                return _Window(start, end, (9, 10, 11))
            if name == "afternoon":
                return _Window(start, end, (14, 15, 16))
            return _Window(start, end, (16, 17))
    if "noon" in text or "lunch" in text:
        return _Window(11, 14, (12, 13))
    return _Window(9, 17, (10, 14, 16))


def _candidate_times(window: _Window, open_at: time, close_at: time) -> tuple[tuple[int, int], ...]:
    open_hour = open_at.hour
    close_hour = close_at.hour
    preferred = window.preferred
    times = []
    for hour in preferred:
        if open_hour <= hour < close_hour:
            times.append((hour, 0))
    if not times:
        candidate = max(open_hour, window.start)
        while candidate < min(close_hour, window.end + 1):
            times.append((candidate, 0))
            candidate += 1
    return tuple(times)


def _label(day: date, hour: int, minute: int, timezone: str) -> str:
    suffix = "AM" if hour < 12 else "PM"
    display_hour = hour % 12 or 12
    return (
        f"{day.strftime('%a')}, {day.strftime('%b')} {day.day} at "
        f"{display_hour}:{minute:02d} {suffix} ({timezone})"
    )


def _human_field(field: str) -> str:
    return {
        "doctor_id": "doctor",
        "treatment_id": "treatment",
        "local_date": "date",
        "local_time": "time",
        "timezone": "timezone",
    }.get(field, field.replace("_", " "))
