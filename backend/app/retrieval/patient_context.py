"""Server-owned patient context for the P001 demo patient.

Only P001's profile and treatment history are read, with raw parameterized SQL.
Bookings are deliberately left to the REST booking tool.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.contracts import PATIENT_ID
from app.retrieval.documents import SessionFactory


def load_patient_context(session_factory: SessionFactory) -> str:
    try:
        with session_factory() as session:
            patient = (
                session.execute(
                    text(
                        "SELECT patient_id, first_name, last_name, known_allergies, "
                        "emergency_contact FROM patients WHERE patient_id = :patient_id"
                    ),
                    {"patient_id": PATIENT_ID},
                )
                .mappings()
                .first()
            )
            history = (
                session.execute(
                    text(
                        "SELECT record_id, visit_date, chief_complaint, diagnosis, "
                        "prescribed_medication, doctor_notes "
                        "FROM patient_treatment_history "
                        "WHERE patient_id = :patient_id "
                        "ORDER BY visit_date DESC, record_id"
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

    name = f"{patient['first_name']} {patient['last_name']}"
    lines = [
        f"Patient context (server-owned; patient {PATIENT_ID}):",
        f"- Name: {name}",
        f"- Known allergies: {patient['known_allergies']}",
        f"- Emergency contact: {patient['emergency_contact']}",
    ]
    if history:
        lines.append("- Treatment history:")
        for row in history:
            lines.append(
                f"  - {row['visit_date']} ({row['record_id']}): {row['chief_complaint']} "
                f"Diagnosis: {row['diagnosis']}. "
                f"Prescribed: {row['prescribed_medication']}. "
                f"Notes: {row['doctor_notes']}"
            )
    else:
        lines.append("- Treatment history: none on file.")
    lines.append(
        f"- Upcoming appointments: {upcoming} (count only; use get_patient_bookings for details)."
    )
    return "\n".join(lines)
