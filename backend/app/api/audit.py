"""Session-scoped agent trace explorer."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.encoders import jsonable_encoder

from app.api.deps import get_clock, get_settings, require_api_session
from app.db.models import DemoSession
from app.services.audit import AuditService

router = APIRouter()


@router.get("/api/audit")
async def audit_events(
    request: Request,
    demo_session: Annotated[DemoSession, Depends(require_api_session)],
    limit: Annotated[int, Query(ge=1, le=1000)] = 300,
):
    settings = get_settings(request)
    events = await AuditService(request.app.state.session_factory, get_clock(request)).list_events(
        demo_session.id, limit=limit
    )
    return jsonable_encoder(
        {
            "events": [
                {
                    "id": event.id,
                    "conversation_id": event.conversation_id,
                    "turn_id": event.turn_id,
                    "event_type": event.event_type,
                    "name": event.name,
                    "status": event.status,
                    "payload": event.payload,
                    "created_at": event.created_at,
                }
                for event in events
            ],
            "pricing": {
                "input_per_million_usd": settings.model_input_price_per_million_usd,
                "output_per_million_usd": settings.model_output_price_per_million_usd,
                "cached_input_per_million_usd": settings.model_cached_input_price_per_million_usd,
                "version": settings.model_pricing_version,
            },
        }
    )
