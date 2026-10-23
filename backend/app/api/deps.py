"""Shared request dependencies: sessions, internal credentials, patient scope."""

from __future__ import annotations

import hmac
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Header, Request
from sqlalchemy.orm import Session, sessionmaker

from app.auth.sessions import SESSION_COOKIE, SessionService
from app.contracts import PATIENT_ID, Clock, ModelProvider
from app.db.models import DemoSession
from app.services.errors import ServiceError
from app.settings import Settings


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_clock(request: Request) -> Clock:
    clock: Clock = request.app.state.clock
    return clock


def get_session_factory(request: Request) -> sessionmaker[Session]:
    factory: sessionmaker[Session] = request.app.state.session_factory
    return factory


async def get_db(request: Request) -> AsyncIterator[Session]:
    session = get_session_factory(request)()
    try:
        yield session
    finally:
        session.close()


async def resolve_session(request: Request) -> DemoSession | None:
    service = SessionService(
        get_session_factory(request), get_clock(request), get_settings(request)
    )
    return await service.resolve(request.cookies.get(SESSION_COOKIE))


async def require_api_session(request: Request) -> DemoSession:
    session = await resolve_session(request)
    if session is None:
        raise ServiceError("Authentication required.", code="unauthorized", status_code=401)
    return session


def has_internal_key(
    request: Request,
    x_internal_tool_key: Annotated[str | None, Header()] = None,
) -> bool:
    provided = x_internal_tool_key or request.headers.get("x-internal-tool-key")
    if not provided:
        return False
    expected = get_settings(request).internal_tool_key
    return hmac.compare_digest(provided, expected)


def require_internal_key(
    request: Request,
    x_internal_tool_key: Annotated[str | None, Header()] = None,
) -> None:
    if not has_internal_key(request, x_internal_tool_key):
        raise ServiceError(
            "A valid internal tool key is required.",
            code="unauthorized",
            status_code=401,
        )


def require_patient(patient_id: str | None) -> str:
    if patient_id is not None and patient_id != PATIENT_ID:
        raise ServiceError(
            "The shared demo only exposes patient P001.",
            code="forbidden",
            status_code=403,
        )
    return PATIENT_ID


def require_model_available(request: Request, model: ModelProvider) -> ModelProvider:
    if model == "local":
        return model
    providers = getattr(request.app.state, "provider_settings", None)
    if providers is None or not providers.configured():
        raise ServiceError(
            "DeepSeek is not configured. Add an API key or use the local model.",
            code="provider_not_configured",
            status_code=400,
        )
    return model
