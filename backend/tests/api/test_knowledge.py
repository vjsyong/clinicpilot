from __future__ import annotations

from app.contracts import RetrievedDocument
from tests.conftest import AppHarness


def _document() -> RetrievedDocument:
    return RetrievedDocument(
        document_id="doctors:D104",
        source_file="doctors.csv",
        record_id="D104",
        text="Doctor D104: Dr. James Wilson. Specialty: Orthopedics.",
        metadata={
            "name": "Dr. James Wilson",
            "doctor_id": "D104",
            "clinic_id": "C001",
            "specialty": "Orthopedics",
        },
    )


def test_knowledge_status_and_record_lookup(harness: AppHarness, login) -> None:
    assert login(harness.client).status_code == 303
    harness.app.state.knowledge_index.documents = [_document()]

    status = harness.client.get("/demo/api/knowledge/status")
    assert status.status_code == 200
    assert status.json()["ready"] is True
    assert status.json()["records"] == 1

    record = harness.client.get("/demo/api/knowledge/doctors.csv/D104")
    assert record.status_code == 200
    payload = record.json()
    assert payload["record_id"] == "D104"
    assert payload["citation"] == "[doc:D104]"
    assert "James Wilson" in payload["text"]


def test_knowledge_record_rejects_unknown_records(harness: AppHarness, login) -> None:
    assert login(harness.client).status_code == 303

    response = harness.client.get("/demo/api/knowledge/doctors.csv/D999")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_knowledge_routes_require_authentication(harness: AppHarness) -> None:
    assert harness.client.get("/demo/api/knowledge/status").status_code == 401
    assert harness.client.get("/demo/api/knowledge/doctors.csv/D104").status_code == 401
