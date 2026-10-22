from __future__ import annotations

from datetime import UTC, date, datetime, time

from app.db.models import (
    Clinic,
    Doctor,
    Patient,
    PatientBooking,
    PatientTreatmentHistory,
    Treatment,
)
from app.db.seed import seed_all
from sqlalchemy import func, select
from tests.conftest import DBHarness


def _count(session, model: type) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def test_seed_counts_and_timezone_normalization(db: DBHarness) -> None:
    with db.session_factory() as session:
        assert _count(session, Clinic) == 2
        assert _count(session, Doctor) == 4
        assert _count(session, Treatment) == 5
        assert _count(session, Patient) == 3
        assert _count(session, PatientTreatmentHistory) == 2
        assert _count(session, PatientBooking) == 4

        assert session.get(Doctor, "D101").consultation_fee_cents == 15000  # type: ignore[union-attr]
        assert session.get(Treatment, "T001").price_cents == 15000  # type: ignore[union-attr]
        assert session.get(Treatment, "T005").duration_minutes == 45  # type: ignore[union-attr]

        b1001 = session.get(PatientBooking, "B1001")
        assert b1001 is not None
        assert b1001.timezone == "America/New_York"
        assert b1001.starts_at_utc == datetime(2026, 11, 5, 14, 0, tzinfo=UTC)

        b1002 = session.get(PatientBooking, "B1002")
        assert b1002 is not None
        assert b1002.timezone == "America/Los_Angeles"
        assert b1002.starts_at_utc == datetime(2026, 11, 6, 22, 30, tzinfo=UTC)

        b1003 = session.get(PatientBooking, "B1003")
        assert b1003 is not None
        assert b1003.starts_at_utc == datetime(2026, 10, 20, 14, 15, tzinfo=UTC)

        b1004 = session.get(PatientBooking, "B1004")
        assert b1004 is not None
        assert b1004.starts_at_utc == datetime(2026, 11, 15, 16, 0, tzinfo=UTC)


def test_seed_twice_is_stable_and_retains_new_booking(db: DBHarness) -> None:
    with db.session_factory() as session:
        session.add(
            PatientBooking(
                booking_id="B1005",
                patient_id="P001",
                doctor_id="D104",
                treatment_id="T005",
                booking_date=date(2026, 12, 1),
                booking_time=time(10, 0),
                status="Confirmed",
                notes="User-created booking.",
                starts_at_utc=datetime(2026, 12, 1, 15, 0, tzinfo=UTC),
                timezone="America/New_York",
                idempotency_key="booking:user:v1",
                request_hash="user-hash",
                created_at=datetime(2026, 10, 22, 12, 0, tzinfo=UTC),
            )
        )
        session.commit()

    seed_all(db.session_factory, db.settings)
    seed_all(db.session_factory, db.settings)

    with db.session_factory() as session:
        assert _count(session, Clinic) == 2
        assert _count(session, Doctor) == 4
        assert _count(session, Treatment) == 5
        assert _count(session, Patient) == 3
        assert _count(session, PatientTreatmentHistory) == 2
        assert _count(session, PatientBooking) == 5
        retained = session.get(PatientBooking, "B1005")
        assert retained is not None
        assert retained.notes == "User-created booking."
        assert retained.idempotency_key == "booking:user:v1"
        assert retained.request_hash == "user-hash"
