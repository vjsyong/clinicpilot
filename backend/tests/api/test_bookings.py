from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from app.auth.sessions import SessionService
from app.contracts import PATIENT_ID
from app.db.models import PatientBooking
from app.main import create_app
from app.services.bookings import BookingService
from app.services.conversations import ConversationService
from app.services.drafts import DraftService
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from tests.conftest import (
    ORIGIN,
    TEST_INTERNAL_KEY,
    AppHarness,
    DBHarness,
    FakeController,
    FakeIndex,
)

INTERNAL = {"X-Internal-Tool-Key": TEST_INTERNAL_KEY}


async def _authorized_draft(harness: AppHarness, *, authorize: bool = True) -> tuple[str, str, Any]:
    sessions = SessionService(harness.session_factory, harness.clock, harness.settings)
    token, session = await sessions.create_session()
    conversations = ConversationService(harness.session_factory, harness.clock)
    conversation_id = await conversations.create_conversation(session.id, PATIENT_ID)
    drafts = DraftService(harness.session_factory, harness.clock, harness.settings)
    update = await drafts.update(
        conversation_id,
        {
            "doctor_id": "D104",
            "treatment_id": "T005",
            "local_date": "2026-11-17",
            "local_time": "15:00",
        },
    )
    assert update.draft is not None
    if authorize:
        await drafts.mark_presented(conversation_id, "assistant-1", update.draft.version)
        await drafts.authorize(conversation_id, "turn-1")
    return token, conversation_id, update.draft


def _key(draft: Any) -> str:
    return f"booking:{draft.draft_id}:v{draft.version}"


def _create(client: TestClient, draft: Any, **overrides: Any) -> Any:
    body = {"draft_id": draft.draft_id, "draft_version": draft.version}
    body.update(overrides)
    return client.post(
        "/demo/api/bookings",
        json=body,
        headers={**INTERNAL, "Idempotency-Key": _key(draft)},
    )


def test_get_bookings_requires_authentication(harness: AppHarness) -> None:
    response = harness.client.get("/demo/api/bookings")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_get_bookings_with_internal_key(harness: AppHarness) -> None:
    response = harness.client.get("/demo/api/bookings", headers=INTERNAL)
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 2
    assert items[0]["booking_id"] == "B1001"
    assert items[0]["doctor_name"] == "Dr. Sarah Jenkins"
    assert items[0]["treatment_name"] == "General Health Checkup"
    assert items[0]["timezone"] == "America/New_York"
    assert items[0]["starts_at_utc"] == "2026-11-05T14:00:00Z"
    assert items[-1]["booking_id"] == "B1004"


def test_get_bookings_with_browser_session(harness: AppHarness) -> None:
    token, _conversation, _draft = asyncio.run(_authorized_draft(harness))
    harness.client.cookies.set("clinicpilot_session", token, path="/demo/")
    response = harness.client.get("/demo/api/bookings")
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_post_bookings_rejects_cookie_only(harness: AppHarness) -> None:
    token, _conversation, draft = asyncio.run(_authorized_draft(harness))
    harness.client.cookies.set("clinicpilot_session", token, path="/demo/")
    response = harness.client.post(
        "/demo/api/bookings",
        json={"draft_id": draft.draft_id, "draft_version": draft.version},
        headers={**ORIGIN, "Idempotency-Key": _key(draft)},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_post_bookings_creates_and_replays(harness: AppHarness, db: DBHarness) -> None:
    _token, _conversation, draft = asyncio.run(_authorized_draft(harness))

    created = _create(harness.client, draft)
    assert created.status_code == 201
    body = created.json()
    assert body["booking_id"] == "B1005"
    assert body["doctor_id"] == "D104"
    assert body["treatment_id"] == "T005"
    assert body["timezone"] == "America/New_York"

    replay = _create(harness.client, draft)
    assert replay.status_code == 200
    assert replay.json()["booking_id"] == body["booking_id"]

    with db.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(PatientBooking)) == 5


def test_post_bookings_idempotency_details_conflict(harness: AppHarness, db: DBHarness) -> None:
    _token, _conversation, draft = asyncio.run(_authorized_draft(harness))
    created = _create(harness.client, draft)
    assert created.status_code == 201

    with db.engine.connect() as connection:
        connection.exec_driver_sql(
            "UPDATE booking_drafts SET notes = ? WHERE id = ?",
            ("different canonical details", draft.draft_id),
        )
        connection.commit()

    replay = _create(harness.client, draft)
    assert replay.status_code == 409
    assert replay.json()["error"]["code"] == "idempotency_conflict"


