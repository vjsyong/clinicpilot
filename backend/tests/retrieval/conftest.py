from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np
import pytest
from app.settings import REPO_ROOT, Settings
from numpy.typing import NDArray

DIMENSION = 96

_GROUPS: dict[str, set[str]] = {
    "orthopedics": {
        "ache",
        "aching",
        "hurt",
        "hurts",
        "injuries",
        "injury",
        "joint",
        "joints",
        "knee",
        "knees",
        "musculoskeletal",
        "orthopedic",
        "orthopedics",
        "pain",
        "pains",
        "rehabilitation",
        "rehab",
        "sports",
    },
    "allergy": {"allergic", "allergies", "allergist", "allergy"},
}

_TOKEN_GROUP = {token: group for group, tokens in _GROUPS.items() for token in tokens}


def _features(text: str) -> NDArray[np.float32]:
    vector = np.zeros(DIMENSION, dtype=np.float32)
    for token in re.findall(r"[a-z0-9]+", text.casefold()):
        feature = _TOKEN_GROUP.get(token, token)
        digest = hashlib.sha256(feature.encode("utf-8")).digest()
        position = int.from_bytes(digest[:4], "big") % DIMENSION
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[position] += sign
    norm = float(np.linalg.norm(vector))
    if norm:
        vector /= norm
    return vector


class FakeEmbedder:
    """Deterministic hashing bag-of-words with a few semantic synonym groups."""

    model_name = "fake-hashing-bow"
    revision = "test-v1"

    def embed_texts(self, texts: Sequence[str]) -> NDArray[np.float32]:
        if not texts:
            return np.zeros((0, DIMENSION), dtype=np.float32)
        return np.vstack([_features(text) for text in texts]).astype(np.float32)

    def embed_query(self, text: str) -> NDArray[np.float32]:
        return _features(text)


class FakeReranker:
    """Deterministic reranker; zero scores preserve the fused order."""

    model_name = "fake-reranker"
    revision = "test-v1"

    def __init__(
        self,
        scorer: Callable[[str], float] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.scorer = scorer or (lambda _text: 0.0)
        self.error = error
        self.calls: list[tuple[str, list[str]]] = []

    def prewarm(self) -> None:
        return None

    def rerank(self, query: str, texts: Sequence[str]) -> list[float]:
        self.calls.append((query, list(texts)))
        if self.error is not None:
            raise self.error
        return [float(self.scorer(text)) for text in texts]


@pytest.fixture
def fake_embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture
def fake_reranker() -> FakeReranker:
    return FakeReranker()


@pytest.fixture
def retrieval_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        database_url=f"sqlite:///{tmp_path / 'data' / 'clinicpilot.db'}",
        csv_dir=REPO_ROOT / "dkl_ai_interview_data",
    )
