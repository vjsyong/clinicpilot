"""Pinned local model identity shared by settings and the image prewarm step.

This module deliberately has no imports from the application so the Dockerfile
can prewarm models in a cacheable layer without copying the whole backend.
Keep these values in sync with the deployed embedding/reranker stack.
"""

from __future__ import annotations

EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-0.6B"
EMBEDDING_REVISION = "af95f2c416ffe9379369ad64f9113e865db6112c"
EMBEDDING_QUERY_PREFIX = (
    "Instruct: Given a search query, retrieve relevant clinic, doctor, and "
    "treatment records\nQuery: "
)
EMBEDDING_THREADS = 8

RERANKER_MODEL = "jinaai/jina-reranker-v1-turbo-en"
RERANKER_REVISION = "b8c14f4e723d9e0aab4732a7b7b93741eeeb77c2"
RERANKER_THREADS = 8
