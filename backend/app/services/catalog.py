"""Static application assumptions about clinics and doctor/treatment pairing."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

DOCTOR_TREATMENTS_PATH = Path(__file__).resolve().parents[1] / "config" / "doctor_treatments.json"

CLINIC_TIMEZONES: dict[str, str] = {
    "C001": "America/New_York",
    "C002": "America/Los_Angeles",
}


class LocalTimeError(ValueError):
    """A local wall-clock time is malformed, nonexistent, or ambiguous."""


@lru_cache(maxsize=1)
def _doctor_treatments() -> dict[str, frozenset[str]]:
    with DOCTOR_TREATMENTS_PATH.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    return {
        str(doctor): frozenset(str(t) for t in treatments) for doctor, treatments in raw.items()
    }


def doctor_treatments() -> dict[str, frozenset[str]]:
    return _doctor_treatments()


def doctor_offers(doctor_id: str, treatment_id: str) -> bool:
    return treatment_id in doctor_treatments().get(doctor_id, frozenset())


def clinic_timezone(clinic_id: str) -> str:
    try:
        return CLINIC_TIMEZONES[clinic_id]
    except KeyError as exc:
        raise LocalTimeError(f"No timezone is configured for clinic {clinic_id}.") from exc


def resolve_local_utc(local_date: str, local_time: str, timezone: str) -> datetime:
    """Combine a local date/time in a clinic timezone into an aware UTC datetime.

    Rejects nonexistent (spring-forward) and ambiguous (fall-back) wall times
    instead of guessing a fold.
    """
    try:
        day = datetime.strptime(local_date, "%Y-%m-%d").date()
        clock = datetime.strptime(local_time, "%H:%M").time()
        zone = ZoneInfo(timezone)
    except (ValueError, KeyError) as exc:
        raise LocalTimeError("The appointment date or time is invalid.") from exc

    naive = datetime.combine(day, clock)
    valid_offsets: set[object] = set()
    for fold in (0, 1):
        aware = naive.replace(tzinfo=zone, fold=fold)
        roundtrip = aware.astimezone(UTC).astimezone(zone).replace(tzinfo=None)
        if roundtrip == naive:
            valid_offsets.add(aware.utcoffset())
    if not valid_offsets:
        raise LocalTimeError("That local time does not exist because of a daylight-saving change.")
    if len(valid_offsets) > 1:
        raise LocalTimeError("That local time is ambiguous because of a daylight-saving change.")
    return naive.replace(tzinfo=zone).astimezone(UTC)
