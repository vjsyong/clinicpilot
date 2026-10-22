"""Durable, session-scoped agent trace events."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.contracts import Clock
from app.db.models import AgentEvent


@dataclass(frozen=True)
class AuditEvent:
    id: str
    demo_session_id: int
    conversation_id: str | None
    turn_id: str | None
    event_type: str
    name: str
    status: str
    payload: dict[str, Any]
    created_at: datetime


class AuditService:
    def __init__(self, session_factory: sessionmaker[Session], clock: Clock) -> None:
        self._session_factory = session_factory
        self._clock = clock

    async def record(
        self,
        *,
        demo_session_id: int,
        conversation_id: str | None,
        turn_id: str | None,
        event_type: str,
        name: str,
        status: str,
        payload: dict[str, Any],
    ) -> None:
        session = self._session_factory()
        try:
            session.add(
                AgentEvent(
                    id=str(uuid.uuid4()),
                    demo_session_id=demo_session_id,
                    conversation_id=conversation_id,
                    turn_id=turn_id,
                    event_type=event_type,
                    name=name,
                    status=status,
                    payload_json=json.dumps(
                        payload, ensure_ascii=False, default=str, separators=(",", ":")
                    ),
                    created_at=self._clock.now(),
                )
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    async def list_events(self, demo_session_id: int, *, limit: int = 300) -> list[AuditEvent]:
        session = self._session_factory()
        try:
            rows = session.scalars(
                select(AgentEvent)
                .where(AgentEvent.demo_session_id == demo_session_id)
                .order_by(AgentEvent.created_at.desc(), AgentEvent.id.desc())
                .limit(max(1, min(limit, 1000)))
            ).all()
            return [_event(row) for row in rows]
        finally:
            session.close()


def _event(row: AgentEvent) -> AuditEvent:
    try:
        payload = json.loads(row.payload_json)
    except ValueError:
        payload = {}
    return AuditEvent(
        id=row.id,
        demo_session_id=row.demo_session_id,
        conversation_id=row.conversation_id,
        turn_id=row.turn_id,
        event_type=row.event_type,
        name=row.name,
        status=row.status,
        payload=payload if isinstance(payload, dict) else {},
        created_at=row.created_at,
    )
