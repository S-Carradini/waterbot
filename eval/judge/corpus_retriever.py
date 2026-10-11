"""Exact k-NN retrieval straight out of pgvector, for the L1 freeze.

`retrieval.ExactRetriever` does brute-force cosine over an in-memory chunk set, which is the
right shape for tests but not for this corpus: 32,000 chunks at 1,536 dimensions is roughly a
gigabyte once Python boxes the floats. The database can do the same exhaustive search in place.

EXACT, NOT APPROXIMATE. `SET LOCAL enable_indexscan = off` forces a sequential scan, so the
ivfflat index is bypassed and the true nearest neighbours come back every time. That matters more
than it sounds: the index is `ivfflat lists=50` at the default `probes=1`, so it reads one
partition of fifty and can miss true neighbours. The frozen set is the artefact every later
result is traced back to, so it gets the exhaustive answer.

Satisfies the `search(question, k) -> Sequence[Hit]` contract that `freeze.freeze_responses`
calls, so it drops in wherever `ExactRetriever` was expected.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Protocol, Sequence

from eval.judge.retrieval import Chunk, Hit


class Embedder(Protocol):
    def embed(self, text: str) -> Sequence[float]: ...


@dataclass
class OpenAIEmbedder:
    """Adapter onto langchain's OpenAIEmbeddings, matching the `Embedder` protocol.

    Uses the same embedding model the application uses, because a frozen set retrieved with a
    different embedder is not the corpus the system under test actually searches.
    """

    _inner: Any = None

    def __post_init__(self) -> None:
        if self._inner is None:
            from langchain_openai import OpenAIEmbeddings

            self._inner = OpenAIEmbeddings()

    @property
    def model(self) -> str:
        return getattr(self._inner, "model", "unknown")

    def embed(self, text: str) -> Sequence[float]:
        return self._inner.embed_query(text)


class PgVectorExactRetriever:
    """Exhaustive cosine k-NN against a pgvector table."""

    def __init__(
        self,
        db_url: str,
        embedder: Embedder,
        locale: str = "en",
        table: str = "rag_chunks",
    ) -> None:
        self._db_url = db_url
        self._embedder = embedder
        self._locale = locale
        self._table = table
        self._conn = None

    def _connection(self):
        import psycopg

        if self._conn is None or self._conn.closed:
            self._conn = psycopg.connect(self._db_url)
        return self._conn

    def close(self) -> None:
        if self._conn is not None and not self._conn.closed:
            self._conn.close()

    def search(self, question: str, k: int = 4) -> List[Hit]:
        vector = list(self._embedder.embed(question))
        literal = "[" + ",".join(repr(float(x)) for x in vector) + "]"

        conn = self._connection()
        with conn.cursor() as cur:
            # LOCAL so the setting dies with the transaction and cannot leak into another query.
            cur.execute("SET LOCAL enable_indexscan = off;")
            cur.execute("SET LOCAL enable_bitmapscan = off;")
            cur.execute(
                f"""
                SELECT
                    COALESCE(metadata->>'name', metadata->>'source', 'unknown') AS doc,
                    id::text,
                    content,
                    1 - (embedding <=> %s::vector) AS score,
                    embedding::text
                FROM {self._table}
                WHERE locale = %s AND embedding IS NOT NULL
                ORDER BY embedding <=> %s::vector
                LIMIT %s;
                """,
                (literal, self._locale, literal, k),
            )
            rows = cur.fetchall()
        conn.rollback()  # end the transaction so SET LOCAL is discarded

        hits: List[Hit] = []
        for rank, (doc, chunk_id, content, score, embedding_text) in enumerate(rows):
            # `Chunk` requires a real embedding, and only the k retrieved chunks are
            # materialised here - not the corpus - so the cost is four vectors per question.
            embedding = tuple(
                float(x) for x in (embedding_text or "[]").strip("[]").split(",") if x.strip()
            )
            hits.append(
                Hit(
                    chunk=Chunk(
                        chunk_id=chunk_id,
                        canonical_doc_id=doc,
                        text=content or "",
                        embedding=embedding,
                    ),
                    score=float(score),
                    rank=rank,
                )
            )
        return hits


def corpus_fingerprint_for(db_url: str, table: str = "rag_chunks") -> str:
    """A fingerprint of what is actually in this database, right now.

    Deliberately computed from the corpus rather than passed in. A frozen run whose fingerprint
    was asserted by its caller can silently claim to be something it is not, and invariant 1
    exists to stop exactly that.

    Covers the distinct document set and the chunk content hashes. It does NOT cover the chunker
    or embedding configuration, which the architecture's fingerprint does - so this is a corpus
    identity, and any run that changes chunking must not reuse it.
    """
    import hashlib

    import psycopg

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                WITH doc AS (
                    SELECT COALESCE(metadata->>'name', 'unknown') AS name, content_hash
                    FROM {table}
                    WHERE content_hash IS NOT NULL
                    GROUP BY 1, 2
                ),
                sig AS (
                    SELECT name, md5(string_agg(content_hash, ',' ORDER BY content_hash)) AS fp
                    FROM doc GROUP BY 1
                )
                SELECT md5(string_agg(DISTINCT fp, ',' ORDER BY fp)), count(DISTINCT fp)
                FROM sig;
                """
            )
            digest, n_documents = cur.fetchone()
    short = hashlib.sha256((digest or "").encode()).hexdigest()[:16]
    return f"{short}"
