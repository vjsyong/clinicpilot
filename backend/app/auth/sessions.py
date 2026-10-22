"""Opaque browser sessions: only the SHA-256 token hash is persisted."""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.contracts import Clock
from app.db.models import DemoSession
from app.settings import Settings

SESSION_COOKIE = "clinicpilot_session"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class SessionService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        clock: Clock,
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._settings = settings

    async def create_session(self) -> tuple[str, DemoSession]:
        token = secrets.token_urlsafe(32)
        now = self._clock.now()
        session = self._session_factory()
        try:
            record = DemoSession(
                token_hash=hash_token(token),
                created_at=now,
                expires_at=now + timedelta(hours=self._settings.session_ttl_hours),
                revoked_at=None,
            )
            session.add(record)
            session.commit()
            return token, record
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    async def resolve(self, token: str | None) -> DemoSession | None:
        if not token:
            return None
        now = self._clock.now()
        session = self._session_factory()
        try:
            record = session.scalar(
                select(DemoSession).where(DemoSession.token_hash == hash_token(token))
            )
            if record is None:
                return None
            if record.revoked_at is not None or now >= record.expires_at:
                return None
            return record
        finally:
            session.close()

    async def revoke(self, token: str | None) -> bool:
        if not token:
            return False
        session = self._session_factory()
        try:
            record = session.scalar(
                select(DemoSession).where(DemoSession.token_hash == hash_token(token))
            )
            if record is None:
                return False
            if record.revoked_at is None:
                record.revoked_at = self._clock.now()
                session.commit()
            return True
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
