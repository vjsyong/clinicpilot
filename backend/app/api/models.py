"""Model catalogue and the in-memory DeepSeek backup credential."""

from __future__ import annotations

from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.api.deps import get_settings, require_api_session
from app.db.models import DemoSession
from app.services.errors import ServiceError
from app.services.provider_settings import ProviderSettings

router = APIRouter()

_LOCAL = "local"
_DEEPSEEK = "deepseek"
_VERIFY_TIMEOUT_SECONDS = 5.0


class DeepSeekKeyRequest(BaseModel):
    api_key: str = Field(min_length=1, max_length=512)


def _providers(request: Request) -> ProviderSettings:
    providers = getattr(request.app.state, "provider_settings", None)
    if not isinstance(providers, ProviderSettings):
        providers = ProviderSettings()
        request.app.state.provider_settings = providers
    return providers


def _catalogue(request: Request) -> dict[str, object]:
    settings = get_settings(request)
    providers = _providers(request)
    return {
        "default": settings.default_model,
        "models": [
            {
                "id": _LOCAL,
                "label": "Gemma 26B-A4B (local)",
                "model": settings.local_model_id,
                "available": True,
                "hint": None,
            },
            {
                "id": _DEEPSEEK,
                "label": "DeepSeek (backup)",
                "model": settings.deepseek_model,
                "available": providers.configured(),
                "hint": providers.masked_hint(),
            },
        ],
    }


@router.get("/api/models")
async def list_models(
    request: Request,
    demo_session: Annotated[DemoSession, Depends(require_api_session)],
):
    return _catalogue(request)


@router.put("/api/models/deepseek-key")
async def save_deepseek_key(
    payload: DeepSeekKeyRequest,
    request: Request,
    demo_session: Annotated[DemoSession, Depends(require_api_session)],
):
    providers = _providers(request)
    try:
        providers.set_key(payload.api_key)
    except ValueError as exc:
        raise ServiceError(str(exc), code="invalid_request", status_code=400) from exc
    verified = await _verify_deepseek(request, providers.get_key())
    response = _catalogue(request)
    response["verified"] = verified
    return response


@router.delete("/api/models/deepseek-key")
async def clear_deepseek_key(
    request: Request,
    demo_session: Annotated[DemoSession, Depends(require_api_session)],
):
    _providers(request).clear()
    return _catalogue(request)


async def _verify_deepseek(request: Request, api_key: str) -> bool:
    settings = get_settings(request)
    url = settings.deepseek_base_url.rstrip("/") + "/models"
    try:
        async with httpx.AsyncClient(timeout=_VERIFY_TIMEOUT_SECONDS) as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {api_key}"},
            )
    except httpx.HTTPError:
        return False
    return response.status_code == 200