def test_post_bookings_version_mismatch_conflicts(harness: AppHarness) -> None:
    _token, _conversation, draft = asyncio.run(_authorized_draft(harness))
    wrong_version = draft.version + 1
    response = harness.client.post(
        "/demo/api/bookings",
        json={"draft_id": draft.draft_id, "draft_version": wrong_version},
        headers={
            **INTERNAL,
            "Idempotency-Key": f"booking:{draft.draft_id}:v{wrong_version}",
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "draft_version_conflict"


def test_post_bookings_requires_confirmation(harness: AppHarness) -> None:
    _token, _conversation, draft = asyncio.run(_authorized_draft(harness, authorize=False))
    response = _create(harness.client, draft)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "confirmation_required"


def test_post_bookings_rejects_invalid_details_422(harness: AppHarness, db: DBHarness) -> None:
    _token, _conversation, draft = asyncio.run(_authorized_draft(harness))

    statements = {
        "doctor_id": "UPDATE booking_drafts SET doctor_id = ? WHERE id = ?",
        "treatment_id": "UPDATE booking_drafts SET treatment_id = ? WHERE id = ?",
    }

    def tamper(column: str, value: str) -> None:
        with db.engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.exec_driver_sql(
                statements[column],
                (value, draft.draft_id),
            )
            connection.commit()

    tamper("doctor_id", "D999")
    invalid_doctor = _create(harness.client, draft)
    assert invalid_doctor.status_code == 422
    assert invalid_doctor.json()["error"]["code"] == "invalid_booking_details"

    tamper("doctor_id", "D104")
    tamper("treatment_id", "T999")
    invalid_treatment = _create(harness.client, draft)
    assert invalid_treatment.status_code == 422

    tamper("treatment_id", "T002")
    incompatible = _create(harness.client, draft)
    assert incompatible.status_code == 422

    tamper("treatment_id", "T005")
    harness.clock.current = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
    past = _create(harness.client, draft)
    assert past.status_code == 422
    assert past.json()["error"]["code"] == "invalid_booking_details"


def test_post_bookings_requires_idempotency_header(harness: AppHarness) -> None:
    _token, _conversation, draft = asyncio.run(_authorized_draft(harness))
    response = harness.client.post(
        "/demo/api/bookings",
        json={"draft_id": draft.draft_id, "draft_version": draft.version},
        headers=INTERNAL,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_booking_details"


def test_booking_survives_app_restart(harness: AppHarness, db: DBHarness) -> None:
    _token, _conversation, draft = asyncio.run(_authorized_draft(harness))
    created = _create(harness.client, draft)
    assert created.status_code == 201
    booking_id = created.json()["booking_id"]

    asgi = create_app(
        harness.settings,
        controller_factory=lambda *_args, **_kwargs: FakeController(),
        index_factory=lambda *_args, **_kwargs: FakeIndex(),
    )
    with TestClient(asgi) as restarted:
        response = restarted.get("/demo/api/bookings", headers=INTERNAL)
        assert response.status_code == 200
        assert any(item["booking_id"] == booking_id for item in response.json())

    with db.session_factory() as session:
        service = BookingService(db.session_factory, harness.clock, harness.settings)
        listed = asyncio.run(service.list_bookings())
        assert any(item.booking_id == booking_id for item in listed)
        assert session.get(PatientBooking, booking_id) is not None


def test_delete_booking_hides_it_with_browser_session(harness: AppHarness, db: DBHarness) -> None:
    token, _conversation, _draft = asyncio.run(_authorized_draft(harness))
    harness.client.cookies.set("clinicpilot_session", token, path="/demo/")

    response = harness.client.delete("/demo/api/bookings/B1001", headers=ORIGIN)
    assert response.status_code == 200
    assert response.json()["booking_id"] == "B1001"

    listed = harness.client.get("/demo/api/bookings")
    assert all(item["booking_id"] != "B1001" for item in listed.json())
    with db.session_factory() as session:
        row = session.get(PatientBooking, "B1001")
        assert row is not None
        assert row.deleted_at is not None


def test_delete_booking_requires_authentication(harness: AppHarness) -> None:
    response = harness.client.delete("/demo/api/bookings/B1001", headers=ORIGIN)
    assert response.status_code == 401


def test_reset_demo_restores_the_seed_workspace(harness: AppHarness, db: DBHarness) -> None:
    token, _conversation, _draft = asyncio.run(_authorized_draft(harness))
    harness.client.cookies.set("clinicpilot_session", token, path="/demo/")

    response = harness.client.post("/demo/api/demo/reset", headers=ORIGIN)

    assert response.status_code == 200
    body = response.json()
    assert body["restored_bookings"] == ["B1001", "B1004"]
    assert body["cleared_conversations"] >= 1
    listed = harness.client.get("/demo/api/bookings").json()
    assert [item["booking_id"] for item in listed] == ["B1001", "B1004"]
    with db.session_factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(PatientBooking)
                .where(PatientBooking.patient_id == PATIENT_ID)
            )
            == 2
        )
