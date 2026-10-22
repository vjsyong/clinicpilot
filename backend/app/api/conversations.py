"""Authenticated conversation history for the assistant rail."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import (
    get_clock,
    get_session_factory,
    get_settings,
    require_api_session,
)
from app.contracts import ConversationSummary, ConversationTranscript
from app.db.models import DemoSession
from app.services.conversations import ConversationService
from app.services.drafts import DraftService
from app.services.errors import ForbiddenError, NotFoundError

router = APIRouter()


def _conversations(request: Request) -> ConversationService:
    return ConversationService(get_session_factory(request), get_clock(request))


def _drafts(request: Request) -> DraftService:
    return DraftService(
        get_session_factory(request),
        get_clock(request),
        get_settings(request),
    )


async def _owned(conversation_id: str, demo_session: DemoSession, request: Request):
    record = await _conversations(request).get_conversation(conversation_id)
    if record is None:
        raise NotFoundError("Conversation not found.")
    if record.demo_session_id != demo_session.id:
        raise ForbiddenError("Conversation belongs to another session.")
    return record


@router.get("/api/conversations", response_model=list[ConversationSummary])
async def list_conversations(
    request: Request,
    demo_session: Annotated[DemoSession, Depends(require_api_session)],
) -> list[ConversationSummary]:
    return await _conversations(request).list_conversations(demo_session.id)


@router.get("/api/conversations/{conversation_id}", response_model=ConversationTranscript)
async def get_conversation(
    conversation_id: str,
    request: Request,
    demo_session: Annotated[DemoSession, Depends(require_api_session)],
) -> ConversationTranscript:
    await _owned(conversation_id, demo_session, request)
    transcript = await _conversations(request).get_transcript(conversation_id)
    if transcript is None:
        raise NotFoundError("Conversation not found.")
    transcript.draft = await _drafts(request).get(conversation_id)
    return transcript


@router.delete("/api/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: str,
    request: Request,
    demo_session: Annotated[DemoSession, Depends(require_api_session)],
) -> Response:
    await _owned(conversation_id, demo_session, request)
    deleted = await _conversations(request).delete_conversation(conversation_id)
    if not deleted:
        raise NotFoundError("Conversation not found.")
    return Response(status_code=204)
