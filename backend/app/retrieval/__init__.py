"""Retrieval: knowledge documents, local embeddings, hybrid search, reranking."""

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
