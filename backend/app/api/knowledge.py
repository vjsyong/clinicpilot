"""Authenticated knowledge-source inspection for the assistant UI."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.encoders import jsonable_encoder

from app.api.deps import get_settings, require_api_session
from app.db.models import DemoSession
from app.services.errors import NotFoundError, ServiceError

router = APIRouter()


def _index(request: Request):
    index = getattr(request.app.state, "knowledge_index", None)
    if index is None:
        raise ServiceError(
            "The knowledge index is not ready.",
            code="not_ready",
            status_code=503,
            retryable=True,
        )
    return index


@router.get("/api/knowledge/status")
async def knowledge_status(
    request: Request,
    _session: Annotated[DemoSession, Depends(require_api_session)],
):
    settings = get_settings(request)
    index = _index(request)
    return {
        "ready": bool(index.ready()),
        "records": len(index.documents),
        "model": settings.embedding_model,
        "revision": settings.embedding_revision,
        "reranker": settings.reranker_model,
        "reranker_revision": settings.reranker_revision,
        "reranker_enabled": settings.reranker_enabled,
    }


@router.get("/api/knowledge/{source_file}/{record_id}")
async def knowledge_record(
    source_file: str,
    record_id: str,
    request: Request,
    _session: Annotated[DemoSession, Depends(require_api_session)],
):
    document = _index(request).lookup(source_file, record_id)
    if document is None:
        raise NotFoundError("Knowledge record not found.")
    return jsonable_encoder(
        {
            "document_id": document.document_id,
            "source_file": document.source_file,
            "record_id": document.record_id,
            "citation": f"[doc:{document.record_id}]",
            "text": document.text,
            "metadata": document.metadata,
        }
    )
