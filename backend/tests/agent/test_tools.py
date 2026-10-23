from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from app.agent.tools import BookingApiError, RestBookingApi, bookings_tool_result
from app.settings import Settings
from tests.agent.fakes import booking_view

INTERNAL_KEY = "test-internal-tool-key-0123456789abcdef"


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        internal_api_base_url="http://internal.test",
        internal_tool_key=INTERNAL_KEY,
    )


async def test_list_bookings_uses_internal_key_and_parses_views() -> None:
    view = booking_view()
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["key"] = request.headers.get("X-Internal-Tool-Key")
        return httpx.Response(200, json=[view.model_dump(mode="json")])

    async with httpx.AsyncClient(
        base_url="http://internal.test", transport=httpx.MockTransport(handler)
    ) as client:
        api = RestBookingApi(_settings(), client=client)
        bookings = await api.list_bookings("P001")

    assert seen == {"method": "GET", "path": "/api/bookings", "key": INTERNAL_KEY}
    assert bookings == [view]


async def test_list_bookings_refuses_other_patients_without_a_request() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=[])

    async with httpx.AsyncClient(
        base_url="http://internal.test", transport=httpx.MockTransport(handler)
    ) as client:
        api = RestBookingApi(_settings(), client=client)
        with pytest.raises(BookingApiError):
            await api.list_bookings("P002")

    assert calls == 0


async def test_create_booking_posts_server_owned_idempotency_key() -> None:
    view = booking_view()
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["key"] = request.headers.get("X-Internal-Tool-Key")
        seen["idempotency"] = request.headers.get("Idempotency-Key")
        seen["body"] = json.loads(request.content)
        return httpx.Response(201, json=view.model_dump(mode="json"))

    async with httpx.AsyncClient(
        base_url="http://internal.test", transport=httpx.MockTransport(handler)
    ) as client:
        api = RestBookingApi(_settings(), client=client)
        created = await api.create_booking("draft-7", 3)

    assert created == view
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/bookings"
    assert seen["key"] == INTERNAL_KEY
    assert seen["idempotency"] == "booking:draft-7:v3"
    assert seen["body"] == {"draft_id": "draft-7", "draft_version": 3}


async def test_idempotent_replay_200_is_accepted() -> None:
    view = booking_view()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=view.model_dump(mode="json"))

    async with httpx.AsyncClient(
        base_url="http://internal.test", transport=httpx.MockTransport(handler)
    ) as client:
        api = RestBookingApi(_settings(), client=client)
        created = await api.create_booking("draft-7", 3)

    assert created == view


async def test_conflict_is_a_safe_booking_api_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            409,
            json={
                "error": {
                    "code": "idempotency_conflict",
                    "message": "raw internal detail that must not leak",
                    "retryable": False,
                },
                "request_id": "req-1",
            },
        )

    async with httpx.AsyncClient(
        base_url="http://internal.test", transport=httpx.MockTransport(handler)
    ) as client:
        api = RestBookingApi(_settings(), client=client)
        with pytest.raises(BookingApiError) as excinfo:
            await api.create_booking("draft-7", 3)

    error = excinfo.value
    assert error.status_code == 409
    assert error.code == "idempotency_conflict"
    assert "raw internal detail" not in error.safe_message


async def test_transport_timeout_is_safe_and_retryable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("upstream timeout", request=request)

    async with httpx.AsyncClient(
        base_url="http://internal.test", transport=httpx.MockTransport(handler)
    ) as client:
        api = RestBookingApi(_settings(), client=client)
        with pytest.raises(BookingApiError) as excinfo:
            await api.list_bookings()

    assert excinfo.value.retryable
    assert "draft was kept" in excinfo.value.safe_message


async def test_invalid_payload_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"not": "a booking"})

    async with httpx.AsyncClient(
        base_url="http://internal.test", transport=httpx.MockTransport(handler)
    ) as client:
        api = RestBookingApi(_settings(), client=client)
        with pytest.raises(BookingApiError):
            await api.create_booking("draft-7", 3)


def test_bookings_tool_result_marks_upcoming_and_past() -> None:
    now = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
    upcoming = booking_view(booking_id="B2001")
    past = booking_view(
        booking_id="B2002",
        local_date="2026-10-20",
        starts_at_utc=datetime(2026, 10, 20, 14, 0, tzinfo=UTC),
    )

    result = bookings_tool_result([upcoming, past], now=now)
    items = result.payload["bookings"]

    assert [item["booking_id"] for item in items] == ["B2001", "B2002"]
    assert items[0]["is_upcoming"] is True
    assert items[1]["is_upcoming"] is False
