"""Shared execution path for blocking and streamed chat turns."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from app.contracts import (
    PATIENT_ID,
    ChatResponse,
    ModelProvider,
    ProviderError,
    ProviderNotConfiguredError,
    TurnContext,
)
from app.services.conversations import ConversationService
from app.services.errors import ServiceError

logger = logging.getLogger("clinicpilot.chat_turn")


async def execute_turn(
    *,
    controller: Any,
    conversations: ConversationService,
    conversation_id: str,
    turn_id: str,
    client_message_id: str,
    demo_session_id: str,
    user_text: str,
    now: datetime,
    model: ModelProvider = "local",
    emit: Any = None,
) -> ChatResponse:
    """Run one turn, persist its response, and fail the turn on any error."""
    try:
        result = await controller.handle_turn(
            TurnContext(
                conversation_id=conversation_id,
                turn_id=turn_id,
                demo_session_id=demo_session_id,
                patient_id=PATIENT_ID,
                user_text=user_text,
                now=now,
                model=model,
            ),
            emit=emit,
        )
        response = ChatResponse(
            conversation_id=conversation_id,
            message_id=client_message_id,
            assistant_message=result.assistant_message,
            sources=result.sources,
            booking_draft=result.booking_draft,
            events=result.events,
            next_step=result.next_step,
        )
        await conversations.finish_turn(turn_id, response)
        return response
    except asyncio.CancelledError:
        await conversations.fail_turn(turn_id)
        raise
    except (ProviderError, ProviderNotConfiguredError):
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
