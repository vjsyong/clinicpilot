"""Local FastEmbed/ONNX embeddings with a fingerprint-keyed vector cache.

Qwen3-Embedding uses an instruction prefix for queries and a raw document
input. The model is loaded lazily so importing the retrieval package never
imports ONNX. Tests inject a deterministic fake embedder.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import tempfile
import threading
import zipfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from numpy.typing import NDArray

from app.contracts import RetrievedDocument
from app.retrieval.fastembed_cache import (
    cache_directory,
    dereference_model_symlinks,
    is_external_data_error,
)
from app.settings import Settings, get_settings

Vector = NDArray[np.float32]


class Embedder(Protocol):
    model_name: str
    revision: str

    def prewarm(self) -> None: ...

    def embed_texts(self, texts: Sequence[str]) -> Vector: ...

    def embed_query(self, text: str) -> Vector: ...


def _normalize(vectors: NDArray[np.float32]) -> Vector:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (vectors / norms).astype(np.float32, copy=False)


def _validated(vectors: Any, expected_rows: int) -> Vector:
    array = np.asarray(vectors, dtype=np.float32)
    if array.ndim != 2 or array.shape[0] != expected_rows:
        raise RuntimeError(
            "The embedder returned an unexpected vector shape: "
            f"expected ({expected_rows}, n), got {array.shape}."
        )
    if expected_rows and not np.isfinite(array).all():
        raise RuntimeError("The embedder returned non-finite vector values.")
    return _normalize(array)


class FastEmbedder:
    """Lazy FastEmbed wrapper for Qwen3-Embedding (ONNX, CPU)."""

    def __init__(
        self,
        model_name: str,
        revision: str,
        *,
        threads: int = 8,
        query_prefix: str = "",
    ) -> None:
        self.model_name = model_name
        self.revision = revision
        self.threads = threads
        self.query_prefix = query_prefix
        self._model: Any | None = None
        self._lock = threading.Lock()

    def _load(self) -> Any:
        if self._model is None:
            with self._lock:
                if self._model is None:
                    module = importlib.import_module("fastembed")
                    cache_dir = cache_directory()
                    try:
                        self._model = module.TextEmbedding(
                            model_name=self.model_name,
                            cache_dir=str(cache_dir),
                            threads=self.threads,
                        )
                    except Exception as exc:
                        if not is_external_data_error(exc):
                            raise
                        dereference_model_symlinks(cache_dir)
                        self._model = module.TextEmbedding(
                            model_name=self.model_name,
                            cache_dir=str(cache_dir),
                            threads=self.threads,
                        )
        return self._model

    def prewarm(self) -> None:
        self._load()

    def _embed(self, texts: Sequence[str]) -> Vector:
        model = self._load()
        return np.asarray(list(model.embed(list(texts))), dtype=np.float32)

    def embed_texts(self, texts: Sequence[str]) -> Vector:
        if not texts:
            return np.empty((0, 0), dtype=np.float32)
        return _validated(self._embed(texts), len(texts))

    def embed_query(self, text: str) -> Vector:
        prefixed = f"{self.query_prefix}{text}" if self.query_prefix else text
        vector: Vector = self.embed_texts([prefixed])[0]
        return vector


_DEFAULT_EMBEDDERS: dict[tuple[str, str, int, str], FastEmbedder] = {}
_DEFAULT_LOCK = threading.Lock()


def default_embedder(settings: Settings | None = None) -> FastEmbedder:
    settings = settings or get_settings()
    key = (
        settings.embedding_model,
        settings.embedding_revision,
        settings.embedding_threads,
        settings.embedding_query_prefix,
    )
    with _DEFAULT_LOCK:
        embedder = _DEFAULT_EMBEDDERS.get(key)
        if embedder is None:
            embedder = FastEmbedder(
                settings.embedding_model,
                settings.embedding_revision,
                threads=settings.embedding_threads,
                query_prefix=settings.embedding_query_prefix,
            )
            _DEFAULT_EMBEDDERS[key] = embedder
    return embedder


def embed_texts(
    texts: Sequence[str],
    *,
    settings: Settings | None = None,
    embedder: Embedder | None = None,
) -> Vector:
    """Embed and normalize a batch of texts with the configured local model."""
    return (embedder or default_embedder(settings)).embed_texts(texts)


def embed_query(
    text: str,
    *,
    settings: Settings | None = None,
    embedder: Embedder | None = None,
) -> Vector:
    """Embed one query; the returned vector is normalized float32."""
    return (embedder or default_embedder(settings)).embed_query(text)


def embedder_identity(embedder: Embedder) -> tuple[str, str]:
    return (
        str(getattr(embedder, "model_name", type(embedder).__qualname__)),
        str(getattr(embedder, "revision", "")),
    )


def cache_fingerprint(
    model_name: str,
    revision: str,
    inputs: Sequence[tuple[str, str]],
) -> str:
    """Hash the model identity and the serialized document inputs."""
    payload = json.dumps(
        {
            "model": model_name,
            "revision": revision,
            "documents": [[document_id, text] for document_id, text in inputs],
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def data_directory(settings: Settings) -> Path:
    """Return the data directory holding the SQLite database, if it has one."""
    url = settings.database_url
    if url.startswith("sqlite:///"):
        raw = url.removeprefix("sqlite:///")
        if raw and not raw.startswith(":memory:"):
            return Path(raw).expanduser().resolve().parent
    return Path.cwd()


def cache_path(settings: Settings, fingerprint: str) -> Path:
    return data_directory(settings) / f"embedding_cache-{fingerprint}.npz"


_MEMORY_CACHE: dict[str, Vector] = {}
_MEMORY_LOCK = threading.Lock()


def clear_memory_cache() -> None:
    with _MEMORY_LOCK:
        _MEMORY_CACHE.clear()


def load_cached_vectors(path: Path, expected_rows: int) -> Vector | None:
    """Load a cache file, returning ``None`` when it is absent or corrupt."""
    if not path.is_file():
        return None
    try:
        with np.load(path, allow_pickle=False) as data:
            vectors = np.asarray(data["vectors"], dtype=np.float32)
    except (OSError, ValueError, KeyError, EOFError, zipfile.BadZipFile):
        return None
    if vectors.ndim != 2 or vectors.shape[0] != expected_rows:
        return None
    if expected_rows and not np.isfinite(vectors).all():
        return None
    return _normalize(vectors)


def save_cached_vectors(path: Path, vectors: Vector) -> None:
    """Atomically write vectors to a ``.npz`` cache file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    temporary_path = Path(temporary)
    try:
        with os.fdopen(handle, "wb") as stream:
            np.savez(stream, vectors=vectors)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def embed_documents(
    documents: Sequence[RetrievedDocument],
    embedder: Embedder,
    settings: Settings,
) -> Vector:
    """Return normalized document vectors, using the memory/disk cache."""
    inputs = [(document.document_id, document.text) for document in documents]
    model_name, revision = embedder_identity(embedder)
    fingerprint = cache_fingerprint(model_name, revision, inputs)

    with _MEMORY_LOCK:
        memory = _MEMORY_CACHE.get(fingerprint)
        if memory is not None and memory.shape[0] == len(documents):
            return memory

    path = cache_path(settings, fingerprint)
    vectors = load_cached_vectors(path, len(documents))
    if vectors is None:
        vectors = _validated(
            embedder.embed_texts([document.text for document in documents]),
            len(documents),
        )
        save_cached_vectors(path, vectors)

    with _MEMORY_LOCK:
        _MEMORY_CACHE[fingerprint] = vectors
    return vectors
