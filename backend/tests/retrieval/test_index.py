from __future__ import annotations

import itertools

import pytest
from app.retrieval.index import build_knowledge_index
from tests.conftest import DBHarness
from tests.retrieval.conftest import FakeEmbedder, FakeReranker

KNOWN_RECORD_IDS = {
    "C001",
    "C002",
    "D101",
    "D102",
    "D103",
    "D104",
    "T001",
    "T002",
    "T003",
    "T004",
    "T005",
}


async def _csv_index(
    settings,
    embedder: FakeEmbedder,
    reranker: FakeReranker | None = None,
):
    index = build_knowledge_index(
        settings,
        None,
        embedder=embedder,
        reranker=reranker or FakeReranker(),
    )
    await index.prewarm()
    return index


async def test_ready_is_false_until_prewarm(retrieval_settings, fake_embedder) -> None:
    index = build_knowledge_index(
        retrieval_settings,
        None,
        embedder=fake_embedder,
        reranker=FakeReranker(),
    )
    assert index.ready() is False
    with pytest.raises(RuntimeError, match="prewarm"):
        index.search("D104")

    await index.prewarm()

    assert index.ready() is True
    assert len(index.documents) == 11
    assert fake_embedder.prewarmed is True


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("D104", "doctors:D104"),
        ("dr james wilson", "doctors:D104"),
        ("Dr. James Wilson", "doctors:D104"),
        ("doctors:D104", "doctors:D104"),
        ("T005", "treatments:T005"),
        ("Metro Care", "clinics:C001"),
        ("Sunset Wellness Center", "clinics:C002"),
    ],
)
async def test_exact_id_and_name_resolution(
    retrieval_settings, fake_embedder, query: str, expected: str
) -> None:
    index = await _csv_index(retrieval_settings, fake_embedder)

    results = index.search(query)

    assert results[0].document_id == expected
    assert results[0].source_file
    assert results[0].record_id


async def test_knee_paraphrase_ranks_orthopedics(retrieval_settings, fake_embedder) -> None:
    index = await _csv_index(retrieval_settings, fake_embedder)

    results = index.search("my knee hurts", limit=5)
    ids = [document.document_id for document in results]

    assert ids[0] in {"doctors:D104", "treatments:T005"}
    assert "doctors:D104" in ids[:2]
    assert "treatments:T005" in ids[:2]


async def test_allergy_query_does_not_invent_a_service(retrieval_settings, fake_embedder) -> None:
    index = await _csv_index(retrieval_settings, fake_embedder)

    results = index.search("allergy", limit=11)

    assert results
    for document in results:
        assert document.record_id in KNOWN_RECORD_IDS
        assert "allerg" not in document.text.casefold()
        assert document.metadata.get("specialty", "").casefold() != "allergy"
        assert document.metadata.get("category", "").casefold() != "allergy"


async def test_filters_restrict_results(retrieval_settings, fake_embedder) -> None:
    index = await _csv_index(retrieval_settings, fake_embedder)

    doctors = index.search("consultation", limit=10, filters={"source_file": "doctors.csv"})
    assert len(doctors) == 4
    assert all(document.source_file == "doctors.csv" for document in doctors)

    orthopedics = index.search("joint pain", limit=10, filters={"specialty": "Orthopedics"})
    assert [document.record_id for document in orthopedics] == ["D104"]

    treatment = index.search("joint pain", limit=10, filters={"category": "Orthopedics"})
    assert [document.record_id for document in treatment] == ["T005"]

    sunset = index.search("clinic", limit=10, filters={"clinic_id": "C002"})
    assert {document.record_id for document in sunset} == {"C002", "D103"}


async def test_results_carry_matching_source_refs(retrieval_settings, fake_embedder) -> None:
    index = await _csv_index(retrieval_settings, fake_embedder)
    by_id = {document.document_id: document for document in index.documents}

    for result in index.search("joint pain", limit=5):
        source = by_id[result.document_id]
        assert result.source_file == source.source_file
        assert result.record_id == source.record_id
        assert result.text == source.text


