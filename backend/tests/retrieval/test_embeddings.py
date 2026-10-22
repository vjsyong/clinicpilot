from __future__ import annotations

from pathlib import Path

import numpy as np
from app.retrieval.documents import documents_from_csv
from app.retrieval.embeddings import (
    cache_fingerprint,
    cache_path,
    clear_memory_cache,
    embed_documents,
)
from app.settings import Settings
from tests.retrieval.conftest import FakeEmbedder


def test_cache_fingerprint_tracks_model_revision_and_text() -> None:
    inputs = [("clinics:C001", "Clinic C001: Metro Care Health Clinic.")]

    baseline = cache_fingerprint("model", "rev", inputs)
    assert baseline == cache_fingerprint("model", "rev", list(inputs))
    assert cache_fingerprint("other-model", "rev", inputs) != baseline
    assert cache_fingerprint("model", "other-rev", inputs) != baseline
    assert (
        cache_fingerprint(
            "model", "rev", [("clinics:C001", "Clinic C001: Sunset Wellness Center.")]
        )
        != baseline
    )
    assert cache_fingerprint("model", "rev", [("clinics:C002", inputs[0][1])]) != baseline


def test_cache_path_is_a_sibling_of_the_sqlite_database(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=f"sqlite:///{tmp_path / 'state' / 'clinicpilot.db'}",
    )

    path = cache_path(settings, "abc123")

    assert path == (tmp_path / "state").resolve() / "embedding_cache-abc123.npz"


def test_embed_documents_recomputes_missing_cache(
    retrieval_settings, fake_embedder: FakeEmbedder
) -> None:
    documents = documents_from_csv(retrieval_settings)
    inputs = [(document.document_id, document.text) for document in documents]
    fingerprint = cache_fingerprint(fake_embedder.model_name, fake_embedder.revision, inputs)
    path = cache_path(retrieval_settings, fingerprint)
    path.unlink(missing_ok=True)
    clear_memory_cache()

    vectors = embed_documents(documents, fake_embedder, retrieval_settings)

    assert vectors.shape == (11, 96)
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0)
    assert path.is_file()
    with np.load(path, allow_pickle=False) as data:
        assert data["vectors"].shape == vectors.shape


def test_embed_documents_recomputes_corrupt_cache(
    retrieval_settings, fake_embedder: FakeEmbedder
) -> None:
    documents = documents_from_csv(retrieval_settings)
    inputs = [(document.document_id, document.text) for document in documents]
    fake_embedder.revision = "corrupt-cache-v1"
    fingerprint = cache_fingerprint(fake_embedder.model_name, fake_embedder.revision, inputs)
    path = cache_path(retrieval_settings, fingerprint)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"this is not a numpy archive")
    clear_memory_cache()

    vectors = embed_documents(documents, fake_embedder, retrieval_settings)

    assert vectors.shape == (11, 96)
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0)
    with np.load(path, allow_pickle=False) as data:
        assert data["vectors"].shape == vectors.shape
