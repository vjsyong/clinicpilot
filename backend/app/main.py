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
from app.settings import Settings, get_settings

logger = logging.getLogger("clinicpilot")


def _request_id() -> str:
    return str(uuid.uuid4())


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
            await self.app(scope, receive, send)
            return
        if path == self.bare_prefix:
            query = scope.get("query_string", b"").decode("latin-1")
            url = self.prefix + (("?" + query) if query else "")
            redirect = RedirectResponse(url=url, status_code=308)
            await redirect(scope, receive, send)
            return
        if not path.startswith(self.prefix):
            not_found = JSONResponse(
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

        build_index = index_factory
        if build_index is None:
            from app.retrieval.index import build_knowledge_index as build_index
        build_controller_fn = controller_factory
        if build_controller_fn is None:
            from app.agent.controller import build_controller as build_controller_fn

        index = build_index(settings, session_factory)
        await index.prewarm()
        app.state.knowledge_index = index
        controller_kwargs: dict[str, Any] = {}
        try:
            if "index" in inspect.signature(build_controller_fn).parameters:
                controller_kwargs["index"] = index
        except (TypeError, ValueError):
            pass
        app.state.controller = build_controller_fn(
            settings, session_factory, app.state.clock, **controller_kwargs
        )

        logger.info("ClinicPilot ready at prefix %s", settings.demo_path_prefix)
        try:
            yield
        finally:
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
