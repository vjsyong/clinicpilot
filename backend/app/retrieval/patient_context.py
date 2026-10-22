"""Server-owned patient context for the P001 demo patient.

Only P001's profile and treatment history are read, with raw parameterized SQL.
Bookings are deliberately left to the REST booking tool.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.contracts import PATIENT_ID
from app.retrieval.documents import SessionFactory


@dataclass(frozen=True)
class PatientRecord:
    """The only patient record the assistant may read."""

    profile: dict[str, Any]
    history: tuple[dict[str, Any], ...]
    upcoming_appointments: int


def load_patient_record(session_factory: SessionFactory) -> PatientRecord:
    try:
        with session_factory() as session:
            patient = (
                session.execute(
                    text(
                        "SELECT patient_id, first_name, last_name, dob, gender, phone, "
                        "email, known_allergies, emergency_contact "
                        "FROM patients WHERE patient_id = :patient_id"
                    ),
                    {"patient_id": PATIENT_ID},
                )
                .mappings()
                .first()
            )
            history = (
                session.execute(
                    text(
                        "SELECT h.record_id, h.visit_date, h.chief_complaint, h.diagnosis, "
                        "h.prescribed_medication, h.doctor_notes, h.doctor_id, "
                        "d.full_name AS doctor_name "
                        "FROM patient_treatment_history AS h "
                        "LEFT JOIN doctors AS d ON d.doctor_id = h.doctor_id "
                        "WHERE h.patient_id = :patient_id "
                        "ORDER BY h.visit_date DESC, h.record_id"
                    ),
                    {"patient_id": PATIENT_ID},
                )
                .mappings()
                .all()
            )
            now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
            upcoming: int = int(
                session.execute(
                    text(
                        "SELECT COUNT(*) AS count FROM patient_bookings "
                        "WHERE patient_id = :patient_id "
                        "AND status NOT IN ('Cancelled', 'Completed') "
                        "AND starts_at_utc >= :now"
                    ),
                    {"patient_id": PATIENT_ID, "now": now},
                ).scalar_one()
            )
    except SQLAlchemyError as exc:
        raise RuntimeError("Could not load the patient context from the database.") from exc

    if patient is None:
        raise RuntimeError(f"Patient {PATIENT_ID} is missing from the database.")

    profile = {
        "patient_id": str(patient["patient_id"]),
        "first_name": str(patient["first_name"]),
        "last_name": str(patient["last_name"]),
        "full_name": f"{patient['first_name']} {patient['last_name']}",
        "date_of_birth": str(patient["dob"]),
        "gender": str(patient["gender"]),
        "phone": str(patient["phone"]),
        "email": str(patient["email"]),
        "known_allergies": str(patient["known_allergies"]),
        "emergency_contact": str(patient["emergency_contact"]),
    }
    rows = tuple(
        {
            "record_id": str(row["record_id"]),
            "visit_date": str(row["visit_date"]),
            "doctor_id": str(row["doctor_id"]),
            "doctor_name": str(row["doctor_name"] or row["doctor_id"]),
            "chief_complaint": str(row["chief_complaint"]),
            "diagnosis": str(row["diagnosis"]),
            "prescribed_medication": str(row["prescribed_medication"]),
            "doctor_notes": str(row["doctor_notes"]),
        }
        for row in history
    )
    return PatientRecord(profile=profile, history=rows, upcoming_appointments=upcoming)


def render_patient_record(record: PatientRecord) -> str:
    profile = record.profile
    lines = [
        f"Patient context (server-owned; patient {PATIENT_ID}):",
        f"- Name: {profile['full_name']}",
        f"- Date of birth: {profile['date_of_birth']}",
        f"- Gender: {profile['gender']}",
        f"- Phone: {profile['phone']}",
        f"- Email: {profile['email']}",
        f"- Known allergies: {profile['known_allergies']}",
        f"- Emergency contact: {profile['emergency_contact']}",
    ]
    if record.history:
        lines.append("- Treatment history:")
        for row in record.history:
            lines.append(
                f"  - {row['visit_date']} ({row['record_id']}, "
                f"{row['doctor_name']} / {row['doctor_id']}): {row['chief_complaint']} "
                f"Diagnosis: {row['diagnosis']}. "
                f"Prescribed: {row['prescribed_medication']}. "
                f"Notes: {row['doctor_notes']}"
            )
    else:
        lines.append("- Treatment history: none on file.")
    lines.append(
        f"- Upcoming appointments: {record.upcoming_appointments} "
        "(count only; use get_patient_bookings for details)."
    )
    return "\n".join(lines)


def patient_record_payload(record: PatientRecord) -> dict[str, Any]:
    """Return the record as JSON-safe tool output."""
    return {
        "profile": dict(record.profile),
        "treatment_history": [dict(row) for row in record.history],
        "upcoming_appointments": record.upcoming_appointments,
    }


def load_patient_context(session_factory: SessionFactory) -> str:
    return render_patient_record(load_patient_record(session_factory))