async def test_db_backed_index_uses_session_factory(db: DBHarness, fake_embedder) -> None:
    index = build_knowledge_index(
        db.settings,
        db.session_factory,
        embedder=fake_embedder,
        reranker=FakeReranker(),
    )

    await index.prewarm()

    assert index.ready() is True
    assert len(index.documents) == 11
    results = index.search("D104")
    assert results[0].document_id == "doctors:D104"


async def test_search_evidence_reports_channels_and_excerpt(
    retrieval_settings, fake_embedder
) -> None:
    index = await _csv_index(retrieval_settings, fake_embedder)

    evidence = index.search_evidence("D104")

    assert evidence[0].document.document_id == "doctors:D104"
    assert "exact" in evidence[0].channels
    assert evidence[0].excerpt
    assert evidence[0].score > 0
    assert all(item.score >= next_item.score for item, next_item in itertools.pairwise(evidence))


async def test_lexical_channel_resolves_policy_phrases(retrieval_settings, fake_embedder) -> None:
    index = await _csv_index(retrieval_settings, fake_embedder)

    evidence = index.search_evidence("cancellation policy", limit=5)

    assert evidence
    assert evidence[0].document.record_id in {"C001", "C002"}
    assert "lexical" in evidence[0].channels


async def test_evidence_filters_and_lookup_are_consistent(
    retrieval_settings, fake_embedder
) -> None:
    index = await _csv_index(retrieval_settings, fake_embedder)

    evidence = index.search_evidence("joint pain", filters={"specialty": "Orthopedics"})
    assert [item.document.record_id for item in evidence] == ["D104"]
    assert "lexical" in evidence[0].channels

    document = index.lookup("doctors.csv", "d104")
    assert document is not None
    assert document.document_id == "doctors:D104"
    assert index.lookup("doctors.csv", "D999") is None


async def test_search_and_search_evidence_agree(retrieval_settings, fake_embedder) -> None:
    index = await _csv_index(retrieval_settings, fake_embedder)

    documents = index.search("my knee hurts", limit=5)
    evidence = index.search_evidence("my knee hurts", limit=5)

    assert [document.document_id for document in documents] == [
        item.document.document_id for item in evidence
    ]


async def test_reranker_reorders_and_reports_channel(retrieval_settings, fake_embedder) -> None:
    reranker = FakeReranker(lambda text: 10.0 if "Sunset" in text else 0.0)
    index = await _csv_index(retrieval_settings, fake_embedder, reranker=reranker)

    evidence = index.search_evidence("clinic", limit=5)

    assert evidence[0].document.record_id == "C002"
    assert "rerank" in evidence[0].channels
    assert reranker.calls


async def test_exact_matches_stay_ahead_of_reranker(retrieval_settings, fake_embedder) -> None:
    reranker = FakeReranker(lambda text: -100.0 if "D104" in text else 100.0)
    index = await _csv_index(retrieval_settings, fake_embedder, reranker=reranker)

    evidence = index.search_evidence("D104", limit=5)

    assert evidence[0].document.record_id == "D104"
    assert "exact" in evidence[0].channels
    assert "rerank" in evidence[0].channels
    assert all(item.score >= next_item.score for item, next_item in itertools.pairwise(evidence))


async def test_reranker_failure_falls_back_to_hybrid(retrieval_settings, fake_embedder) -> None:
    failing = FakeReranker(error=RuntimeError("reranker unavailable"))
    baseline = await _csv_index(retrieval_settings, fake_embedder)
    index = await _csv_index(retrieval_settings, fake_embedder, reranker=failing)

    expected = [item.document.record_id for item in baseline.search_evidence("my knee hurts")]
    evidence = index.search_evidence("my knee hurts")

    assert [item.document.record_id for item in evidence] == expected
    assert all("rerank" not in item.channels for item in evidence)


async def test_disabled_reranker_skips_rerank_channel(retrieval_settings, fake_embedder) -> None:
    settings = retrieval_settings.model_copy(update={"reranker_enabled": False})
    index = build_knowledge_index(settings, None, embedder=fake_embedder)
    await index.prewarm()

    evidence = index.search_evidence("my knee hurts")

    assert evidence
    assert all("rerank" not in item.channels for item in evidence)
