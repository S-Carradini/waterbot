"""
RAG manager: wraps any VectorStoreBase and provides ann_search + knowledge_to_string + parse_source.
Used by FastAPI for /chat_api and /riverbot_chat_api.
"""
import asyncio
import logging
import re
import time
from typing import Any, List

from mappings.knowledge_sources import knowledge_sources

from managers.vector_store import VectorStoreBase


def parse_source(source: str) -> dict:
    """Map source path to filename, url, human_readable. Shared for any vector backend."""
    pattern = r'[\\/]+([^\\/]+\.pdf)$'
    match = re.search(pattern, source)
    if match:
        filename = match.group(1)
        mapping_entry = knowledge_sources.get(filename, {"url": "", "description": ""})
        return {
            "full_path": source,
            "filename": filename,
            "url": mapping_entry.get("url", ""),
            "human_readable": mapping_entry.get("description", filename),
        }
    logging.warning("Could not parse source path: %s", source)
    return {"full_path": source, "filename": "", "url": "", "human_readable": ""}


class RAGManager:
    """Wraps a VectorStoreBase and exposes ann_search() and knowledge_to_string() for the app."""

    def __init__(self, store: VectorStoreBase):
        self._store = store

    def parse_source(self, source: str) -> dict:
        return parse_source(source)

    async def ann_search(self, user_query: str, k: int = 4, locale: str = "en") -> dict:
        logging.info("Starting RAG similarity search (locale=%s)", locale)
        logging.info("   Query: '%s%s'", user_query[:100], "..." if len(user_query) > 100 else "")
        start_time = time.time()

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        try:
            docs = await loop.run_in_executor(
                None,
                lambda: self._store.similarity_search(user_query, k=k, locale=locale),
            )
        except Exception as e:
            logging.error("Vector store similarity_search failed: %s", e, exc_info=True)
            return {"documents": [], "sources": []}

        elapsed = time.time() - start_time
        logging.info("Similarity search completed in %.3fs, retrieved %s document(s)", elapsed, len(docs))

        if not docs:
            logging.warning("No documents found for query")
            return {"documents": [], "sources": []}

        for i, doc in enumerate(docs, 1):
            source = getattr(doc, "metadata", {}).get("source", "unknown")
            name = getattr(doc, "metadata", {}).get("name", "unknown")
            content_preview = (getattr(doc, "page_content", "") or "")[:100]
            logging.debug("   %s. Source: %s | Path: %s | Content: %s...", i, name, source, content_preview)

        sources = [getattr(doc, "metadata", {}).get("source", "") for doc in docs if getattr(doc, "metadata", {}).get("source")]
        unique_sources = list(set(sources))
        sources_parsed = [self.parse_source(s) for s in unique_sources]

        return {"documents": docs, "sources": sources_parsed}

    async def knowledge_to_string(self, docs: dict, doc_field: str = "documents") -> str:
        target = docs.get(doc_field, [])
        if not target:
            logging.warning("No documents in field '%s' to convert to string", doc_field)
            return ""
        content_parts = []
        for i, doc in enumerate(target, 1):
            if hasattr(doc, "page_content"):
                content_parts.append(doc.page_content)
            else:
                logging.warning("Document %s missing page_content", i)
        result = " ".join(content_parts)
        logging.info("Knowledge string created: %s characters from %s document(s)", len(result), len(content_parts))
        return result
