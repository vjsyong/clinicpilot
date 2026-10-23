from __future__ import annotations

import inspect
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from starlette.responses import JSONResponse, RedirectResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.clock import SystemClock
from app.services.provider_settings import ProviderSettings
from app.settings import Settings, get_settings

logger = logging.getLogger("clinicpilot")


def _request_id() -> str:
    return str(uuid.uuid4())


_INTERNAL_HEALTH_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _not_found_response() -> JSONResponse:
    return JSONResponse(
        {
            "error": {
                "code": "not_found",
                "message": "Not found.",
                "retryable": False,
            },
            "request_id": _request_id(),
        },
        status_code=404,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


def _host_name(scope: Scope) -> str:
    headers = dict(scope.get("headers", []))
    raw = headers.get(b"host", b"").decode("latin-1").strip().lower()
    if not raw:
        return ""
    if raw.startswith("["):
        end = raw.find("]")
        return raw[1:end] if end >= 0 else raw
    return raw.split(":", 1)[0]


def _internal_health_request(scope: Scope) -> bool:
    """Health routes are for the container/host network, never the tunnel."""
    headers = dict(scope.get("headers", []))
    if b"cf-ray" in headers or b"cf-connecting-ip" in headers:
        return False
    return _host_name(scope) in _INTERNAL_HEALTH_HOSTS


class PrefixApp:
    """Serve the whole application beneath one runtime-configured prefix."""

    def __init__(self, app: ASGIApp, prefix: str) -> None:
        self.app = app
        self.prefix = prefix
        self.bare_prefix = prefix.rstrip("/")
        self.internal_paths = ("/healthz", "/readyz")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "/")
        if path in self.internal_paths:
            if _internal_health_request(scope):
                await self.app(scope, receive, send)
            else:
                not_found = _not_found_response()
                await not_found(scope, receive, send)
            return
        if path == self.bare_prefix:
            query = scope.get("query_string", b"").decode("latin-1")
            url = self.prefix + (("?" + query) if query else "")
            redirect = RedirectResponse(url=url, status_code=308)
            await redirect(scope, receive, send)
            return
        if not path.startswith(self.prefix):
            not_found = _not_found_response()
            await not_found(scope, receive, send)
            return

        inner = dict(scope)
        inner["path"] = "/" + path[len(self.prefix) :].lstrip("/")
        inner["root_path"] = self.bare_prefix
        await self.app(inner, receive, send)


def create_app(
    settings: Settings | None = None,
    *,
    controller_factory: Any = None,
    index_factory: Any = None,
) -> ASGIApp:
    settings = settings or get_settings()
    settings.validate_runtime()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        from app.db.session import create_session_factory

        engine, session_factory = create_session_factory(settings)
        app.state.engine = engine
        app.state.session_factory = session_factory
        app.state.clock = SystemClock()

        from app.services.recovery import recover_interrupted_turns

        recovered = recover_interrupted_turns(session_factory, app.state.clock)
        if recovered:
            logger.info("Recovered %s interrupted chat turn(s)", recovered)

        build_index = index_factory
        if build_index is None:
            from app.retrieval.index import build_knowledge_index as build_index
        build_controller_fn = controller_factory
        if build_controller_fn is None:
            from app.agent.controller import build_controller as build_controller_fn

        index = build_index(settings, session_factory)
        await index.prewarm()
        app.state.knowledge_index = index
        # The optional DeepSeek key is deliberately process-local: it is never
        # written to SQLite, the environment, or logs.
        app.state.provider_settings = ProviderSettings()
        controller_kwargs: dict[str, Any] = {}
        try:
            parameters = inspect.signature(build_controller_fn).parameters
            if "index" in parameters:
                controller_kwargs["index"] = index
            if "provider_settings" in parameters:
                controller_kwargs["provider_settings"] = app.state.provider_settings
        except (TypeError, ValueError):
            pass
        app.state.controller = build_controller_fn(
            settings, session_factory, app.state.clock, **controller_kwargs
        )

        logger.info("ClinicPilot ready at prefix %s", settings.demo_path_prefix)
        try:
            yield
        finally:
            runs = getattr(app.state, "chat_runs", None)
            if runs is not None:
                await runs.shutdown()
            controller = getattr(app.state, "controller", None)
            model_client = getattr(controller, "_model_client", None)
            aclose = getattr(model_client, "aclose", None)
            if aclose is not None:
                await aclose()
            engine.dispose()

    app = FastAPI(
        title="ClinicPilot",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings

    from app.api import router as api_router
    from app.api.errors import install_error_handlers
    from app.auth.middleware import SecurityHeadersMiddleware
    from app.auth.routes import router as auth_router

    install_error_handlers(app)
    app.add_middleware(SecurityHeadersMiddleware, settings=settings)
    app.include_router(auth_router)
    app.include_router(api_router)
    return PrefixApp(app, settings.demo_path_prefix)


app = create_app()


def run() -> Any:
    return app
