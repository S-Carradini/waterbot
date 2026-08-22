"""Deterministic retrieval for the frozen response set.

WHY THIS EXISTS
---------------
Production retrieval uses an approximate index (ivfflat). Two identical runs already differ by
roughly 2 points on retrieval metrics, because an approximate index does not promise the same
neighbours twice. That is fine for serving users and fatal for measurement: judge disagreement
and retrieval drift would be tangled together, and no amount of judge replication could separate
them.

At 288 documents, exact k-nearest-neighbour search is cheap. So the paper-grade freeze runs
exact search, which is reproducible by construction, and the approximate-versus-exact difference
becomes a *measured, reported quantity* rather than a threat-to-validity paragraph.

DETERMINISM IS THE WHOLE POINT
------------------------------
Two freezes of the same corpus must produce byte-identical response files (milestone 4's
acceptance check). Cosine similarity on floats can tie, and ties broken by dictionary iteration
order would silently reorder passages between runs. Every ordering here is total: score
descending, then chunk id ascending. Nothing is left to chance or to insertion order.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Protocol, Sequence, Tuple


@dataclass(frozen=True)
class Chunk:
    """One indexed passage, with its embedding pinned alongside its text."""

    chunk_id: str
    canonical_doc_id: str
    text: str
    embedding: Tuple[float, ...]

    def __post_init__(self) -> None:
        if not self.chunk_id:
            raise ValueError("chunk_id may not be empty")
        if not self.embedding:
            raise ValueError(f"chunk {self.chunk_id} has an empty embedding")


@dataclass(frozen=True)
class Hit:
    """One retrieved chunk with the score and rank it was retrieved at."""

    chunk: Chunk
    score: float
    rank: int  # 0-based


class Embedder(Protocol):
    """Turns text into a vector. Injected so retrieval is testable without a provider."""

    def embed(self, text: str) -> Sequence[float]: ...


# ---------------------------------------------------------------------------
# Vector maths
# ---------------------------------------------------------------------------
def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity, with zero vectors defined as maximally dissimilar.

    A zero vector has no direction, so the angle is undefined. Returning 0.0 rather than raising
    keeps a degenerate embedding from crashing a whole freeze, and 0.0 sorts it to the bottom
    where an undefined match belongs.
    """
    if len(a) != len(b):
        raise ValueError(f"dimension mismatch: {len(a)} vs {len(b)}")
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (norm_a * norm_b)


# ---------------------------------------------------------------------------
# Exact retrieval
# ---------------------------------------------------------------------------
class ExactRetriever:
    """Brute-force cosine k-NN over an in-memory chunk set.

    Exhaustive, so it returns the true nearest neighbours every time. At this corpus size the
    cost is irrelevant and the reproducibility is worth everything.
    """

    def __init__(self, chunks: Sequence[Chunk], embedder: Embedder) -> None:
        if not chunks:
            raise ValueError("cannot build a retriever over an empty chunk set")
        ids = [c.chunk_id for c in chunks]
        if len(set(ids)) != len(ids):
            duplicates = sorted({i for i in ids if ids.count(i) > 1})
            raise ValueError(f"duplicate chunk ids: {duplicates[:5]}")

        dimensions = {len(c.embedding) for c in chunks}
        if len(dimensions) != 1:
            raise ValueError(f"chunks have mixed embedding dimensions: {sorted(dimensions)}")

        # Sorted once at construction, so retrieval order never depends on insertion order.
        self._chunks: Tuple[Chunk, ...] = tuple(sorted(chunks, key=lambda c: c.chunk_id))
        self._embedder = embedder
        self.dimension = dimensions.pop()

    def __len__(self) -> int:
        return len(self._chunks)

    def search(self, query: str, k: int = 4) -> List[Hit]:
        if k < 1:
            raise ValueError("k must be at least 1")
        query_vector = self._embedder.embed(query)
        if len(query_vector) != self.dimension:
            raise ValueError(
                f"query embedding has dimension {len(query_vector)}, "
                f"index has {self.dimension}"
            )

        scored = [
            (cosine_similarity(query_vector, chunk.embedding), chunk) for chunk in self._chunks
        ]
        # Total order: score descending, then chunk_id ascending. Without the second key, two
        # chunks with equal similarity would be ordered by whatever the sort happened to see
        # first, and identical corpora could produce different frozen files.
        scored.sort(key=lambda pair: (-pair[0], pair[1].chunk_id))
        return [
            Hit(chunk=chunk, score=score, rank=rank)
            for rank, (score, chunk) in enumerate(scored[:k])
        ]


