"""Tests for deterministic retrieval (L1).

The property that matters is that exact search returns the same passages in the same order every
time, including when scores tie. If that fails, frozen response files differ between runs and
the whole point of freezing is lost.

Network-free and database-free.
"""

from __future__ import annotations

import math

import pytest

from eval.judge.retrieval import (
    ApproximateRetriever,
    Chunk,
    ExactRetriever,
    HashingEmbedder,
    cosine_similarity,
    hash_to_partition,
    measure_retrieval_delta,
)

TEXTS = [
    "The Central Arizona Project delivers Colorado River water across 336 miles.",
    "Active Management Areas regulate groundwater withdrawal in Phoenix and Tucson.",
    "Lake Mead shortage tiers are defined by the Drought Contingency Plan.",
    "Tribal water settlements allocate Central Arizona Project water to communities.",
    "The Groundwater Management Act of 1980 created the Active Management Areas.",
    "Colorado River flows are measured at Lee's Ferry under the compact.",
]


def build_chunks(embedder, texts=TEXTS):
    return [
        Chunk(
            chunk_id=f"chunk_{i:02d}",
            canonical_doc_id=f"doc_{i // 2}",
            text=text,
            embedding=tuple(embedder.embed(text)),
        )
        for i, text in enumerate(texts)
    ]


@pytest.fixture
def embedder():
    return HashingEmbedder(dimension=48)


@pytest.fixture
def retriever(embedder):
    return ExactRetriever(build_chunks(embedder), embedder)


# ---------------------------------------------------------------------------
# Cosine
# ---------------------------------------------------------------------------
def test_cosine_of_identical_vectors_is_one():
    assert cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_cosine_ignores_magnitude():
    assert cosine_similarity([1.0, 0.0], [7.0, 0.0]) == pytest.approx(1.0)


def test_cosine_of_orthogonal_vectors_is_zero():
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_of_opposite_vectors_is_minus_one():
    assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


def test_cosine_of_a_zero_vector_is_defined_not_raised():
    """A degenerate embedding must not crash a whole freeze; 0.0 sorts it to the bottom."""
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_cosine_rejects_mismatched_dimensions():
    with pytest.raises(ValueError, match="dimension mismatch"):
        cosine_similarity([1.0, 2.0], [1.0])


# ---------------------------------------------------------------------------
# Embedder
# ---------------------------------------------------------------------------
def test_embedder_is_deterministic_across_calls(embedder):
    assert embedder.embed("Lake Mead") == embedder.embed("Lake Mead")


def test_embedder_is_deterministic_across_instances():
    """Python's hash() is salted per process; the embedder must not depend on it."""
    assert HashingEmbedder(32).embed("Lake Mead") == HashingEmbedder(32).embed("Lake Mead")


def test_embedder_returns_unit_vectors(embedder):
    vector = embedder.embed("Colorado River compact")
    assert math.sqrt(sum(v * v for v in vector)) == pytest.approx(1.0)


def test_shared_vocabulary_scores_higher_than_unrelated_text(embedder):
    """Not semantic, but ordered enough to exercise retrieval meaningfully."""
    base = embedder.embed("Colorado River water delivery")
    related = embedder.embed("Colorado River water compact")
    unrelated = embedder.embed("quantum computing applications")
    assert cosine_similarity(base, related) > cosine_similarity(base, unrelated)


def test_empty_text_still_embeds(embedder):
    vector = embedder.embed("...")
    assert len(vector) == embedder.dimension
    assert math.sqrt(sum(v * v for v in vector)) == pytest.approx(1.0)


def test_embedder_rejects_a_degenerate_dimension():
    with pytest.raises(ValueError):
        HashingEmbedder(dimension=1)


# ---------------------------------------------------------------------------
# Exact retrieval
# ---------------------------------------------------------------------------
def test_search_returns_k_hits_ranked_from_zero(retriever):
    hits = retriever.search("Central Arizona Project", k=3)
    assert len(hits) == 3
    assert [h.rank for h in hits] == [0, 1, 2]


def test_scores_are_non_increasing(retriever):
    hits = retriever.search("groundwater management", k=6)
    scores = [h.score for h in hits]
    assert scores == sorted(scores, reverse=True)


def test_search_is_reproducible(retriever):
    first = retriever.search("Colorado River", k=4)
    second = retriever.search("Colorado River", k=4)
    assert [h.chunk.chunk_id for h in first] == [h.chunk.chunk_id for h in second]


def test_result_order_does_not_depend_on_insertion_order(embedder):
    """The determinism property that makes byte-identical freezes possible."""
    chunks = build_chunks(embedder)
    forward = ExactRetriever(chunks, embedder).search("Arizona water", k=5)
    backward = ExactRetriever(list(reversed(chunks)), embedder).search("Arizona water", k=5)
    assert [h.chunk.chunk_id for h in forward] == [h.chunk.chunk_id for h in backward]


def test_ties_break_by_chunk_id(embedder):
    """Identical text in two chunks gives identical scores; the order must still be total."""
    shared = "Identical passage text for both chunks."
    chunks = [
        Chunk("chunk_zz", "doc_a", shared, tuple(embedder.embed(shared))),
        Chunk("chunk_aa", "doc_b", shared, tuple(embedder.embed(shared))),
    ]
    hits = ExactRetriever(chunks, embedder).search(shared, k=2)
    assert hits[0].score == pytest.approx(hits[1].score)
    assert [h.chunk.chunk_id for h in hits] == ["chunk_aa", "chunk_zz"]


