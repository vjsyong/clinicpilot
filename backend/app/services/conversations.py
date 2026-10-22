"""Conversation persistence and per-message turn deduplication."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.contracts import (
    PATIENT_ID,
    ChatResponse,
    ChatTurnStatus,
    Clock,
    ConversationSummary,
    ConversationTranscript,
    DraftStatus,
    ToolTrace,
    TranscriptTurn,
)
from app.db.models import BookingDraft, ChatTurn, Conversation
from app.services.errors import NotFoundError, ServiceError
from app.services.hashing import chat_request_hash
from app.services.tool_summary import result_sources, tool_summary

TurnOutcome = Literal["new", "replay", "conflict", "in_progress"]


@dataclass(frozen=True)
class ConversationRecord:
    id: str
    demo_session_id: int
    patient_id: str
    messages: list[dict[str, Any]]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class TurnStart:
    outcome: TurnOutcome
    turn_id: str | None = None
    response: ChatResponse | None = None


@dataclass(frozen=True)
class PreparedRegeneration:
    conversation_id: str
    turn_id: str
    client_message_id: str
    user_text: str


class ConversationService:
    """Implements ``app.contracts.ConversationStore`` plus conversation CRUD."""

    def __init__(self, session_factory: sessionmaker[Session], clock: Clock) -> None:
        self._session_factory = session_factory
        self._clock = clock

    async def create_conversation(
        self, demo_session_id: int | str, patient_id: str = PATIENT_ID
    ) -> str:
        conversation_id = str(uuid.uuid4())
        now = self._clock.now()
        session = self._session_factory()
        try:
            session.add(
                Conversation(
                    id=conversation_id,
                    demo_session_id=int(demo_session_id),
                    patient_id=patient_id,
                    messages_json="[]",
                    created_at=now,
                    updated_at=now,
                )
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
        return conversation_id

    async def get_conversation(self, conversation_id: str) -> ConversationRecord | None:
        session = self._session_factory()
        try:
            conversation = session.get(Conversation, conversation_id)
            if conversation is None:
                return None
            return ConversationRecord(
                id=conversation.id,
                demo_session_id=conversation.demo_session_id,
                patient_id=conversation.patient_id,
                messages=_decode_messages(conversation.messages_json),
                created_at=conversation.created_at,
                updated_at=conversation.updated_at,
            )
        finally:
            session.close()

    async def delete_conversation(self, conversation_id: str) -> bool:
        session = self._session_factory()
        try:
            conversation = session.get(Conversation, conversation_id)
            if conversation is None:
                return False
            for turn in session.scalars(
                select(ChatTurn).where(ChatTurn.conversation_id == conversation_id)
            ):
                session.delete(turn)
            for draft in session.scalars(
                select(BookingDraft).where(BookingDraft.conversation_id == conversation_id)
            ):
                session.delete(draft)
            session.delete(conversation)
            session.commit()
            return True
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    async def load_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        record = await self.get_conversation(conversation_id)
        if record is None:
            raise NotFoundError("Conversation not found.")
        return list(record.messages)

    async def list_conversations(
        self, demo_session_id: int | str, limit: int = 50
    ) -> list[ConversationSummary]:
        session = self._session_factory()
        try:
            conversations = session.scalars(
                select(Conversation)
                .where(Conversation.demo_session_id == int(demo_session_id))
                .order_by(Conversation.updated_at.desc())
                .limit(max(1, min(limit, 100)))
            ).all()
            return [_summary(session, conversation) for conversation in conversations]
        finally:
            session.close()

    async def prepare_regeneration(
        self, conversation_id: str, expected_message_id: str
    ) -> PreparedRegeneration | None:
        """Trim the last assistant reply and start a fresh turn for the same user message.

        Refuses confirmation turns and turns that already created a booking so a
        regenerate can never repeat a write or bypass the confirmation boundary.
        """
        from app.agent.controller import is_confirmation_phrase

        session = self._session_factory()
        try:
            conversation = session.get(Conversation, conversation_id)
            if conversation is None:
                return None
            messages = _decode_messages(conversation.messages_json)
            last_user_index = -1
            for index, message in enumerate(messages):
                if message.get("role") == "user":
                    last_user_index = index
            if last_user_index < 0:
                return None
            user_message = messages[last_user_index]
            user_text = str(user_message.get("content") or "").strip()
            if not user_text:
                return None
            if is_confirmation_phrase(user_text):
                raise ServiceError(
                    "Confirmation turns cannot be regenerated.",
                    code="conflict",
                    status_code=409,
                )
            last_assistant = next(
                (
                    message
                    for message in reversed(messages[last_user_index + 1 :])
                    if message.get("role") == "assistant"
                ),
                None,
            )
            presented_draft = session.scalar(
                select(BookingDraft)
                .where(
                    BookingDraft.conversation_id == conversation_id,
                    BookingDraft.status == DraftStatus.AWAITING_CONFIRMATION.value,
                    BookingDraft.confirmation_message_id.is_not(None),
                )
                .order_by(BookingDraft.created_at.desc(), BookingDraft.id.desc())
                .limit(1)
            )
            if (
                last_assistant is not None
                and presented_draft is not None
                and presented_draft.confirmation_message_id == last_assistant.get("_cp_message_id")
            ):
                raise ServiceError(
                    "The current booking summary cannot be regenerated. Ask for it again.",
                    code="conflict",
                    status_code=409,
                )
            old_turn_id = user_message.get("_cp_message_id")
            old_turn = session.get(ChatTurn, old_turn_id) if old_turn_id else None
            if old_turn is not None and old_turn.client_message_id != expected_message_id:
                raise ServiceError(
                    "Only the latest reply can be regenerated.",
                    code="conflict",
                    status_code=409,
                )
            if old_turn is not None and old_turn.status == ChatTurnStatus.IN_PROGRESS.value:
                raise ServiceError(
                    "This reply is still being generated.",
                    code="turn_in_progress",
                    status_code=409,
                    retryable=True,
                )
            if old_turn is not None and old_turn.response_json:
                response = ChatResponse.model_validate_json(old_turn.response_json)
                if any(event.type == "booking_created" for event in response.events):
                    raise ServiceError(
                        "A completed booking cannot be regenerated.",
                        code="conflict",
                        status_code=409,
                    )
            trimmed = messages[: last_user_index + 1]
        finally:
            session.close()

        client_message_id = (
            old_turn.client_message_id if old_turn is not None else f"regen-{uuid.uuid4().hex}"
        )
        if old_turn is not None:
            cleanup = self._session_factory()
            try:
                previous = cleanup.get(ChatTurn, old_turn.id)
                if previous is not None:
                    cleanup.delete(previous)
                    cleanup.commit()
            except Exception:
                cleanup.rollback()
                raise
            finally:
                cleanup.close()
        started = await self.start_turn(
            conversation_id,
            client_message_id,
            chat_request_hash(user_text, PATIENT_ID),
        )
        if started.outcome != "new" or started.turn_id is None:
            raise ServiceError(
                "The previous reply could not be regenerated.",
                code="conflict",
                status_code=409,
            )
        trimmed[-1] = {**user_message, "_cp_message_id": started.turn_id}
        try:
            await self.save_messages(conversation_id, trimmed, self._clock.now())
        except Exception:
            await self.fail_turn(started.turn_id)
            raise
        return PreparedRegeneration(
            conversation_id=conversation_id,
            turn_id=started.turn_id,
            client_message_id=client_message_id,
            user_text=user_text,
        )

    async def get_transcript(self, conversation_id: str) -> ConversationTranscript | None:
        session = self._session_factory()
        try:
            conversation = session.get(Conversation, conversation_id)
            if conversation is None:
                return None
            messages = _decode_messages(conversation.messages_json)
            turns = session.scalars(
                select(ChatTurn)
                .where(ChatTurn.conversation_id == conversation_id)
                .order_by(ChatTurn.created_at, ChatTurn.id)
            ).all()
            return ConversationTranscript(
                conversation=_summary(session, conversation),
                turns=_transcript_turns(conversation, messages, list(turns)),
                draft=None,
            )
        finally:
            session.close()

    async def save_messages(
        self, conversation_id: str, messages: list[dict[str, Any]], now: datetime
    ) -> None:
        session = self._session_factory()
        try:
            conversation = session.get(Conversation, conversation_id)
            if conversation is None:
                raise NotFoundError("Conversation not found.")
            conversation.messages_json = json.dumps(
                messages, ensure_ascii=False, separators=(",", ":")
            )
            conversation.updated_at = now
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    async def last_assistant_message_id(self, conversation_id: str) -> str | None:
        messages = await self.load_messages(conversation_id)
        for message in reversed(messages):
            if message.get("role") != "assistant":
                continue
            message_id = message.get("_cp_message_id")
            return message_id if isinstance(message_id, str) and message_id else None
        return None

    async def start_turn(
        self, conversation_id: str, client_message_id: str, request_hash: str
    ) -> TurnStart:
        session = self._session_factory()
        try:
            turn = _find_turn(session, conversation_id, client_message_id)
            if turn is None:
                new_turn = ChatTurn(
                    id=str(uuid.uuid4()),
                    conversation_id=conversation_id,
                    client_message_id=client_message_id,
                    request_hash=request_hash,
                    status=ChatTurnStatus.IN_PROGRESS.value,
                    response_json=None,
                    created_at=self._clock.now(),
                    updated_at=self._clock.now(),
                )
                session.add(new_turn)
                try:
                    session.commit()
                except IntegrityError:
                    session.rollback()
                    turn = _find_turn(session, conversation_id, client_message_id)
                    if turn is None:
                        raise
                    return _classify_turn(turn, request_hash)
                return TurnStart(outcome="new", turn_id=new_turn.id)

            if turn.request_hash != request_hash:
                return TurnStart(outcome="conflict")
            if turn.status == ChatTurnStatus.IN_PROGRESS.value:
                return TurnStart(outcome="in_progress")
            if turn.status == ChatTurnStatus.COMPLETED.value and turn.response_json:
                stored = ChatResponse.model_validate_json(turn.response_json)
                return TurnStart(outcome="replay", turn_id=turn.id, response=stored)
            # A failed turn may safely be retried with the same message ID.
            turn.status = ChatTurnStatus.IN_PROGRESS.value
            turn.response_json = None
            turn.updated_at = self._clock.now()
            session.commit()
            return TurnStart(outcome="new", turn_id=turn.id)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    async def finish_turn(self, turn_id: str, response: ChatResponse) -> None:
        session = self._session_factory()
        try:
            turn = session.get(ChatTurn, turn_id)
            if turn is None:
                raise NotFoundError("Chat turn not found.")
            turn.status = ChatTurnStatus.COMPLETED.value
            turn.response_json = response.model_dump_json()
            turn.updated_at = self._clock.now()
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    async def fail_turn(self, turn_id: str) -> None:
        session = self._session_factory()
        try:
            turn = session.get(ChatTurn, turn_id)
            if turn is None or turn.status != ChatTurnStatus.IN_PROGRESS.value:
                return
            turn.status = ChatTurnStatus.FAILED.value
            turn.response_json = None
            turn.updated_at = self._clock.now()
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    async def pending_turn_id(self, conversation_id: str, client_message_id: str) -> str | None:
        session = self._session_factory()
        try:
            turn = _find_turn(session, conversation_id, client_message_id)
            if turn is None:
                return None
            return turn.id
        finally:
            session.close()


def _decode_messages(raw: str) -> list[dict[str, Any]]:
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(decoded, list):
        return []
    return [item for item in decoded if isinstance(item, dict)]


def _find_turn(session: Session, conversation_id: str, client_message_id: str) -> ChatTurn | None:
    return session.scalar(
        select(ChatTurn).where(
            ChatTurn.conversation_id == conversation_id,
            ChatTurn.client_message_id == client_message_id,
        )
    )


def _classify_turn(turn: ChatTurn, request_hash: str) -> TurnStart:
    if turn.request_hash != request_hash:
        return TurnStart(outcome="conflict")
    if turn.status == ChatTurnStatus.IN_PROGRESS.value:
        return TurnStart(outcome="in_progress")
    if turn.status == ChatTurnStatus.COMPLETED.value and turn.response_json:
        return TurnStart(
            outcome="replay",
            turn_id=turn.id,
            response=ChatResponse.model_validate_json(turn.response_json),
        )
    return TurnStart(outcome="new", turn_id=turn.id)


def _summary(session: Session, conversation: Conversation) -> ConversationSummary:
    messages = _decode_messages(conversation.messages_json)
    active = session.scalar(
        select(ChatTurn)
        .where(
            ChatTurn.conversation_id == conversation.id,
            ChatTurn.status == ChatTurnStatus.IN_PROGRESS.value,
        )
        .order_by(ChatTurn.created_at.desc(), ChatTurn.id.desc())
        .limit(1)
    )
    return ConversationSummary(
        id=conversation.id,
        title=_title(messages),
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        message_count=sum(
            1
            for message in messages
            if message.get("role") in {"user", "assistant"}
            and (message.get("content") or message.get("tool_calls"))
        ),
        turn_count=sum(1 for message in messages if message.get("role") == "user"),
        active_turn_id=active.id if active is not None else None,
    )


_TITLE_LIMIT = 64
_TRIVIAL_TITLES = frozenset(
    {
        "hi",
        "hello",
        "hey",
        "thanks",
        "thank you",
        "ok",
        "okay",
        "yes",
        "no",
        "please",
        "good morning",
        "good afternoon",
        "good evening",
    }
)


def _title(messages: list[dict[str, Any]]) -> str:
    """Build a readable title from the first substantive user message."""
    fallback: str | None = None
    for message in messages:
        if message.get("role") != "user":
            continue
        text = _collapse(str(message.get("content") or ""))
        if not text:
            continue
        if fallback is None:
            fallback = text
        if _is_trivial_title(text):
            continue
        return _truncate_title(text)
    return _truncate_title(fallback) if fallback else "New conversation"


def _is_trivial_title(text: str) -> bool:
    return text.strip().lower().rstrip(".!?,") in _TRIVIAL_TITLES


def _truncate_title(text: str) -> str:
    if len(text) <= _TITLE_LIMIT:
        return text
    cut = text[:_TITLE_LIMIT].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return f"{cut}..." if cut else f"{text[:_TITLE_LIMIT]}..."


def _collapse(value: str) -> str:
    return " ".join(value.split())


def _transcript_turns(
    conversation: Conversation,
    messages: list[dict[str, Any]],
    turns: list[ChatTurn],
) -> list[TranscriptTurn]:
    by_id = {turn.id: turn for turn in turns}
    result: list[TranscriptTurn] = []
    current: TranscriptTurn | None = None
    tool_calls: dict[str, ToolTrace] = {}

    for message in messages:
        role = message.get("role")
        if role == "user":
            turn_id = str(message.get("_cp_message_id") or f"legacy-{len(result) + 1}")
            record = by_id.get(turn_id)
            current = TranscriptTurn(
                turn_id=turn_id,
                client_message_id=record.client_message_id if record else turn_id,
                user=str(message.get("content") or ""),
                status=record.status if record else ChatTurnStatus.COMPLETED.value,
                created_at=record.created_at if record else conversation.created_at,
            )
            result.append(current)
            tool_calls = {}
            continue
        if current is None:
            continue
        if role == "assistant":
            calls = message.get("tool_calls")
            if isinstance(calls, list):
                for call in calls:
                    if not isinstance(call, dict):
                        continue
                    function = call.get("function")
                    function = function if isinstance(function, dict) else {}
                    call_id = str(call.get("id") or "")
                    trace = ToolTrace(
                        id=call_id or None,
                        name=str(function.get("name") or "tool"),
                        args=_parse_object(function.get("arguments")),
                    )
                    current.tools.append(trace)
                    if call_id:
                        tool_calls[call_id] = trace
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                current.assistant = content.strip()
        elif role == "tool":
            call_id = str(message.get("tool_call_id") or "")
            pending = tool_calls.get(call_id)
            if pending is None:
                pending = ToolTrace(
                    id=call_id or None,
                    name=str(message.get("name") or "tool"),
                )
                current.tools.append(pending)
                if call_id:
                    tool_calls[call_id] = pending
            payload = _parse_object(message.get("content"))
            pending.ok = bool(payload.get("ok", True))
            pending.summary = tool_summary(pending.name, payload)
            pending.sources = result_sources(payload)

    for turn in result:
        record = by_id.get(turn.turn_id)
        if record is None:
            continue
        turn.status = record.status
        if not record.response_json:
            continue
        try:
            response = ChatResponse.model_validate_json(record.response_json)
        except ValueError:
            continue
        turn.assistant = response.assistant_message
        turn.sources = response.sources
        turn.booking_draft = response.booking_draft
        turn.events = response.events
        turn.next_step = response.next_step
    return result


def _parse_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return dict(decoded) if isinstance(decoded, dict) else {}
