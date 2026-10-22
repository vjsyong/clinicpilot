"""Internal liveness and readiness checks. Never contacts DeepSeek."""

from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import text
from starlette.responses import JSONResponse, Response

router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request) -> Response:
    factory = getattr(request.app.state, "session_factory", None)
    if factory is None:
        return JSONResponse({"status": "unavailable"}, status_code=503)
    session = factory()
    try:
        session.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse({"status": "unavailable"}, status_code=503)
    finally:
        session.close()

    index = getattr(request.app.state, "knowledge_index", None)
    try:
        ready = index is not None and bool(index.ready())
    except Exception:
        ready = False
    if not ready:
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return JSONResponse({"status": "ready"})