def test_asking_for_more_than_the_corpus_returns_the_corpus(retriever):
    assert len(retriever.search("water", k=999)) == len(retriever)


def test_exact_search_finds_the_true_best_match(retriever):
    """Exhaustive by construction: the top hit is the highest-scoring chunk in the index."""
    query = "Active Management Areas regulate groundwater withdrawal in Phoenix and Tucson."
    assert retriever.search(query, k=1)[0].chunk.text == query


@pytest.mark.parametrize("k", [0, -1])
def test_invalid_k_is_rejected(retriever, k):
    with pytest.raises(ValueError, match="k must be at least 1"):
        retriever.search("water", k=k)


def test_empty_index_is_rejected(embedder):
    with pytest.raises(ValueError, match="empty chunk set"):
        ExactRetriever([], embedder)


def test_duplicate_chunk_ids_are_rejected(embedder):
    vector = tuple(embedder.embed("text"))
    with pytest.raises(ValueError, match="duplicate chunk ids"):
        ExactRetriever(
            [Chunk("same", "d", "a", vector), Chunk("same", "d", "b", vector)], embedder
        )


def test_mixed_embedding_dimensions_are_rejected(embedder):
    with pytest.raises(ValueError, match="mixed embedding dimensions"):
        ExactRetriever(
            [Chunk("a", "d", "x", (1.0, 0.0)), Chunk("b", "d", "y", (1.0, 0.0, 0.0))], embedder
        )


def test_query_dimension_must_match_the_index(embedder):
    retriever = ExactRetriever(build_chunks(embedder), embedder)
    retriever._embedder = HashingEmbedder(dimension=8)  # a different embedder than the index
    with pytest.raises(ValueError, match="dimension"):
        retriever.search("water", k=1)


def test_chunk_rejects_an_empty_embedding():
    with pytest.raises(ValueError, match="empty embedding"):
        Chunk("a", "d", "text", ())


def test_chunk_rejects_an_empty_id():
    with pytest.raises(ValueError, match="chunk_id"):
        Chunk("", "d", "text", (1.0,))


# ---------------------------------------------------------------------------
# Approximate retrieval and the measured delta
# ---------------------------------------------------------------------------
def test_partition_assignment_is_stable_across_instances():
    assert hash_to_partition("Lake Mead", 8) == hash_to_partition("Lake Mead", 8)


def test_approximate_search_can_miss_a_true_neighbour(embedder):
    """The failure being modelled: a neighbour in an unvisited partition is invisible."""
    chunks = build_chunks(embedder)
    exact = ExactRetriever(chunks, embedder)
    approximate = ApproximateRetriever(chunks, embedder, probes=1, partitions=6)

    misses = 0
    for text in TEXTS:
        exact_ids = {h.chunk.chunk_id for h in exact.search(text, k=3)}
        approximate_ids = {h.chunk.chunk_id for h in approximate.search(text, k=3)}
        if exact_ids - approximate_ids:
            misses += 1
    assert misses > 0


def test_more_probes_recover_more_of_the_truth(embedder):
    chunks = build_chunks(embedder)
    exact = ExactRetriever(chunks, embedder)
    narrow = measure_retrieval_delta(
        TEXTS, exact, ApproximateRetriever(chunks, embedder, probes=1, partitions=6), k=3
    )
    wide = measure_retrieval_delta(
        TEXTS, exact, ApproximateRetriever(chunks, embedder, probes=6, partitions=6), k=3
    )
    assert wide.mean_overlap >= narrow.mean_overlap


def test_scanning_every_partition_reproduces_exact_search(embedder):
    chunks = build_chunks(embedder)
    exact = ExactRetriever(chunks, embedder)
    full = ApproximateRetriever(chunks, embedder, probes=6, partitions=6)
    delta = measure_retrieval_delta(TEXTS, exact, full, k=3)
    assert delta.mean_overlap == pytest.approx(1.0)
    assert delta.exact_only == 0


def test_delta_reports_in_percentage_points(embedder):
    """Turns a threat-to-validity paragraph into a number comparable to metric reporting."""
    chunks = build_chunks(embedder)
    delta = measure_retrieval_delta(
        TEXTS,
        ExactRetriever(chunks, embedder),
        ApproximateRetriever(chunks, embedder, probes=6, partitions=6),
        k=3,
    )
    assert delta.agreement_points == pytest.approx(100.0)
    assert delta.to_dict()["n_queries"] == len(TEXTS)


def test_delta_requires_queries(embedder):
    chunks = build_chunks(embedder)
    with pytest.raises(ValueError, match="at least one query"):
        measure_retrieval_delta(
            [], ExactRetriever(chunks, embedder),
            ApproximateRetriever(chunks, embedder), k=3
        )


def test_approximate_retriever_rejects_invalid_settings(embedder):
    chunks = build_chunks(embedder)
    with pytest.raises(ValueError, match="must be positive"):
        ApproximateRetriever(chunks, embedder, probes=0)
