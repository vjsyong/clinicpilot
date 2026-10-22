"""Retrieval: knowledge documents, local embeddings, cosine search, patient context."""

from app.retrieval.documents import documents_from_csv, documents_from_db
from app.retrieval.embeddings import (
    Embedder,
    LocalEmbedder,
    embed_documents,
    embed_query,
    embed_texts,
)
from app.retrieval.index import build_knowledge_index
from app.retrieval.patient_context import load_patient_context

__all__ = [
    "Embedder",
    "LocalEmbedder",
    "build_knowledge_index",
    "documents_from_csv",
    "documents_from_db",
    "embed_documents",
    "embed_query",
    "embed_texts",
    "load_patient_context",
]
