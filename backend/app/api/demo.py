"""Explicit shared-demo reset."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.encoders import jsonable_encoder
from starlette.responses import JSONResponse, Response

from app.api.deps import get_clock, get_settings, require_api_session
from app.db.models import DemoSession
from app.services.audit import AuditService
from app.services.workspace import WorkspaceService

router = APIRouter()


@router.post("/api/demo/reset")
async def reset_demo(
    request: Request,
    demo_session: Annotated[DemoSession, Depends(require_api_session)],
) -> Response:
    runs = getattr(request.app.state, "chat_runs", None)
    if runs is not None:
        await runs.shutdown()
    result = await WorkspaceService(
        request.app.state.session_factory,
        get_clock(request),
        get_settings(request),
    ).reset()
    await AuditService(request.app.state.session_factory, get_clock(request)).record(
        demo_session_id=demo_session.id,
        conversation_id=None,
        turn_id=None,
        event_type="action",
        name="workspace_reset",
        status="ok",
        payload={
            "restored_bookings": result.restored_bookings,
            "removed_bookings": result.removed_bookings,
            "cleared_conversations": result.cleared_conversations,
        },
    )
    return JSONResponse(jsonable_encoder(result), status_code=200)
