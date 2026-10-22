"""Repeatable seeding of the six source CSV datasets.

Seeding is an upsert keyed by the source IDs. Rows that the application created
(bookings without a CSV source ID) are never deleted or modified, and running
the seeder twice leaves seed counts stable.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.db.models import (
    Clinic,
    Doctor,
    Patient,
    PatientBooking,
    PatientTreatmentHistory,
    Treatment,
)
from app.settings import Settings, get_settings
from sqlalchemy.orm import Session, sessionmaker

CLINIC_TIMEZONES: dict[str, str] = {
    "C001": "America/New_York",
    "C002": "America/Los_Angeles",
}


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _cents(value: str) -> int:
    return int((Decimal(value) * 100).to_integral_value())


def _booking_starts_at_utc(booking_date: date, booking_time: time, tz: str) -> datetime:
    local = datetime.combine(booking_date, booking_time).replace(tzinfo=ZoneInfo(tz))
    return local.astimezone(UTC)


def _upsert(
    session: Session,
    model: type[Any],
    primary_key: str,
    values: Mapping[str, Any],
    *,
    update: bool = True,
) -> None:
    existing = session.get(model, values[primary_key])
    if existing is None:
        session.add(model(**values))
        return
    if not update:
        return
    for key, value in values.items():
        if key == primary_key:
            continue
        setattr(existing, key, value)


def _seed_clinics(session: Session, rows: Iterable[Mapping[str, str]]) -> None:
    for row in rows:
        _upsert(
            session,
            Clinic,
            "clinic_id",
            {
                "clinic_id": row["clinic_id"],
                "clinic_name": row["clinic_name"],
                "address": row["address"],
                "phone": row["phone"],
                "operating_hours": row["operating_hours"],
                "cancellation_policy": row["cancellation_policy"],
                "emergency_instructions": row["emergency_instructions"],
            },
        )


def _seed_doctors(session: Session, rows: Iterable[Mapping[str, str]]) -> None:
    for row in rows:
        _upsert(
            session,
            Doctor,
            "doctor_id",
            {
                "doctor_id": row["doctor_id"],
                "clinic_id": row["clinic_id"],
                "full_name": row["full_name"],
                "specialty": row["specialty"],
                "languages_spoken": row["languages_spoken"],
                "consultation_fee_cents": _cents(row["consultation_fee_usd"]),
                "bio": row["bio"],
            },
        )


def _seed_treatments(session: Session, rows: Iterable[Mapping[str, str]]) -> None:
    for row in rows:
        _upsert(
            session,
            Treatment,
            "treatment_id",
            {
                "treatment_id": row["treatment_id"],
                "treatment_name": row["treatment_name"],
                "category": row["category"],
                "duration_minutes": int(row["duration_minutes"]),
                "price_cents": _cents(row["price_usd"]),
                "pre_treatment_instructions": row["pre_treatment_instructions"],
            },
        )


def _seed_patients(session: Session, rows: Iterable[Mapping[str, str]]) -> None:
    for row in rows:
        _upsert(
            session,
            Patient,
            "patient_id",
            {
                "patient_id": row["patient_id"],
                "first_name": row["first_name"],
                "last_name": row["last_name"],
                "dob": date.fromisoformat(row["dob"]),
                "gender": row["gender"],
                "phone": row["phone"],
                "email": row["email"],
                "known_allergies": row["known_allergies"],
                "emergency_contact": row["emergency_contact"],
            },
        )


def _seed_history(session: Session, rows: Iterable[Mapping[str, str]]) -> None:
    for row in rows:
        _upsert(
            session,
            PatientTreatmentHistory,
            "record_id",
            {
                "record_id": row["record_id"],
                "patient_id": row["patient_id"],
                "doctor_id": row["doctor_id"],
                "visit_date": date.fromisoformat(row["visit_date"]),
                "chief_complaint": row["chief_complaint"],
                "diagnosis": row["diagnosis"],
                "prescribed_medication": row["prescribed_medication"],
                "doctor_notes": row["doctor_notes"],
            },
        )


def _seed_bookings(session: Session, rows: Iterable[Mapping[str, str]], now: datetime) -> None:
    for row in rows:
        booking_id = row["booking_id"]
        booking_date = date.fromisoformat(row["booking_date"])
        booking_time = time.fromisoformat(row["booking_time"])
        doctor = session.get(Doctor, row["doctor_id"])
        if doctor is None:
            raise RuntimeError(f"Booking {booking_id} references unknown doctor")
        tz = CLINIC_TIMEZONES.get(doctor.clinic_id)
        if tz is None:
            raise RuntimeError(f"No clinic timezone configured for {doctor.clinic_id}")
        values: dict[str, Any] = {
            "booking_id": booking_id,
            "patient_id": row["patient_id"],
            "doctor_id": row["doctor_id"],
            "treatment_id": row["treatment_id"],
            "booking_date": booking_date,
            "booking_time": booking_time,
            "status": row["status"],
            "notes": row["notes"] or None,
            "starts_at_utc": _booking_starts_at_utc(booking_date, booking_time, tz),
            "timezone": tz,
        }
        existing = session.get(PatientBooking, booking_id)
        if existing is None:
            session.add(
                PatientBooking(
                    **values,
                    idempotency_key=None,
                    request_hash=None,
                    created_at=now,
                )
            )
            continue
        # Only rows without an idempotency key are seed rows; application-created
        # bookings are never overwritten.
        if existing.idempotency_key is not None:
            continue
        for key, value in values.items():
            if key == "booking_id":
                continue
            setattr(existing, key, value)


def seed_all(session_factory: sessionmaker[Session], settings: Settings) -> None:
    """Upsert every CSV row. Safe to call on every startup and repeatedly."""
    csv_dir = settings.csv_dir
    if not csv_dir.is_dir():
        raise RuntimeError(f"CSV directory does not exist: {csv_dir}")

    clinics = _read_rows(csv_dir / "clinics.csv")
    doctors = _read_rows(csv_dir / "doctors.csv")
    treatments = _read_rows(csv_dir / "treatments.csv")
    patients = _read_rows(csv_dir / "patients.csv")
    history = _read_rows(csv_dir / "patient_treatment_history.csv")
    bookings = _read_rows(csv_dir / "patient_bookings.csv")

    now = datetime.now(UTC)
    session = session_factory()
    try:
        _seed_clinics(session, clinics)
        session.flush()
        _seed_doctors(session, doctors)
        _seed_treatments(session, treatments)
        _seed_patients(session, patients)
        session.flush()
        _seed_history(session, history)
        _seed_bookings(session, bookings, now)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def main() -> None:
    settings = get_settings()
    from app.db.session import create_session_factory

    _engine, session_factory = create_session_factory(settings)
    seed_all(session_factory, settings)
    print(f"Seeded ClinicPilot data from {settings.csv_dir}")


if __name__ == "__main__":
    main()
