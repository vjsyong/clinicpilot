"""Consistent JSON error responses for every API failure."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

from app.auth.middleware import SECURITY_HEADERS
from app.contracts import ProviderError
from app.services.errors import ServiceError

logger = logging.getLogger("clinicpilot.errors")

_STATUS_CODES: dict[int, tuple[str, str, bool]] = {
    400: ("invalid_request", "The request was invalid.", False),
    401: ("unauthorized", "Authentication required.", False),
    403: ("forbidden", "Forbidden.", False),
    404: ("not_found", "Not found.", False),
    409: ("conflict", "The request conflicts with the current state.", False),
    422: ("invalid_request", "The request was invalid.", False),
    429: ("rate_limited", "Too many requests.", True),
    502: ("provider_error", "The generation provider failed. Please retry.", True),
    503: ("internal_error", "The service is not ready.", True),
}


def _request_id(request: Request) -> str:
    value = getattr(request.state, "request_id", None)
    if isinstance(value, str) and value:
        return value
    return str(uuid.uuid4())


def error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    retryable: bool,
) -> JSONResponse:
    response = JSONResponse(
        {
            "error": {"code": code, "message": message, "retryable": retryable},
            "request_id": _request_id(request),
        },
        status_code=status_code,
    )
    for name, value in SECURITY_HEADERS.items():
        response.headers[name] = value
    return response


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ServiceError)
    async def _service_error(request: Request, exc: ServiceError) -> JSONResponse:
        return error_response(
            request,
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            retryable=exc.retryable,
        )

    @app.exception_handler(ProviderError)
    async def _provider_error(request: Request, exc: ProviderError) -> JSONResponse:
        logger.warning("Provider failure: %s", exc)
        return error_response(
            request,
            status_code=502,
            code="provider_error",
            message="The generation provider failed. Please retry.",
            retryable=True,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(
            request,
            status_code=422,
            code="invalid_request",
            message="The request was invalid.",
            retryable=False,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        status = exc.status_code
        code, message, retryable = _STATUS_CODES.get(
            status,
            ("internal_error", "The server could not complete the request.", False)
            if status >= 500
            else ("invalid_request", "The request was invalid.", False),
        )
        detail: Any = exc.detail
        if isinstance(detail, dict):
            code = str(detail.get("code", code))
            message = str(detail.get("message", message))
            retryable = bool(detail.get("retryable", retryable))
        return error_response(
            request,
            status_code=status,
            code=code,
            message=message,
            retryable=retryable,
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return error_response(
            request,
            status_code=500,
            code="internal_error",
            message="The server could not complete the request.",
            retryable=False,
        )
