"""Retrieval exports, loaded lazily so embeddings can be prewarmed alone."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.retrieval.documents import documents_from_csv, documents_from_db
    from app.retrieval.embeddings import (
        Embedder,
        FastEmbedder,
        embed_documents,
        embed_query,
        embed_texts,
    )
    from app.retrieval.index import build_knowledge_index
    from app.retrieval.patient_context import load_patient_context
    from app.retrieval.reranker import FastEmbedReranker, Reranker

__all__ = [
    "Embedder",
    "FastEmbedReranker",
    "FastEmbedder",
    "Reranker",
    "build_knowledge_index",
    "documents_from_csv",
    "documents_from_db",
    "embed_documents",
    "embed_query",
    "embed_texts",
    "load_patient_context",
]

_EXPORTS: dict[str, tuple[str, str]] = {
    "Embedder": ("app.retrieval.embeddings", "Embedder"),
    "FastEmbedReranker": ("app.retrieval.reranker", "FastEmbedReranker"),
    "FastEmbedder": ("app.retrieval.embeddings", "FastEmbedder"),
    "Reranker": ("app.retrieval.reranker", "Reranker"),
    "build_knowledge_index": ("app.retrieval.index", "build_knowledge_index"),
    "documents_from_csv": ("app.retrieval.documents", "documents_from_csv"),
    "documents_from_db": ("app.retrieval.documents", "documents_from_db"),
    "embed_documents": ("app.retrieval.embeddings", "embed_documents"),
    "embed_query": ("app.retrieval.embeddings", "embed_query"),
    "embed_texts": ("app.retrieval.embeddings", "embed_texts"),
    "load_patient_context": ("app.retrieval.patient_context", "load_patient_context"),
}


def __getattr__(name: str) -> Any:
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError:
        raise AttributeError(name) from None
    value = getattr(importlib.import_module(module_name), attribute)
    globals()[name] = value
    return value
