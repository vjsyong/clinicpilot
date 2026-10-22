"""POST /api/chat: authenticated turns with replay-safe deduplication."""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.encoders import jsonable_encoder
from starlette.responses import JSONResponse, Response

from app.api.deps import get_clock, get_settings, require_api_session, require_patient
from app.contracts import (
    PATIENT_ID,
    ChatRequest,
    ChatResponse,
    ProviderError,
    TurnContext,
)
from app.db.models import DemoSession
from app.services.conversations import ConversationService
from app.services.errors import NotFoundError, ServiceError
from app.services.hashing import chat_request_hash

logger = logging.getLogger("clinicpilot.chat")

router = APIRouter()


def _lock_for(request: Request, conversation_id: str) -> asyncio.Lock:
    locks = getattr(request.app.state, "conversation_locks", None)
    if not isinstance(locks, dict):
        locks = {}
        request.app.state.conversation_locks = locks
    lock = locks.get(conversation_id)
    if not isinstance(lock, asyncio.Lock):
        lock = asyncio.Lock()
        locks[conversation_id] = lock
    return lock


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
    lock = _lock_for(request, conversation_id)
    async with lock:
        try:
            controller = getattr(request.app.state, "controller", None)
            if controller is None:
                raise RuntimeError("Agent controller is not configured")
            result = await controller.handle_turn(
                TurnContext(
                    conversation_id=conversation_id,
                    turn_id=turn_id,
                    demo_session_id=str(demo_session.id),
                    patient_id=PATIENT_ID,
                    user_text=payload.message,
                    now=get_clock(request).now(),
                )
            )
            response = ChatResponse(
                conversation_id=conversation_id,
                message_id=payload.message_id,
                assistant_message=result.assistant_message,
                sources=result.sources,
                booking_draft=result.booking_draft,
                events=result.events,
            )
            await conversations.finish_turn(turn_id, response)
            return JSONResponse(jsonable_encoder(response), status_code=200)
        except asyncio.CancelledError:
            await conversations.fail_turn(turn_id)
            raise
        except ProviderError:
            await conversations.fail_turn(turn_id)
            raise
        except ServiceError:
            await conversations.fail_turn(turn_id)
            raise
        except Exception:
            await conversations.fail_turn(turn_id)
            logger.exception("Chat turn %s failed", turn_id)
            raise ServiceError(
                "The server could not complete the request.",
                code="internal_error",
                status_code=500,
            ) from None
