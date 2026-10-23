"""SSE chat streaming with replay, re-attachment, and cooperative stop."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from starlette.responses import Response, StreamingResponse

from app.api.deps import (
    get_clock,
    get_settings,
    require_api_session,
    require_model_available,
    require_patient,
)
from app.api.locks import conversation_lock
from app.contracts import (
    ChatRequest,
    ChatResponse,
    ModelProvider,
    ProviderError,
    ProviderNotConfiguredError,
)
from app.db.models import DemoSession
from app.services.chat_turn import execute_turn
from app.services.conversations import ConversationService, TurnStart
from app.services.errors import NotFoundError, ServiceError
from app.services.hashing import chat_request_hash

logger = logging.getLogger("clinicpilot.chat_stream")

router = APIRouter()

_RUN_REPLAY_SECONDS = 60


class RegenerateRequest(BaseModel):
    conversation_id: str
    message_id: str
    model: ModelProvider = "local"


class ChatRun:
    """One background turn with a replayable event log."""

    def __init__(
        self,
        *,
        turn_id: str,
        conversation_id: str,
        client_message_id: str,
        demo_session_id: int,
        model: ModelProvider = "local",
    ) -> None:
        self.turn_id = turn_id
        self.conversation_id = conversation_id
        self.client_message_id = client_message_id
        self.demo_session_id = demo_session_id
        self.model = model
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.condition = asyncio.Condition()
        self.done = False
        self.cancelled = False
        self.response: ChatResponse | None = None
        self.task: asyncio.Task[None] | None = None
        self.created_at = time.monotonic()
        self.finished_at: float | None = None

    async def emit(self, event: str, data: dict[str, Any]) -> None:
        async with self.condition:
            self.events.append((event, data))
            self.condition.notify_all()

    async def finish(self) -> None:
        async with self.condition:
            self.done = True
            self.finished_at = time.monotonic()
            self.condition.notify_all()


class ChatRunRegistry:
    def __init__(self) -> None:
        self._runs: dict[str, ChatRun] = {}

    def add(self, run: ChatRun) -> None:
        self._runs[run.turn_id] = run
        self.prune()

    def get(self, turn_id: str) -> ChatRun | None:
        self.prune()
        return self._runs.get(turn_id)

    def prune(self) -> None:
        now = time.monotonic()
        expired = [
            turn_id
            for turn_id, run in self._runs.items()
            if run.done
            and run.finished_at is not None
            and now - run.finished_at > _RUN_REPLAY_SECONDS
        ]
        for turn_id in expired:
            self._runs.pop(turn_id, None)

    async def shutdown(self) -> None:
        tasks = [
            run.task for run in self._runs.values() if run.task is not None and not run.task.done()
        ]
        for run in self._runs.values():
            run.cancelled = True
            if run.task is not None and not run.task.done():
                run.task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


def _registry(request: Request) -> ChatRunRegistry:
    registry = getattr(request.app.state, "chat_runs", None)
    if not isinstance(registry, ChatRunRegistry):
        registry = ChatRunRegistry()
        request.app.state.chat_runs = registry
    return registry


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(jsonable_encoder(data), ensure_ascii=False)}\n\n"


async def _tail(run: ChatRun, cursor: int = 0) -> AsyncIterator[str]:
    while True:
        event: tuple[str, dict[str, Any]] | None = None
        async with run.condition:
            if cursor >= len(run.events) and not run.done:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(run.condition.wait(), timeout=10)
            if cursor < len(run.events):
                event = run.events[cursor]
                cursor += 1
        if event is not None:
            yield _sse(*event)
        elif run.done:
            return
        else:
            yield ": keep-alive\n\n"


def _stream(run: ChatRun, cursor: int = 0) -> StreamingResponse:
    async def generator() -> AsyncIterator[str]:
        async for frame in _tail(run, cursor):
            yield frame

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _prepare(
    payload: ChatRequest,
    request: Request,
    demo_session: DemoSession,
    model: ModelProvider,
) -> tuple[ConversationService, str, TurnStart]:
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
    if started.outcome == "new":
        try:
            require_model_available(request, model)
        except ServiceError:
            if started.turn_id is not None:
                await conversations.fail_turn(started.turn_id)
            raise
    return conversations, conversation_id, started


async def _run(
    run: ChatRun,
    request: Request,
    conversations: ConversationService,
    user_text: str,
    now: Any,
) -> None:
    lock = conversation_lock(request, run.conversation_id)
    try:
        async with lock:
            if run.cancelled:
                raise asyncio.CancelledError
            response = await execute_turn(
                controller=request.app.state.controller,
                conversations=conversations,
                conversation_id=run.conversation_id,
                turn_id=run.turn_id,
                client_message_id=run.client_message_id,
                demo_session_id=str(run.demo_session_id),
                user_text=user_text,
                now=now,
                model=run.model,
                emit=run.emit,
            )
            run.response = response
            await run.emit("done", response.model_dump(mode="json"))
    except asyncio.CancelledError:
        if run.response is None:
            await conversations.fail_turn(run.turn_id)
        await run.emit("stopped", {})
    except ProviderNotConfiguredError as exc:
        await run.emit(
            "error",
            {
                "code": "provider_not_configured",
                "message": str(exc),
                "retryable": False,
            },
        )
    except ProviderError:
        await run.emit(
            "error",
            {
                "code": "provider_error",
                "message": "The generation provider failed. Please retry.",
                "retryable": True,
            },
        )
    except ServiceError as exc:
        await run.emit(
            "error",
            {
                "code": exc.code,
                "message": exc.message,
                "retryable": exc.retryable,
            },
        )
    except Exception:
        logger.exception("Streamed chat turn %s failed", run.turn_id)
        await run.emit(
            "error",
            {
                "code": "internal_error",
                "message": "The server could not complete the request.",
                "retryable": False,
            },
        )
    finally:
        await run.finish()


@router.post("/api/chat/stream")
async def chat_stream(
    payload: ChatRequest,
    request: Request,
    demo_session: Annotated[DemoSession, Depends(require_api_session)],
) -> Response:
    conversations, conversation_id, started = await _prepare(
        payload, request, demo_session, payload.model
    )
    registry = _registry(request)

    if started.outcome == "replay" and started.response is not None:
        run = ChatRun(
            turn_id=started.turn_id or payload.message_id,
            conversation_id=conversation_id,
            client_message_id=payload.message_id,
            demo_session_id=demo_session.id,
            model=payload.model,
        )
        run.events.append(
            (
                "session",
                {
                    "conversation_id": conversation_id,
                    "turn_id": run.turn_id,
                    "message_id": payload.message_id,
                },
            )
        )
        run.events.append(("done", started.response.model_dump(mode="json")))
        run.response = started.response
        await run.finish()
        registry.add(run)
        return _stream(run)

    if started.outcome == "conflict":
        raise ServiceError(
            "This message ID was already used with different content.",
            code="message_id_conflict",
            status_code=409,
        )
    if started.outcome == "in_progress":
        turn_id = await conversations.pending_turn_id(conversation_id, payload.message_id)
        existing = registry.get(turn_id) if turn_id else None
        if existing is not None:
            return _stream(existing)
        raise ServiceError(
            "This message is still being processed. Retry shortly.",
            code="turn_in_progress",
            status_code=409,
            retryable=True,
        )

    assert started.turn_id is not None
    run = ChatRun(
        turn_id=started.turn_id,
        conversation_id=conversation_id,
        client_message_id=payload.message_id,
        demo_session_id=demo_session.id,
        model=payload.model,
    )
    run.events.append(
        (
            "session",
            {
                "conversation_id": conversation_id,
                "turn_id": run.turn_id,
                "message_id": payload.message_id,
            },
        )
    )
    registry.add(run)
    run.task = asyncio.create_task(
        _run(
            run,
            request,
            conversations,
            payload.message,
            get_clock(request).now(),
        )
    )
    return _stream(run)


@router.post("/api/chat/regenerate")
async def chat_regenerate(
    payload: RegenerateRequest,
    request: Request,
    demo_session: Annotated[DemoSession, Depends(require_api_session)],
) -> Response:
    require_model_available(request, payload.model)
    conversations = ConversationService(request.app.state.session_factory, get_clock(request))
    conversation = await conversations.get_conversation(payload.conversation_id)
    if conversation is None or conversation.demo_session_id != demo_session.id:
        raise NotFoundError("Conversation not found.")
    prepared = await conversations.prepare_regeneration(payload.conversation_id, payload.message_id)
    if prepared is None:
        raise NotFoundError("Nothing to regenerate.")
    run = ChatRun(
        turn_id=prepared.turn_id,
        conversation_id=prepared.conversation_id,
        client_message_id=prepared.client_message_id,
        demo_session_id=demo_session.id,
        model=payload.model,
    )
    run.events.append(
        (
            "session",
            {
                "conversation_id": prepared.conversation_id,
                "turn_id": prepared.turn_id,
                "message_id": payload.message_id,
            },
        )
    )
    _registry(request).add(run)
    run.task = asyncio.create_task(
        _run(
            run,
            request,
            conversations,
            prepared.user_text,
            get_clock(request).now(),
        )
    )
    return _stream(run)


@router.get("/api/chat/runs/{turn_id}")
async def chat_run_events(
    turn_id: str,
    request: Request,
    demo_session: Annotated[DemoSession, Depends(require_api_session)],
) -> Response:
    run = _registry(request).get(turn_id)
    if run is None or run.demo_session_id != demo_session.id:
        raise NotFoundError("Chat run not found.")
    return _stream(run)


@router.post("/api/chat/runs/{turn_id}/stop")
async def stop_chat_run(
    turn_id: str,
    request: Request,
    demo_session: Annotated[DemoSession, Depends(require_api_session)],
) -> dict[str, bool]:
    run = _registry(request).get(turn_id)
    if run is None or run.demo_session_id != demo_session.id:
        raise NotFoundError("Chat run not found.")
    if run.done or run.task is None or run.task.done():
        return {"stopped": False}
    run.cancelled = True
    run.task.cancel()
    return {"stopped": True}
