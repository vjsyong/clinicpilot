"""Local FastEmbed/ONNX cross-encoder reranking.

The reranker is optional and loaded lazily so the application can start and
serve retrieval even when reranking is disabled. Tests inject a deterministic
fake reranker.
"""

from __future__ import annotations

import importlib
import threading
from collections.abc import Sequence
from typing import Any, Protocol

from app.retrieval.fastembed_cache import (
    cache_directory,
    dereference_model_symlinks,
    is_external_data_error,
)
from app.settings import Settings, get_settings


class Reranker(Protocol):
    model_name: str
    revision: str

    def prewarm(self) -> None: ...

    def rerank(self, query: str, texts: Sequence[str]) -> list[float]: ...


class FastEmbedReranker:
    """Lazy FastEmbed wrapper for a cross-encoder reranker (ONNX, CPU)."""

    def __init__(self, model_name: str, revision: str, *, threads: int = 8) -> None:
        self.model_name = model_name
        self.revision = revision
        self.threads = threads
        self._model: Any | None = None
        self._lock = threading.Lock()

    def _load(self) -> Any:
        if self._model is None:
            with self._lock:
                if self._model is None:
                    module = importlib.import_module("fastembed.rerank.cross_encoder")
                    cache_dir = cache_directory()
                    try:
                        self._model = module.TextCrossEncoder(
                            model_name=self.model_name,
                            cache_dir=str(cache_dir),
                            threads=self.threads,
                        )
                    except Exception as exc:
                        if not is_external_data_error(exc):
                            raise
                        dereference_model_symlinks(cache_dir)
                        self._model = module.TextCrossEncoder(
                            model_name=self.model_name,
                            cache_dir=str(cache_dir),
                            threads=self.threads,
                        )
        return self._model

    def prewarm(self) -> None:
        self._load()

    def rerank(self, query: str, texts: Sequence[str]) -> list[float]:
        if not texts:
            return []
        model = self._load()
        return [float(score) for score in model.rerank(query, list(texts))]


_DEFAULT_RERANKERS: dict[tuple[str, str, int], FastEmbedReranker] = {}
_DEFAULT_LOCK = threading.Lock()


def default_reranker(settings: Settings | None = None) -> FastEmbedReranker:
    settings = settings or get_settings()
    key = (
        settings.reranker_model,
        settings.reranker_revision,
        settings.reranker_threads,
    )
    with _DEFAULT_LOCK:
        reranker = _DEFAULT_RERANKERS.get(key)
        if reranker is None:
            reranker = FastEmbedReranker(
                settings.reranker_model,
                settings.reranker_revision,
                threads=settings.reranker_threads,
            )
            _DEFAULT_RERANKERS[key] = reranker
    return reranker
