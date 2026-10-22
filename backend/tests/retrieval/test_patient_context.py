from __future__ import annotations

from pathlib import Path

import pytest
from app.retrieval.patient_context import load_patient_context
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from tests.conftest import DBHarness


def test_patient_context_contains_only_p001(db: DBHarness) -> None:
    context = load_patient_context(db.session_factory)

    assert "P001" in context
    assert "John Doe" in context
    assert "Penicillin, Peanuts" in context
    assert "Annual routine health checkup" in context
    assert "Healthy / Normal Range" in context
    assert "Multivitamins" in context
    assert "Blood pressure normal (120/80)" in context
    assert "1988-05-14" in context
    assert "john.doe@example.com" in context
    assert "Dr. Sarah Jenkins" in context

    assert "P002" not in context
    assert "P003" not in context
    assert "Alice" not in context
    assert "Robert" not in context
    assert "Sulfa" not in context
    assert "Latex" not in context
    assert "Amoxicillin" not in context
    assert "Upper Respiratory Tract Infection" not in context


def test_patient_context_raises_on_missing_tables(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    try:
        factory = sessionmaker(bind=engine)
        with pytest.raises(RuntimeError, match="patient context"):
            load_patient_context(factory)
    finally:
        engine.dispose()
