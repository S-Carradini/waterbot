"""
Abstract interface for RAG vector stores (pgvector, Chroma, etc.).
Implementations must return LangChain-style doc objects (page_content, metadata)
so parse_source and knowledge_to_string keep working.
"""
from abc import ABC, abstractmethod
from typing import Any, List


class VectorStoreBase(ABC):
    """Abstract base for vector stores used by RAG."""

    @abstractmethod
    def similarity_search(self, query: str, k: int = 4, locale: str = "en") -> List[Any]:
        """
        Return up to k documents most similar to the query for the given locale.
        Each item must have .page_content and .metadata (with 'source', 'name' etc.).
        """
        pass

    @abstractmethod
    def add_documents(self, documents: List[Any], locale: str = "en") -> None:
        """
        Ingest documents. Each document must have .page_content and .metadata.
        """
        pass