class ApproximateRetriever:
    """Stands in for an ivfflat index: searches only a subset of the corpus.

    Not a toy. It reproduces the specific failure that matters - an approximate index visits a
    limited number of partitions, so it can miss a true neighbour that lives in a partition it
    did not visit. That is how two identical runs return different passages.

    Used to measure the exact-versus-approximate delta without needing a live database, and to
    prove in tests that the delta detector actually detects something.
    """

    def __init__(
        self,
        chunks: Sequence[Chunk],
        embedder: Embedder,
        probes: int = 2,
        partitions: int = 8,
    ) -> None:
        if probes < 1 or partitions < 1:
            raise ValueError("probes and partitions must be positive")
        self._exact = ExactRetriever(chunks, embedder)
        self._embedder = embedder
        self.probes = probes
        self.partitions = partitions
        # Deterministic partition assignment, so this stand-in is itself reproducible; real
        # ivfflat nondeterminism comes from concurrent index state, which is not what we are
        # modelling here.
        self._partition_of: Dict[str, int] = {
            chunk.chunk_id: hash_to_partition(chunk.chunk_id, partitions)
            for chunk in chunks
        }

    def search(self, query: str, k: int = 4) -> List[Hit]:
        query_vector = self._embedder.embed(query)
        # Visit only the partitions closest to the query, by the same cheap hash.
        centre = hash_to_partition(query, self.partitions)
        visited = {(centre + offset) % self.partitions for offset in range(self.probes)}

        candidates = [
            chunk
            for chunk in self._exact._chunks
            if self._partition_of[chunk.chunk_id] in visited
        ]
        if not candidates:
            return []

        scored = [(cosine_similarity(query_vector, c.embedding), c) for c in candidates]
        scored.sort(key=lambda pair: (-pair[0], pair[1].chunk_id))
        return [
            Hit(chunk=chunk, score=score, rank=rank)
            for rank, (score, chunk) in enumerate(scored[:k])
        ]


def hash_to_partition(text: str, partitions: int) -> int:
    """Stable partition assignment. Python's hash() is salted per process, so it is unusable."""
    import hashlib

    digest = hashlib.blake2b(text.encode("utf-8"), digest_size=4).digest()
    return int.from_bytes(digest, "little") % partitions


# ---------------------------------------------------------------------------
# The exact-vs-approximate delta, as a measured quantity
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RetrievalDelta:
    """How much the approximate index disagrees with the truth.

    Section 15 of the architecture lists retrieval nondeterminism as a low-severity threat with
    "freeze retrieval" as the mitigation. Freezing removes it from the judging experiments, but
    it says nothing about how large it was. This turns it into a number, which is worth roughly
    an hour of work and converts a caveat into a finding.
    """

    n_queries: int
    k: int
    mean_overlap: float  # share of exact top-k also returned by the approximate index
    mean_rank_displacement: float  # average rank shift for chunks present in both
    exact_only: int  # true neighbours the approximate index missed entirely
    queries_with_any_miss: int

    @property
    def agreement_points(self) -> float:
        """Overlap expressed in percentage points, comparable to retrieval metric reporting."""
        return 100.0 * self.mean_overlap

    def to_dict(self) -> Dict[str, float]:
        return {
            "n_queries": self.n_queries,
            "k": self.k,
            "mean_overlap": self.mean_overlap,
            "agreement_points": self.agreement_points,
            "mean_rank_displacement": self.mean_rank_displacement,
            "exact_only": self.exact_only,
            "queries_with_any_miss": self.queries_with_any_miss,
        }


def measure_retrieval_delta(
    queries: Sequence[str],
    exact: ExactRetriever,
    approximate: ApproximateRetriever,
    k: int = 4,
) -> RetrievalDelta:
    """Compare an approximate index against exact search on the same queries."""
    if not queries:
        raise ValueError("need at least one query to measure a delta")

    overlaps: List[float] = []
    displacements: List[float] = []
    exact_only = 0
    queries_with_miss = 0

    for query in queries:
        exact_hits = exact.search(query, k)
        approximate_hits = approximate.search(query, k)

        exact_ids = [h.chunk.chunk_id for h in exact_hits]
        approximate_ranks = {h.chunk.chunk_id: h.rank for h in approximate_hits}

        shared = [cid for cid in exact_ids if cid in approximate_ranks]
        missed = len(exact_ids) - len(shared)
        exact_only += missed
        if missed:
            queries_with_miss += 1

        overlaps.append(len(shared) / len(exact_ids) if exact_ids else 1.0)
        for rank, cid in enumerate(exact_ids):
            if cid in approximate_ranks:
                displacements.append(abs(rank - approximate_ranks[cid]))

    return RetrievalDelta(
        n_queries=len(queries),
        k=k,
        mean_overlap=sum(overlaps) / len(overlaps),
        mean_rank_displacement=(
            sum(displacements) / len(displacements) if displacements else 0.0
        ),
        exact_only=exact_only,
        queries_with_any_miss=queries_with_miss,
    )


# ---------------------------------------------------------------------------
# A deterministic embedder for tests and rehearsals
# ---------------------------------------------------------------------------
class HashingEmbedder:
    """Network-free embedder: a hashed bag of words, L2-normalised.

    Not semantically meaningful, and not meant to be. Its job is to be *deterministic* and to
    give texts that share vocabulary a higher cosine similarity than texts that do not, which is
    enough to exercise every retrieval code path without a provider or a key (invariant 3).
    """

    def __init__(self, dimension: int = 64) -> None:
        if dimension < 2:
            raise ValueError("dimension must be at least 2")
        self.dimension = dimension

    def embed(self, text: str) -> Tuple[float, ...]:
        import hashlib
        import re

        vector = [0.0] * self.dimension
        for word in re.findall(r"[a-z0-9]+", text.lower()):
            digest = hashlib.blake2b(word.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "little") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0.0:
            # Empty or punctuation-only text. A fixed unit vector keeps cosine defined.
            return tuple([1.0] + [0.0] * (self.dimension - 1))
        return tuple(v / norm for v in vector)
