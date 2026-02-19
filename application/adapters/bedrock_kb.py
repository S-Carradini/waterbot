"""
Adapter for Amazon Bedrock Knowledge Bases using the RetrieveAndGenerate API.

Requires env vars:
  AWS_KB_ID            (e.g., "Z2NHZ8JMMQ")
  AWS_KB_MODEL_ARN     (optional; defaults to Claude 3 Sonnet in us-west-2)
  AWS_REGION           (defaults to us-west-2)

Returns a LangChain-ish payload with `text` and `sources` so the rest of the
app can treat it like a vector store result.
"""

import os
import boto3
from mappings.knowledge_sources import knowledge_sources

DEFAULT_MODEL_ARN = os.getenv(
    "AWS_KB_MODEL_ARN",
    "arn:aws:bedrock:us-west-2::foundation-model/anthropic.claude-3-sonnet-20240229-v1:0",
)


class BedrockKnowledgeBase:
    def __init__(self, kb_id: str, model_arn: str | None = None, region: str | None = None):
        if not kb_id:
            raise ValueError("kb_id is required for BedrockKnowledgeBase")
        self.kb_id = kb_id
        self.model_arn = model_arn or DEFAULT_MODEL_ARN
        self.region = region or os.getenv("AWS_REGION", "us-west-2")
        self.client = boto3.client("bedrock-agent-runtime", region_name=self.region)

    async def retrieve(self, user_query: str, session_id: str | None = None) -> dict:
        """Call RetrieveAndGenerate and normalize response to {text, sources, raw}."""
        payload = {
            "input": {"text": user_query},
            "retrieveAndGenerateConfiguration": {
                "type": "KNOWLEDGE_BASE",
                "knowledgeBaseConfiguration": {
                    "knowledgeBaseId": self.kb_id,
                    "modelArn": self.model_arn,
                },
            },
        }
        if session_id:
            payload["sessionConfiguration"] = {"sessionId": session_id}

        resp = self.client.retrieve_and_generate(**payload)

        output_text = resp.get("output", {}).get("text", "")
        citations = resp.get("citations", []) or []

        sources = []
        for citation in citations:
            for ref in citation.get("retrievedReferences", []) or []:
                location = ref.get("location", {}) or {}
                uri = (
                    location.get("s3Location", {}) or {}
                ).get("uri") or location.get("type", "")
                content = ref.get("content", {}) or {}
                text_excerpt = content.get("text", "")
                sources.append(
                    {
                        "human_readable": text_excerpt[:120] + ("..." if len(text_excerpt) > 120 else ""),
                        "url": uri or "",
                        "filename": os.path.basename(uri) if uri else "",
                        "full_path": uri or "",
                    }
                )

        return {
            "text": output_text,
            "sources": sources,
            "raw": resp,
        }

    async def ann_search(self, user_query: str, k: int = 4, locale: str = "en") -> dict:
        """
        Retrieve raw chunks from the Knowledge Base (no generation).
        Returns {"documents": [...], "sources": [...]} for the RAG pipeline.
        Uses the Retrieve API so the LLM adapter handles generation with full
        conversation history, avoiding double-invocation.
        """
        resp = self.client.retrieve(
            knowledgeBaseId=self.kb_id,
            retrievalQuery={"text": user_query},
            retrievalConfiguration={
                "vectorSearchConfiguration": {"numberOfResults": k}
            },
        )

        results = resp.get("retrievalResults", [])
        documents = []
        sources = []
        seen_uris: set = set()

        for result in results:
            content = (result.get("content") or {}).get("text", "")
            location = result.get("location") or {}
            uri = ((location.get("s3Location") or {}).get("uri")
                   or location.get("type", ""))

            doc = type("DocLike", (), {})()
            doc.page_content = content
            doc.metadata = {
                "source": uri,
                "name": os.path.basename(uri) if uri else "bedrock_kb",
            }
            documents.append(doc)

            if uri and uri not in seen_uris:
                seen_uris.add(uri)
                filename = os.path.basename(uri)
                mapping = knowledge_sources.get(filename, {})
                sources.append({
                    "full_path": uri,
                    "filename": filename,
                    "url": mapping.get("url", ""),
                    "human_readable": mapping.get("description", filename),
                })

        return {"documents": documents, "sources": sources}

    async def knowledge_to_string(self, docs: dict, doc_field: str = "documents") -> str:
        """
        For API parity with RAGManager: flatten the docs' text.
        """
        documents = docs.get(doc_field, [])
        if not documents:
            return ""
        parts = []
        for d in documents:
            text = getattr(d, "page_content", "") or ""
            if text:
                parts.append(text)
        return " ".join(parts)
