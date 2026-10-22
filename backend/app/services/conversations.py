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

from app.contracts import PATIENT_ID, ChatResponse, ChatTurnStatus, Clock
from app.db.models import BookingDraft, ChatTurn, Conversation
from app.services.errors import NotFoundError

TurnOutcome = Literal["new", "replay", "conflict", "in_progress"]


@dataclass(frozen=True)
class ConversationRecord:
    id: str
    demo_session_id: int
    patient_id: str
    messages: list[dict[str, Any]]


@dataclass(frozen=True)
class TurnStart:
    outcome: TurnOutcome
    turn_id: str | None = None
    response: ChatResponse | None = None


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
            if turn is None:
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
