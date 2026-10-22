"""Authenticated workbench page, protected assets, and public design tokens."""

from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import APIRouter, Request
from starlette.responses import FileResponse, HTMLResponse, RedirectResponse, Response

from app.api.deps import get_settings, resolve_session
from app.services.errors import NotFoundError, ServiceError
from app.settings import REPO_ROOT, Settings

router = APIRouter()

_CONFIG_ID_PATTERN = re.compile(
    r'<script\b[^>]*\bid\s*=\s*["\']clinicpilot-config["\'][^>]*>.*?</script\s*>',
    re.IGNORECASE | re.DOTALL,
)
_HEAD_PATTERN = re.compile(r"</head\s*>", re.IGNORECASE)

_TRIAGE_FILES: dict[str, Path] = {
    "base.css": REPO_ROOT / "vendor" / "triage" / "core" / "base.css",
    "tokens.css": REPO_ROOT / "vendor" / "triage" / "tokens" / "tokens.css",
    "reset.css": REPO_ROOT / "vendor" / "triage" / "core" / "reset.css",
}


async def _authenticated(request: Request) -> bool:
    return await resolve_session(request) is not None


def _config_script(settings: Settings) -> str:
    payload = json.dumps(
        {"prefix": settings.demo_path_prefix, "appName": "ClinicPilot"},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    payload = (
        payload.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    return f'<script id="clinicpilot-config" type="application/json">{payload}</script>'


def _inject_config(document: str, settings: Settings) -> str:
    document = _CONFIG_ID_PATTERN.sub("", document)
    script = _config_script(settings)
    if _HEAD_PATTERN.search(document):
        return _HEAD_PATTERN.sub(lambda _match: script + "</head>", document, count=1)
    return script + document


@router.get("/")
async def index(request: Request) -> Response:
    if not await _authenticated(request):
        return RedirectResponse("./login", status_code=303)
    settings = get_settings(request)
    index_path = settings.frontend_dist_dir / "index.html"
    try:
        document = index_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return HTMLResponse(
            "<!doctype html><html><head><title>ClinicPilot</title></head>"
            "<body><h1>Frontend build missing</h1>"
            "<p>Run <code>npm run build</code> in the frontend package and restart "
            "the application.</p></body></html>",
            status_code=503,
        )
    return HTMLResponse(_inject_config(document, settings))


@router.get("/assets/{path:path}")
async def asset(request: Request, path: str) -> Response:
    if not await _authenticated(request):
        raise ServiceError("Authentication required.", code="unauthorized", status_code=401)
    settings = get_settings(request)
    base = (settings.frontend_dist_dir / "assets").resolve()
    try:
        target = (base / path).resolve()
    except (OSError, ValueError) as exc:
        raise NotFoundError("Asset not found.") from exc
    if not target.is_relative_to(base) or not target.is_file():
        raise NotFoundError("Asset not found.")
    return FileResponse(target)


@router.get("/public/triage/{name}")
async def triage_asset(name: str) -> Response:
    path = _TRIAGE_FILES.get(name)
    if path is None or not path.is_file():
        raise NotFoundError("Stylesheet not found.")
    return FileResponse(path, media_type="text/css")


@router.get("/public/fonts/{name}")
async def triage_font(name: str) -> Response:
    base = (REPO_ROOT / "vendor" / "triage" / "fonts").resolve()
    try:
        target = (base / name).resolve()
    except (OSError, ValueError) as exc:
        raise NotFoundError("Font not found.") from exc
    if not target.is_relative_to(base) or not target.is_file():
        raise NotFoundError("Font not found.")
    media_type = "font/woff2" if target.suffix == ".woff2" else "font/woff"
    return FileResponse(target, media_type=media_type)
