"""Explicit, auditable reset of the shared P001 demo workspace."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, time
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.contracts import PATIENT_ID, Clock
from app.db.models import BookingDraft, ChatTurn, Conversation, Doctor, PatientBooking
from app.services.catalog import resolve_local_utc
from app.settings import Settings


@dataclass(frozen=True)
class ResetResult:
    restored_bookings: list[str]
    removed_bookings: int
    cleared_conversations: int


class WorkspaceService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        clock: Clock,
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._settings = settings

    async def reset(self) -> ResetResult:
        """Restore the seed bookings and clear all chats while retaining audit data."""
        seed_rows = _read_seed_bookings(self._settings.csv_dir)
        seed_ids = {row["booking_id"] for row in seed_rows}
        now = self._clock.now()
        session = self._session_factory()
        try:
            cleared = session.scalar(select(func.count()).select_from(Conversation)) or 0
            # Explicit child deletes keep the reset portable across SQLite builds
            # that do not enforce ON DELETE CASCADE.
            session.execute(delete(BookingDraft))
            session.execute(delete(ChatTurn))
            session.execute(delete(Conversation))

            existing = {
                row.booking_id: row
                for row in session.scalars(
                    select(PatientBooking).where(PatientBooking.patient_id == PATIENT_ID)
                ).all()
            }
            removed = 0
            for booking_id, row in existing.items():
                if booking_id not in seed_ids:
                    session.delete(row)
                    removed += 1

            restored: list[str] = []
            for values in seed_rows:
                booking = existing.get(values["booking_id"])
                doctor = session.get(Doctor, values["doctor_id"])
                if doctor is None:
                    continue
                local_date = date.fromisoformat(values["booking_date"])
                local_time = time.fromisoformat(values["booking_time"])
                timezone = _clinic_timezone(doctor.clinic_id)
                starts_at = resolve_local_utc(
                    local_date.isoformat(), local_time.strftime("%H:%M"), timezone
                )
                if booking is None:
                    booking = PatientBooking(
                        booking_id=values["booking_id"],
                        patient_id=PATIENT_ID,
                        doctor_id=values["doctor_id"],
                        treatment_id=values["treatment_id"],
                        booking_date=local_date,
                        booking_time=local_time,
                        status=values["status"],
                        notes=values["notes"] or None,
                        starts_at_utc=starts_at,
                        timezone=timezone,
                        idempotency_key=None,
                        request_hash=None,
                        created_at=now,
                    )
                    session.add(booking)
                else:
                    booking.doctor_id = values["doctor_id"]
                    booking.treatment_id = values["treatment_id"]
                    booking.booking_date = local_date
                    booking.booking_time = local_time
                    booking.status = values["status"]
                    booking.notes = values["notes"] or None
                    booking.starts_at_utc = starts_at
                    booking.timezone = timezone
                    booking.idempotency_key = None
                    booking.request_hash = None
                    booking.deleted_at = None
                    booking.deleted_reason = None
                restored.append(values["booking_id"])

            session.commit()
            return ResetResult(
                restored_bookings=sorted(restored),
                removed_bookings=removed,
                cleared_conversations=int(cleared),
            )
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


def _read_seed_bookings(csv_dir: Path) -> list[dict[str, str]]:
    with (csv_dir / "patient_bookings.csv").open("r", encoding="utf-8", newline="") as handle:
        return [row for row in csv.DictReader(handle) if row["patient_id"] == PATIENT_ID]


def _clinic_timezone(clinic_id: str) -> str:
    return {
        "C001": "America/New_York",
        "C002": "America/Los_Angeles",
    }.get(clinic_id, "America/New_York")
