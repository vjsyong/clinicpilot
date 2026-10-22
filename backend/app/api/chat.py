"""POST /api/chat: authenticated turns with replay-safe deduplication."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.encoders import jsonable_encoder
from starlette.responses import JSONResponse, Response

from app.api.deps import get_clock, get_settings, require_api_session, require_patient
from app.api.locks import conversation_lock
from app.contracts import ChatRequest
from app.db.models import DemoSession
from app.services.chat_turn import execute_turn
from app.services.conversations import ConversationService
from app.services.errors import NotFoundError, ServiceError
from app.services.hashing import chat_request_hash

router = APIRouter()


@router.post("/api/chat")
async def chat(
    payload: ChatRequest,
    request: Request,
    demo_session: Annotated[DemoSession, Depends(require_api_session)],
) -> Response:
    patient_id = require_patient(payload.patient_id)
    settings = get_settings(request)
    if len(payload.message) > settings.max_message_chars:
        raise ServiceError("The message is too long.", code="invalid_request", status_code=422)

    conversations = ConversationService(request.app.state.session_factory, get_clock(request))

    if payload.conversation_id:
        conversation = await conversations.get_conversation(payload.conversation_id)
        if conversation is None or conversation.demo_session_id != demo_session.id:
            raise NotFoundError("Conversation not found.")
        conversation_id = conversation.id
    else:
        conversation_id = await conversations.create_conversation(demo_session.id, patient_id)

    request_hash = chat_request_hash(payload.message, patient_id)
    started = await conversations.start_turn(conversation_id, payload.message_id, request_hash)
    if started.outcome == "replay" and started.response is not None:
        return JSONResponse(jsonable_encoder(started.response), status_code=200)
    if started.outcome == "conflict":
        raise ServiceError(
            "This message ID was already used with different content.",
            code="message_id_conflict",
            status_code=409,
        )
    if started.outcome == "in_progress":
        raise ServiceError(
            "This message is still being processed. Retry shortly.",
            code="turn_in_progress",
            status_code=409,
            retryable=True,
        )

    assert started.turn_id is not None
    turn_id = started.turn_id
    lock = conversation_lock(request, conversation_id)
    async with lock:
        controller = getattr(request.app.state, "controller", None)
        if controller is None:
            raise ServiceError(
                "The agent controller is not configured.",
                code="internal_error",
                status_code=500,
            )
        response = await execute_turn(
            controller=controller,
            conversations=conversations,
            conversation_id=conversation_id,
            turn_id=turn_id,
            client_message_id=payload.message_id,
            demo_session_id=str(demo_session.id),
            user_text=payload.message,
            now=get_clock(request).now(),
        )
        return JSONResponse(jsonable_encoder(response), status_code=200)
