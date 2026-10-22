"""Hybrid in-memory retrieval over the eleven knowledge documents.

Dense cosine similarity remains the semantic channel. A field-weighted BM25
channel and an exact ID/name channel are fused with reciprocal rank fusion, so
exact records, paraphrases, and rare terms all have a path into the top results.
No vector database or external retrieval service is required.
"""

from __future__ import annotations

import asyncio
import math
import re
import threading
from collections import Counter, defaultdict

import numpy as np
from numpy.typing import NDArray

from app.contracts import Evidence, KnowledgeIndex, RetrievedDocument
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
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "i",
        "in",
        "is",
        "it",
        "me",
        "my",
        "of",
        "on",
        "or",
        "that",
        "the",
        "to",
        "was",
        "we",
        "what",
        "when",
        "where",
        "which",
        "who",
        "with",
        "you",
    }
)
_FIELD_WEIGHTS = {
    "name": 4.0,
    "specialty": 2.0,
    "category": 2.0,
    "clinic_name": 1.5,
}
_BM25_K1 = 1.5
_BM25_B = 0.75
_RRF_K = 60
_EXACT_BOOST = 0.5


def _normalize_text(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", " ", value.casefold())
    return " ".join(cleaned.split())


def _tokenize(value: str) -> list[str]:
    return [
        token
        for token in _TOKEN_RE.findall(value.casefold())
        if len(token) >= 2 and token not in _STOPWORDS
    ]


def _weighted_terms(document: RetrievedDocument) -> dict[str, float]:
    terms: dict[str, float] = {}
    for token in _tokenize(document.text):
        terms[token] = terms.get(token, 0.0) + 1.0
    for field, weight in _FIELD_WEIGHTS.items():
        value = str(document.metadata.get(field, ""))
        for token in _tokenize(value):
            terms[token] = terms.get(token, 0.0) + weight
    return terms


def _excerpt(document: RetrievedDocument, query: str) -> str:
    text = document.text.strip()
    if not text:
        return ""
    folded = text.casefold()
    positions = [
        folded.find(term) for term in _tokenize(query) if len(term) >= 3 and folded.find(term) >= 0
    ]
    if positions:
        start = max(0, min(positions) - 80)
        end = min(len(text), start + 260)
        snippet = text[start:end].strip()
        if start > 0:
            snippet = "..." + snippet
        if end < len(text):
            snippet = snippet + "..."
        return snippet
    return text[:240] + ("..." if len(text) > 240 else "")


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
        self._term_frequencies: list[dict[str, float]] = []
        self._document_lengths: list[float] = []
        self._average_length = 1.0
        self._document_frequency: Counter[str] = Counter()
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

            frequencies = [_weighted_terms(document) for document in documents]
            lengths = [sum(terms.values()) for terms in frequencies]
            document_frequency: Counter[str] = Counter()
            for terms in frequencies:
                document_frequency.update(terms.keys())

            self._documents = documents
            self._vectors = vectors
            self._term_frequencies = frequencies
            self._document_lengths = lengths
            self._average_length = (sum(lengths) / len(lengths)) if lengths else 1.0
            self._document_frequency = document_frequency
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

    def _bm25_scores(self, query: str, eligible: list[int]) -> dict[int, float]:
        terms = _tokenize(query)
        if not terms:
            return {}
        total = len(self._documents)
        scores: dict[int, float] = {}
        for index in eligible:
            frequencies = self._term_frequencies[index]
            length = self._document_lengths[index]
            score = 0.0
            for term in terms:
                frequency = frequencies.get(term, 0.0)
                if frequency <= 0:
                    continue
                document_frequency = self._document_frequency.get(term, 0)
                inverse_frequency = math.log(
                    1 + (total - document_frequency + 0.5) / (document_frequency + 0.5)
                )
                denominator = frequency + _BM25_K1 * (
                    1 - _BM25_B + _BM25_B * length / self._average_length
                )
                score += inverse_frequency * (frequency * (_BM25_K1 + 1)) / denominator
            if score > 0:
                scores[index] = score
        return scores

    def search_evidence(
        self,
        query: str,
        limit: int = 5,
        filters: dict[str, str] | None = None,
    ) -> list[Evidence]:
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
        lexical = self._bm25_scores(query, eligible)
        lexical_order = sorted(lexical, key=lambda index: (-lexical[index], index))

        query_vector = self._query_vector(query)
        if query_vector.shape[0] != vectors.shape[1]:
            raise RuntimeError("Query embedding dimension does not match the document embeddings.")
        dense_scores = np.asarray(vectors[eligible] @ query_vector, dtype=np.float32)
        dense_order = [
            eligible[int(position)] for position in np.argsort(-dense_scores, kind="stable")
        ]

        fused: dict[int, float] = defaultdict(float)
        channels: dict[int, list[str]] = defaultdict(list)

        def contribute(name: str, order: list[int]) -> None:
            for rank, index in enumerate(order):
                fused[index] += 1.0 / (_RRF_K + rank)
                if name not in channels[index]:
                    channels[index].append(name)

        contribute("exact", exact)
        contribute("lexical", lexical_order)
        contribute("dense", dense_order)
        for index in exact:
            fused[index] += _EXACT_BOOST

        ranked = sorted(fused, key=lambda index: (-fused[index], index))
        return [
            Evidence(
                document=documents[index],
                score=float(fused[index]),
                channels=list(channels[index]),
                excerpt=_excerpt(documents[index], query),
            )
            for index in ranked[:limit]
        ]

    def search(
        self,
        query: str,
        limit: int = 5,
        filters: dict[str, str] | None = None,
    ) -> list[RetrievedDocument]:
        return [
            evidence.document
            for evidence in self.search_evidence(query, limit=limit, filters=filters)
        ]

    def lookup(self, source_file: str, record_id: str) -> RetrievedDocument | None:
        wanted_source = source_file.strip().casefold()
        wanted_record = record_id.strip().casefold()
        with self._lock:
            for document in self._documents:
                if (
                    document.source_file.casefold() == wanted_source
                    and document.record_id.casefold() == wanted_record
                ):
                    return document
        return None


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
