"""Internal REST booking adapter and model-facing tool result helpers.

The agent never opens the database for bookings. Every read and write goes
through the internal HTTP API, using a server-owned key and idempotency key.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.contracts import PATIENT_ID, BookingView, ModelToolCall
from app.settings import Settings

INTERNAL_TIMEOUT_SECONDS = 15.0
BOOKING_CREATE_KEY_PREFIX = "booking"


class BookingApiError(RuntimeError):
    """A safe, transport-independent booking API failure."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.safe_message = message
        self.status_code = status_code
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class ToolResult:
    """One provider-facing tool message.

    ``content`` is already a compact JSON document. Errors are normal tool
    results so the model can recover without crashing the turn.
    """

    content: str
    is_error: bool = False
    payload: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def ok(cls, payload: Mapping[str, Any] | None = None) -> ToolResult:
        document: dict[str, Any] = {"ok": True}
        if payload:
            document.update(payload)
        return cls(content=_encode(document), payload=document)

    @classmethod
    def error(
        cls,
        message: str,
        *,
        code: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> ToolResult:
        document: dict[str, Any] = {"ok": False, "error": message}
        if code:
            document["code"] = code
        if details:
            document.update(details)
        return cls(content=_encode(document), is_error=True, payload=document)


def booking_tool_result(booking: BookingView) -> ToolResult:
    return ToolResult.ok({"booking": booking.model_dump(mode="json")})


def bookings_tool_result(bookings: Sequence[BookingView]) -> ToolResult:
    return ToolResult.ok({"bookings": [booking.model_dump(mode="json") for booking in bookings]})


def invalid_tool_result(call: ModelToolCall, message: str) -> ToolResult:
    return ToolResult.error(
        message,
        code="invalid_tool_call",
        details={"tool": call.name},
    )


def _encode(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


class RestBookingApi:
    """Implements ``app.contracts.BookingApi`` over the internal HTTP API."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=settings.internal_api_base_url,
            headers={"X-Internal-Tool-Key": settings.internal_tool_key},
            timeout=INTERNAL_TIMEOUT_SECONDS,
        )

    async def list_bookings(self, patient_id: str = PATIENT_ID) -> list[BookingView]:
        if patient_id != PATIENT_ID:
            raise BookingApiError("Only the demo patient P001 is available.")
        response = await self._request("GET", "api/bookings")
        payload = _json_payload(response)
        if not isinstance(payload, list):
            raise BookingApiError(
                "The booking service returned an invalid response.", retryable=True
            )
        views = [_booking_view(item) for item in payload]
        return [view for view in views if view.patient_id == PATIENT_ID]

    async def create_booking(self, draft_id: str, draft_version: int) -> BookingView:
        idempotency_key = f"{BOOKING_CREATE_KEY_PREFIX}:{draft_id}:v{draft_version}"
        response = await self._request(
            "POST",
            "api/bookings",
            json={"draft_id": draft_id, "draft_version": draft_version},
            headers={"Idempotency-Key": idempotency_key},
        )
        booking = _booking_view(_json_payload(response))
        if booking.patient_id != PATIENT_ID:
            raise BookingApiError(
                "The booking service returned a booking for an unexpected patient.",
                retryable=False,
            )
        return booking

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        request_headers = {"X-Internal-Tool-Key": self._settings.internal_tool_key}
        if headers:
            request_headers.update(headers)
        try:
            response = await self._client.request(
                method,
                path,
                json=json,
                headers=request_headers,
            )
        except httpx.TimeoutException as exc:
            raise BookingApiError(
                "The booking service did not respond in time. The draft was kept; please retry.",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise BookingApiError(
                "The booking service is temporarily unavailable. The draft was kept; please retry.",
                retryable=True,
            ) from exc

        if response.status_code < 200 or response.status_code >= 300:
            raise _error_from_response(response)
        return response


def _json_payload(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise BookingApiError(
            "The booking service returned an invalid response.", retryable=True
        ) from exc


def _booking_view(payload: Any) -> BookingView:
    if not isinstance(payload, dict):
        raise BookingApiError("The booking service returned an invalid response.", retryable=True)
    try:
        return BookingView.model_validate(payload)
    except ValueError as exc:
        raise BookingApiError(
            "The booking service returned an invalid response.", retryable=True
        ) from exc


def _error_from_response(response: httpx.Response) -> BookingApiError:
    status = response.status_code
    code = _error_code(response)
    if status == 409:
        message = (
            "The booking conflicts with an existing record. The draft was kept; "
            "please review the details and try again."
        )
    elif status == 422:
        message = (
            "The booking details were rejected. The draft was kept; please review "
            "the details and confirm again."
        )
    elif status in {401, 403}:
        message = "The internal booking service rejected the request."
    elif status >= 500:
        message = (
            "The booking service is temporarily unavailable. The draft was kept; "
            "no booking was created. Please retry."
        )
    else:
        message = "The booking service could not complete the request. The draft was kept."
    return BookingApiError(
        message,
        status_code=status,
        code=code,
        retryable=status >= 500,
    )


def _error_code(response: httpx.Response) -> str | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    if not isinstance(error, dict):
        return None
    code = error.get("code")
    return code if isinstance(code, str) else None
