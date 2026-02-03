"""
pgvector-backed vector store for RAG. Replaces ChromaDB with a single Postgres table (rag_chunks).
"""
import hashlib
import json
import logging
import uuid
from typing import Any, Dict, List, Optional

import psycopg
from pgvector.psycopg import register_vector

try:
    from pgvector.psycopg import Vector
except ImportError:
    from pgvector import Vector  # type: ignore[attr-defined]

from managers.vector_store import VectorStoreBase


class DocLike:
    """LangChain-style document with page_content and metadata for RAG responses."""

    __slots__ = ("page_content", "metadata")

    def __init__(self, page_content: str, metadata: Dict[str, Any]):
        self.page_content = page_content
        self.metadata = metadata


def _filter_params(params: Dict[str, Optional[str]]) -> Dict[str, str]:
    """Filter out None/empty so psycopg.connect(**params) works."""
    return {k: str(v) for k, v in params.items() if v is not None and v != ""}


def _strip_nul(s: str) -> str:
    """Remove NUL bytes; PostgreSQL TEXT cannot contain them."""
    if not isinstance(s, str):
        return s
    return s.replace("\x00", "")


def _strip_nul_meta(val: Any) -> Any:
    """Recursively strip NUL from string values in metadata (dict/list/str)."""
    if isinstance(val, dict):
        return {k: _strip_nul_meta(v) for k, v in val.items()}
    if isinstance(val, list):
        return [_strip_nul_meta(v) for v in val]
    if isinstance(val, str):
        return _strip_nul(val)
    return val


class PgVectorStore(VectorStoreBase):
    """Vector store using PostgreSQL pgvector. Uses same DB as messages (DB_PARAMS)."""

    def __init__(
        self,
        db_params: Optional[Dict[str, Optional[str]]] = None,
        db_url: Optional[str] = None,
        embedding_function: Optional[Any] = None,
    ):
        if not db_params and not db_url:
            raise ValueError("Provide either db_params or db_url")
        self._db_params = db_params
        self._db_url = db_url
        self._embedding_function = embedding_function
        logging.info("PgVectorStore initialized (pgvector backend)")

    def _connect(self):
        if self._db_url:
            conn = psycopg.connect(self._db_url)
        else:
            conn = psycopg.connect(**_filter_params(self._db_params or {}))
        register_vector(conn)
        return conn

    def similarity_search(self, query: str, k: int = 4, locale: str = "en") -> List[Any]:
        if not self._embedding_function:
            raise ValueError("embedding_function required for similarity_search")
        embedding = self._embedding_function.embed_query(query)
        if not embedding:
            return []
        # Ensure list and wrap in Vector so psycopg sends as vector type (not double precision[])
        embedding = Vector(list(embedding))

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT content, metadata
                    FROM rag_chunks
                    WHERE locale = %s
                    ORDER BY embedding <=> %s
                    LIMIT %s;
                    """,
                    (locale, embedding, k),
                )
                rows = cur.fetchall()

        return [
            DocLike(
                page_content=row[0] or "",
                metadata=dict(row[1]) if row[1] else {},
            )
            for row in rows
        ]

    def add_documents(self, documents: List[Any], locale: str = "en") -> None:
        if not documents:
            return
        if not self._embedding_function:
            raise ValueError("embedding_function required for add_documents")

        texts = [getattr(d, "page_content", str(d)) for d in documents]
        embeddings = self._embedding_function.embed_documents(texts)

        with self._connect() as conn:
            with conn.cursor() as cur:
                for i, (doc, embedding) in enumerate(zip(documents, embeddings)):
                    meta = getattr(doc, "metadata", {}) or {}
                    # Ensure JSON-serializable (e.g. for LangChain metadata)
                    meta_serializable = {k: v for k, v in meta.items() if isinstance(k, str)}
                    meta_serializable = json.loads(json.dumps(meta_serializable, default=str))
                    doc_id = meta.get("doc_id") or meta.get("source") or str(uuid.uuid4())
                    # Unique id per chunk (metadata "id" from LangChain is often same for all chunks from one doc)
                    chunk_id = hashlib.sha256(f"{doc_id}:{i}".encode()).hexdigest()
                    content = getattr(doc, "page_content", str(doc))
                    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
                    cur.execute(
                        """
                        INSERT INTO rag_chunks (id, doc_id, chunk_index, content, embedding, metadata, content_hash, locale)
                        VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                        ON CONFLICT (id)
                        DO UPDATE SET
                            content = EXCLUDED.content,
                            embedding = EXCLUDED.embedding,
                            metadata = EXCLUDED.metadata,
                            content_hash = EXCLUDED.content_hash;
                        """,
                        (
                            chunk_id,
                            doc_id,
                            i,
                            content,
                            embedding,
                            json.dumps(meta_serializable),
                            content_hash,
                            locale,
                        ),
                    )
            conn.commit()
        logging.info("PgVectorStore: added %s chunks for locale=%s", len(documents), locale)

    def upsert_batch(
        self,
        ids: List[str],
        doc_ids: List[str],
        chunk_indices: List[int],
        contents: List[str],
        embeddings: List[List[float]],
        metadatas: List[Dict[str, Any]],
        content_hashes: List[str],
        locale: str,
    ) -> None:
        """Insert or update chunks with precomputed embeddings (e.g. for Chroma migration)."""
        if not (ids and len(ids) == len(doc_ids) == len(chunk_indices) == len(contents) == len(embeddings) == len(metadatas) == len(content_hashes)):
            raise ValueError("All lists must be non-empty and same length")
        locale_clean = _strip_nul(str(locale))
        with self._connect() as conn:
            with conn.cursor() as cur:
                for i, id_, doc_id, cidx, content, emb, meta, ch in zip(
                    range(len(ids)), ids, doc_ids, chunk_indices, contents, embeddings, metadatas, content_hashes
                ):
                    id_ = _strip_nul(str(id_))
                    doc_id = _strip_nul(str(doc_id))
                    content = _strip_nul(content if isinstance(content, str) else str(content))
                    ch = _strip_nul(str(ch))
                    meta_ser = _strip_nul_meta(meta) if isinstance(meta, dict) else {}
                    meta_ser = json.loads(json.dumps(meta_ser, default=str))
                    cur.execute(
                        """
                        INSERT INTO rag_chunks (id, doc_id, chunk_index, content, embedding, metadata, content_hash, locale)
                        VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                        ON CONFLICT (id)
                        DO UPDATE SET
                            content = EXCLUDED.content,
                            embedding = EXCLUDED.embedding,
                            metadata = EXCLUDED.metadata,
                            content_hash = EXCLUDED.content_hash;
                        """,
                        (id_, doc_id, cidx, content, emb, json.dumps(meta_ser), ch, locale_clean),
                    )
            conn.commit()
        logging.info("PgVectorStore: upserted %s chunks for locale=%s", len(ids), locale)
