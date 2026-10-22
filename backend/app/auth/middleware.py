"""Security headers, request IDs, and CSRF checks for cookie-authenticated writes."""

from __future__ import annotations

import uuid
from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from app.auth.sessions import SESSION_COOKIE
from app.settings import Settings

_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self'; "
    "connect-src 'self'; "
    "font-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)

SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": _CSP,
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, *, settings: Settings) -> None:
        super().__init__(app)
        self._settings = settings

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id

        response: Response
        if self._csrf_violation(request):
            response = JSONResponse(
                {
                    "error": {
                        "code": "forbidden",
                        "message": "Cross-origin request rejected.",
                        "retryable": False,
                    },
                    "request_id": request_id,
                },
                status_code=403,
            )
            _apply_headers(response)
            return response

        response = await call_next(request)
        _apply_headers(response)
        return response

    @staticmethod
    def _csrf_violation(request: Request) -> bool:
        if request.method not in _UNSAFE_METHODS:
            return False
        if request.cookies.get(SESSION_COOKIE) is None:
            return False
        if request.headers.get("x-internal-tool-key"):
            return False
        origin = request.headers.get("origin")
        if not origin:
            return True
        parsed = urlsplit(origin)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return True
        host = request.headers.get("host", "")
        forwarded = request.headers.get("x-forwarded-proto")
        scheme = forwarded.split(",")[0].strip() if forwarded else request.url.scheme
        return parsed.netloc != host or parsed.scheme != scheme


def _apply_headers(response: Response) -> None:
    for name, value in SECURITY_HEADERS.items():
        response.headers[name] = value
