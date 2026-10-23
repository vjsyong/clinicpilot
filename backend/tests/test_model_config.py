from __future__ import annotations

from app.model_config import (
    EMBEDDING_MODEL,
    EMBEDDING_QUERY_PREFIX,
    EMBEDDING_REVISION,
    EMBEDDING_THREADS,
    RERANKER_MODEL,
    RERANKER_REVISION,
    RERANKER_THREADS,
)
from app.settings import Settings


def test_model_manifest_matches_settings_defaults() -> None:
    settings = Settings(_env_file=None, app_env="test")

    assert settings.embedding_model == EMBEDDING_MODEL
    assert settings.embedding_revision == EMBEDDING_REVISION
    assert settings.embedding_query_prefix == EMBEDDING_QUERY_PREFIX
    assert settings.embedding_threads == EMBEDDING_THREADS
    assert settings.reranker_model == RERANKER_MODEL
    assert settings.reranker_revision == RERANKER_REVISION
    assert settings.reranker_threads == RERANKER_THREADS
