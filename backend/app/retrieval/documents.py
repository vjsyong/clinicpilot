"""Knowledge documents derived from the six source datasets.

Exactly one document is produced per knowledge row: two clinics, four doctors,
and five treatments. Documents are the only records embedded in the shared
index; patient rows never enter it.
"""

from __future__ import annotations

import csv
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.contracts import RetrievedDocument
from app.settings import Settings

type SessionFactory = sessionmaker[Session]
type Row = Mapping[str, Any]

CLINICS_SOURCE = "clinics.csv"
DOCTORS_SOURCE = "doctors.csv"
TREATMENTS_SOURCE = "treatments.csv"


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _cents(value: str) -> int:
    return int((Decimal(value) * 100).to_integral_value())


def _money(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def _clinic_document(row: Row) -> RetrievedDocument:
    clinic_id = str(row["clinic_id"])
    clinic_name = str(row["clinic_name"])
    parts = [
        f"Clinic {clinic_id}: {clinic_name}.",
        f"Address: {row['address']}.",
        f"Phone: {row['phone']}.",
        f"Operating hours: {row['operating_hours']}.",
        f"Cancellation policy: {row['cancellation_policy']}",
        f"Emergency instructions: {row['emergency_instructions']}",
    ]
    return RetrievedDocument(
        document_id=f"clinics:{clinic_id}",
        source_file=CLINICS_SOURCE,
        record_id=clinic_id,
        text=" ".join(parts),
        metadata={
            "name": clinic_name,
            "clinic_id": clinic_id,
            "clinic_name": clinic_name,
        },
    )


def _doctor_document(row: Row) -> RetrievedDocument:
    doctor_id = str(row["doctor_id"])
    clinic_id = str(row["clinic_id"])
    clinic_name = str(row["clinic_name"])
    full_name = str(row["full_name"])
    specialty = str(row["specialty"])
    fee = _money(int(row["consultation_fee_cents"]))
    parts = [
        f"Doctor {doctor_id}: {full_name}.",
        f"Specialty: {specialty}.",
        f"Clinic: {clinic_name} ({clinic_id}).",
        f"Languages spoken: {row['languages_spoken']}.",
        f"Consultation fee: {fee}.",
        f"Bio: {row['bio']}",
    ]
    return RetrievedDocument(
        document_id=f"doctors:{doctor_id}",
        source_file=DOCTORS_SOURCE,
        record_id=doctor_id,
        text=" ".join(parts),
        metadata={
            "name": full_name,
            "doctor_id": doctor_id,
            "clinic_id": clinic_id,
            "clinic_name": clinic_name,
            "specialty": specialty,
        },
    )


def _treatment_document(row: Row) -> RetrievedDocument:
    treatment_id = str(row["treatment_id"])
    treatment_name = str(row["treatment_name"])
    category = str(row["category"])
    price = _money(int(row["price_cents"]))
    parts = [
        f"Treatment {treatment_id}: {treatment_name}.",
        f"Category: {category}.",
        f"Duration: {int(row['duration_minutes'])} minutes.",
        f"Price: {price}.",
        f"Pre-treatment instructions: {row['pre_treatment_instructions']}",
    ]
    return RetrievedDocument(
        document_id=f"treatments:{treatment_id}",
        source_file=TREATMENTS_SOURCE,
        record_id=treatment_id,
        text=" ".join(parts),
        metadata={
            "name": treatment_name,
            "treatment_id": treatment_id,
            "category": category,
        },
    )


def _clinic_documents(rows: Sequence[Row]) -> list[RetrievedDocument]:
    return [_clinic_document(row) for row in rows]


def _doctor_documents(
    rows: Sequence[Row], clinic_names: Mapping[str, str]
) -> list[RetrievedDocument]:
    documents: list[RetrievedDocument] = []
    for row in rows:
        clinic_id = str(row["clinic_id"])
        try:
            clinic_name = clinic_names[clinic_id]
        except KeyError as exc:
            doctor_id = str(row["doctor_id"])
            raise RuntimeError(
                f"Doctor {doctor_id} references unknown clinic {clinic_id}."
            ) from exc
        with_clinic = dict(row)
        with_clinic["clinic_name"] = clinic_name
        documents.append(_doctor_document(with_clinic))
    return documents


def _treatment_documents(rows: Sequence[Row]) -> list[RetrievedDocument]:
    return [_treatment_document(row) for row in rows]


def documents_from_csv(settings: Settings) -> list[RetrievedDocument]:
    """Build the eleven knowledge documents from ``settings.csv_dir``."""
    csv_dir = settings.csv_dir
    try:
        clinic_rows = _read_rows(csv_dir / CLINICS_SOURCE)
        doctor_rows = _read_rows(csv_dir / DOCTORS_SOURCE)
        treatment_rows = _read_rows(csv_dir / TREATMENTS_SOURCE)
    except FileNotFoundError as exc:
        raise RuntimeError(f"Knowledge CSV files are missing under {csv_dir}.") from exc

    clinic_names = {row["clinic_id"]: row["clinic_name"] for row in clinic_rows}
    doctor_rows_with_cents: list[Row] = [
        {**row, "consultation_fee_cents": _cents(row["consultation_fee_usd"])}
        for row in doctor_rows
    ]
    treatment_rows_with_cents: list[Row] = [
        {**row, "price_cents": _cents(row["price_usd"])} for row in treatment_rows
    ]
    return [
        *_clinic_documents(clinic_rows),
        *_doctor_documents(doctor_rows_with_cents, clinic_names),
        *_treatment_documents(treatment_rows_with_cents),
    ]


def documents_from_db(session_factory: SessionFactory) -> list[RetrievedDocument]:
    """Build the eleven knowledge documents from the migrated database."""
    try:
        with session_factory() as session:
            clinic_rows = (
                session.execute(
                    text(
                        "SELECT clinic_id, clinic_name, address, phone, operating_hours, "
                        "cancellation_policy, emergency_instructions "
                        "FROM clinics ORDER BY clinic_id"
                    )
                )
                .mappings()
                .all()
            )
            doctor_rows = (
                session.execute(
                    text(
                        "SELECT d.doctor_id, d.clinic_id, d.full_name, d.specialty, "
                        "d.languages_spoken, d.consultation_fee_cents, d.bio, "
                        "c.clinic_name "
                        "FROM doctors AS d "
                        "JOIN clinics AS c ON c.clinic_id = d.clinic_id "
                        "ORDER BY d.doctor_id"
                    )
                )
                .mappings()
                .all()
            )
            treatment_rows = (
                session.execute(
                    text(
                        "SELECT treatment_id, treatment_name, category, duration_minutes, "
                        "price_cents, pre_treatment_instructions "
                        "FROM treatments ORDER BY treatment_id"
                    )
                )
                .mappings()
                .all()
            )
    except OperationalError as exc:
        raise RuntimeError(
            "Knowledge tables are missing; apply Alembic migrations and seed the "
            "database before building the retrieval index."
        ) from exc
    except SQLAlchemyError as exc:
        raise RuntimeError("Could not load knowledge documents from the database.") from exc

    clinic_names = {str(row["clinic_id"]): str(row["clinic_name"]) for row in clinic_rows}
    clinic_documents = _clinic_documents([dict(row) for row in clinic_rows])
    doctor_documents = _doctor_documents([dict(row) for row in doctor_rows], clinic_names)
    treatment_documents = _treatment_documents([dict(row) for row in treatment_rows])
    return [*clinic_documents, *doctor_documents, *treatment_documents]
