"""GET and internal-only POST /api/bookings."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse, Response

from app.api.deps import (
    get_clock,
    get_settings,
    has_internal_key,
    require_internal_key,
    resolve_session,
)
from app.contracts import PATIENT_ID
from app.services.bookings import BookingService
from app.services.errors import ServiceError

router = APIRouter()


class BookingCreateRequest(BaseModel):
    draft_id: str = Field(min_length=1, max_length=200)
    draft_version: int = Field(ge=1)


@router.get("/api/bookings")
async def list_bookings(request: Request) -> Response:
    session = await resolve_session(request)
    if session is None and not has_internal_key(request):
        raise ServiceError("Authentication required.", code="unauthorized", status_code=401)
    service = BookingService(
        request.app.state.session_factory, get_clock(request), get_settings(request)
    )
    views = await service.list_bookings(PATIENT_ID)
    return JSONResponse(jsonable_encoder(views), status_code=200)


@router.post("/api/bookings", dependencies=[Depends(require_internal_key)])
async def create_booking(
    payload: BookingCreateRequest,
    request: Request,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Response:
    if not idempotency_key:
        raise ServiceError(
            "The Idempotency-Key header is required.",
            code="invalid_booking_details",
            status_code=422,
        )
    service = BookingService(
        request.app.state.session_factory, get_clock(request), get_settings(request)
    )
    view, created = await service.create_from_draft(
        payload.draft_id,
        payload.draft_version,
        idempotency_key,
    )
    return JSONResponse(jsonable_encoder(view), status_code=201 if created else 200)
