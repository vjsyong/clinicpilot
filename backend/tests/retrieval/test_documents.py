from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest
from app.retrieval.documents import documents_from_csv, documents_from_db
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from tests.conftest import DBHarness

EXPECTED_IDS = {
    "clinics:C001",
    "clinics:C002",
    "doctors:D101",
    "doctors:D102",
    "doctors:D103",
    "doctors:D104",
    "treatments:T001",
    "treatments:T002",
    "treatments:T003",
    "treatments:T004",
    "treatments:T005",
}


def test_csv_documents_are_exactly_the_eleven_rows(retrieval_settings) -> None:
    documents = documents_from_csv(retrieval_settings)

    assert len(documents) == 11
    assert {document.document_id for document in documents} == EXPECTED_IDS
    assert Counter(document.source_file for document in documents) == {
        "clinics.csv": 2,
        "doctors.csv": 4,
        "treatments.csv": 5,
    }
    for document in documents:
        prefix, record_id = document.document_id.split(":", 1)
        assert record_id == document.record_id
        assert document.document_id.startswith(prefix + ":")
        assert document.text


def test_relational_context_is_present(retrieval_settings) -> None:
    by_id = {document.document_id: document for document in documents_from_csv(retrieval_settings)}

    clinic = by_id["clinics:C001"]
    assert clinic.record_id == "C001"
    assert "123 Medical Center Way" in clinic.text
    assert "Mon-Fri: 8:00 AM - 6:00 PM" in clinic.text
    assert "at least 24 hours in advance" in clinic.text
    assert "dial 911" in clinic.text

    doctor = by_id["doctors:D104"]
    assert doctor.record_id == "D104"
    assert doctor.metadata["clinic_id"] == "C001"
    assert doctor.metadata["clinic_name"] == "Metro Care Health Clinic"
    assert doctor.metadata["specialty"] == "Orthopedics"
    assert "Metro Care Health Clinic (C001)" in doctor.text
    assert "$250.00" in doctor.text

    treatment = by_id["treatments:T005"]
    assert treatment.record_id == "T005"
    assert treatment.metadata["category"] == "Orthopedics"
    assert "Category: Orthopedics" in treatment.text
    assert "$230.00" in treatment.text


def test_db_documents_match_csv_documents(db: DBHarness) -> None:
    from_csv = documents_from_csv(db.settings)
    from_db = documents_from_db(db.session_factory)

    assert [document.document_id for document in from_db] == [
        document.document_id for document in from_csv
    ]
    assert [document.text for document in from_db] == [document.text for document in from_csv]
    assert [document.metadata for document in from_db] == [
        document.metadata for document in from_csv
    ]


def test_documents_from_raw_sqlite_schema(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'raw.db'}")
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE clinics (clinic_id TEXT PRIMARY KEY, clinic_name TEXT, "
                    "address TEXT, phone TEXT, operating_hours TEXT, cancellation_policy TEXT, "
                    "emergency_instructions TEXT)"
                )
            )
            connection.execute(
                text(
                    "CREATE TABLE doctors (doctor_id TEXT PRIMARY KEY, clinic_id TEXT, "
                    "full_name TEXT, specialty TEXT, languages_spoken TEXT, "
                    "consultation_fee_cents INTEGER, bio TEXT)"
                )
            )
            connection.execute(
                text(
                    "CREATE TABLE treatments (treatment_id TEXT PRIMARY KEY, treatment_name TEXT, "
                    "category TEXT, duration_minutes INTEGER, price_cents INTEGER, "
                    "pre_treatment_instructions TEXT)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO clinics VALUES ('C001', 'Metro Care Health Clinic', "
                    "'123 Medical Center Way', '+1-555-019-2831', 'Mon-Fri: 8:00 AM - 6:00 PM', "
                    "'24 hours notice', 'Call 911 for emergencies.')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO doctors VALUES ('D104', 'C001', 'Dr. James Wilson', "
                    "'Orthopedics', 'English', 25000, 'Joint pain and sports injuries.')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO treatments VALUES ('T005', 'Joint & Pain Consultation', "
                    "'Orthopedics', 45, 23000, 'Wear loose clothing.')"
                )
            )
        factory = sessionmaker(bind=engine)
        documents = documents_from_db(factory)
    finally:
        engine.dispose()

    by_id = {document.document_id: document for document in documents}
    assert set(by_id) == {"clinics:C001", "doctors:D104", "treatments:T005"}
    assert by_id["doctors:D104"].metadata["clinic_name"] == "Metro Care Health Clinic"
    assert "$250.00" in by_id["doctors:D104"].text
    assert "$230.00" in by_id["treatments:T005"].text
    assert "Category: Orthopedics" in by_id["treatments:T005"].text


def test_missing_tables_raise_clear_error(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    try:
        factory = sessionmaker(bind=engine)
        with pytest.raises(RuntimeError, match="migrations"):
            documents_from_db(factory)
    finally:
        engine.dispose()
