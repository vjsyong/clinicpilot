"""Login, logout, and the server-rendered sign-in page."""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from urllib.parse import unquote, urlsplit

from fastapi import APIRouter, Form, Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from app.auth.password import effective_password_hash, verify_password
from app.auth.sessions import SESSION_COOKIE, SessionService
from app.settings import Settings

router = APIRouter()

_TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "templates" / "login.html"
_FAILURE_LIMIT = 5
_FAILURE_WINDOW = timedelta(minutes=5)


@dataclass
class LoginThrottle:
    failures: dict[str, list[datetime]] = field(default_factory=dict)

    def is_limited(self, client: str, now: datetime) -> bool:
        recent = self._recent(client, now)
        return len(recent) >= _FAILURE_LIMIT

    def record_failure(self, client: str, now: datetime) -> None:
        recent = self._recent(client, now)
        recent.append(now)
        self.failures[client] = recent

    def reset(self, client: str) -> None:
        self.failures.pop(client, None)

    def _recent(self, client: str, now: datetime) -> list[datetime]:
        cutoff = now - _FAILURE_WINDOW
        recent = [stamp for stamp in self.failures.get(client, []) if stamp > cutoff]
        self.failures[client] = recent
        return recent


@lru_cache(maxsize=1)
def _template() -> str:
    return _TEMPLATE_PATH.read_text(encoding="utf-8")


def _render_login(error: str | None, next_value: str, status_code: int) -> HTMLResponse:
    error_block = ""
    if error:
        error_block = (
            f'<p class="field-err" role="alert" data-testid="login-error">{html.escape(error)}</p>'
        )
    next_field = ""
    if next_value:
        next_field = f'<input type="hidden" name="next" value="{html.escape(next_value)}">'
    body = _template().replace("{{NEXT_FIELD}}", next_field).replace("{{ERROR_BLOCK}}", error_block)
    return HTMLResponse(body, status_code=status_code)


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def _session_service(request: Request) -> SessionService:
    return SessionService(
        request.app.state.session_factory,
        request.app.state.clock,
        _settings(request),
    )


def _client_host(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


def _throttle(request: Request) -> LoginThrottle:
    existing = getattr(request.app.state, "login_throttle", None)
    if isinstance(existing, LoginThrottle):
        return existing
    throttle = LoginThrottle()
    request.app.state.login_throttle = throttle
    return throttle


def _safe_next(raw: str, settings: Settings) -> str:
    value = unquote(raw.strip())
    if not value or "\\" in value or "\x00" in value:
        return "./"
    if value.startswith("//"):
        return "./"
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc:
        return "./"
    bare_prefix = settings.demo_path_prefix.rstrip("/")
    if value.startswith("/"):
        if value == bare_prefix or value.startswith(settings.demo_path_prefix):
            return value
        return "./"
    segments = value.split("/")
    if ".." in segments:
        return "./"
    if value.startswith("./"):
        return value
    return "./"


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> Response:
    existing = await _session_service(request).resolve(request.cookies.get(SESSION_COOKIE))
    if existing is not None:
        return RedirectResponse("./", status_code=303)
    return _render_login(None, "", 200)


@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    password: str = Form(""),
    next: str = Form(""),
) -> Response:
    settings = _settings(request)
    now = request.app.state.clock.now()
    client = _client_host(request)
    throttle = _throttle(request)

    if throttle.is_limited(client, now):
        response: Response = _render_login(
            "Too many failed attempts. Please wait a few minutes and try again.",
            next,
            429,
        )
        response.headers["Retry-After"] = "300"
        return response

    if not verify_password(password, effective_password_hash(settings)):
        throttle.record_failure(client, now)
        return _render_login("Incorrect password.", next, 401)

    throttle.reset(client)
    token, _ = await _session_service(request).create_session()
    response = RedirectResponse(_safe_next(next, settings), status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.secure_cookies,
        path=settings.cookie_path,
    )
    return response


@router.post("/logout")
async def logout(request: Request) -> Response:
    token = request.cookies.get(SESSION_COOKIE)
    await _session_service(request).revoke(token)
    response = RedirectResponse("./login", status_code=303)
    response.delete_cookie(
        SESSION_COOKIE,
        path=_settings(request).cookie_path,
        secure=_settings(request).secure_cookies,
        httponly=True,
        samesite="lax",
    )
    return response
