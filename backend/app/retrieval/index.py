"""In-memory cosine index over the eleven knowledge documents."""

from __future__ import annotations

import asyncio
import re
import threading

import numpy as np
from numpy.typing import NDArray

from app.contracts import KnowledgeIndex, RetrievedDocument
from app.retrieval.documents import (
    SessionFactory,
    documents_from_csv,
    documents_from_db,
)
from app.retrieval.embeddings import (
    Embedder,
    LocalEmbedder,
    embed_documents,
)
from app.settings import Settings

_FILTER_KEYS = frozenset({"source_file", "category", "specialty", "clinic_id"})


def _normalize_text(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", " ", value.casefold())
    return " ".join(cleaned.split())


class _KnowledgeIndex:
    def __init__(
        self,
        settings: Settings,
        session_factory: SessionFactory | None,
        embedder: Embedder,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._embedder = embedder
        self._documents: list[RetrievedDocument] = []
        self._vectors: NDArray[np.float32] | None = None
        self._ready = False
        self._lock = threading.Lock()

    def ready(self) -> bool:
        return self._ready

    @property
    def documents(self) -> list[RetrievedDocument]:
        with self._lock:
            return list(self._documents)

    async def prewarm(self) -> None:
        if self._ready:
            return
        await asyncio.to_thread(self._prewarm)

    def _prewarm(self) -> None:
        with self._lock:
            if self._ready:
                return
            if self._session_factory is None:
                documents = documents_from_csv(self._settings)
            else:
                documents = documents_from_db(self._session_factory)
            vectors = embed_documents(documents, self._embedder, self._settings)
            if vectors.shape[0] != len(documents):
                raise RuntimeError("Embedding count does not match the document count.")
            self._documents = documents
            self._vectors = vectors
            self._ready = True

    def _eligible_indices(self, filters: dict[str, str] | None) -> list[int]:
        if not filters:
            return list(range(len(self._documents)))
        unknown = set(filters).difference(_FILTER_KEYS)
        if unknown:
            names = ", ".join(sorted(unknown))
            raise ValueError(f"Unsupported retrieval filter(s): {names}.")

        wanted: dict[str, str] = {}
        for key, value in filters.items():
            normalized = _normalize_text(str(value))
            if normalized:
                wanted[key] = normalized

        eligible: list[int] = []
        for index, document in enumerate(self._documents):
            if not self._matches(document, wanted):
                continue
            eligible.append(index)
        return eligible

    @staticmethod
    def _matches(document: RetrievedDocument, wanted: dict[str, str]) -> bool:
        for key, value in wanted.items():
            actual = (
                document.source_file
                if key == "source_file"
                else str(document.metadata.get(key, ""))
            )
            if _normalize_text(actual) != value:
                return False
        return True

    @staticmethod
    def _is_exact(query: str, document: RetrievedDocument) -> bool:
        normalized_query = _normalize_text(query)
        if not normalized_query:
            return False
        name = str(document.metadata.get("name", ""))
        aliases = {
            _normalize_text(name),
            _normalize_text(document.record_id),
            _normalize_text(document.document_id),
        }
        normalized_name = _normalize_text(name)
        if normalized_name.startswith("dr "):
            aliases.add(normalized_name[3:])
        aliases.discard("")
        if normalized_query in aliases:
            return True
        if len(normalized_query) < 5:
            return False
        return any(
            len(alias) > len(normalized_query) and alias.startswith(normalized_query)
            for alias in aliases
        )

    def _query_vector(self, query: str) -> NDArray[np.float32]:
        vector = np.asarray(self._embedder.embed_query(query), dtype=np.float32)
        if vector.ndim != 1:
            vector = vector.reshape(-1)
        norm = float(np.linalg.norm(vector))
        if norm:
            vector = vector / norm
        return vector.astype(np.float32, copy=False)

    def search(
        self,
        query: str,
        limit: int = 5,
        filters: dict[str, str] | None = None,
    ) -> list[RetrievedDocument]:
        if limit <= 0:
            return []
        with self._lock:
            if not self._ready or self._vectors is None:
                raise RuntimeError(
                    "Knowledge index is not ready; prewarm() must complete before search()."
                )
            documents = list(self._documents)
            vectors = self._vectors

        eligible = self._eligible_indices(filters)
        if not eligible:
            return []

        exact = [index for index in eligible if self._is_exact(query, documents[index])]
        exact_set = set(exact)

        query_vector = self._query_vector(query)
        if query_vector.shape[0] != vectors.shape[1]:
            raise RuntimeError("Query embedding dimension does not match the document embeddings.")
        scores = np.asarray(vectors[eligible] @ query_vector, dtype=np.float32)
        order = np.argsort(-scores, kind="stable")

        ranked = [*exact]
        ranked.extend(
            eligible[int(position)]
            for position in order
            if eligible[int(position)] not in exact_set
        )
        return [documents[index] for index in ranked[:limit]]


def build_knowledge_index(
    settings: Settings,
    session_factory: SessionFactory | None,
    embedder: Embedder | None = None,
) -> KnowledgeIndex:
    """Build the retrieval index.

    The database is the production source; CSV documents are used only when no
    session factory is supplied (tests and offline smoke checks).
    """
    backend = embedder or LocalEmbedder(settings.embedding_model, settings.embedding_revision)
    return _KnowledgeIndex(settings, session_factory, backend)
