# application/adapters/openai_adapter.py
import asyncio
from openai import OpenAI
from adapters.base import ModelAdapter
from config import settings

class OpenAIAdapter(ModelAdapter):
    def __init__(self, model_id: str = "gpt-4.1"):
        self.client = OpenAI(api_key=settings.openai_api_key)
        self.model_id = model_id
        self.embedding_model = "text-embedding-ada-002"
    
    async def generate(self, messages: list[dict], temperature: float = 0.7) -> str:
        """Call GPT-4.1 to generate a response.
        
        `messages` looks like:
        [
            {"role": "system", "content": "You are a helpful bot..."},
            {"role": "user", "content": "What is drought?"},
            {"role": "assistant", "content": "Drought is..."},  ← history
            {"role": "user", "content": "Tell me more"}         ← current
        ]
        """
        # OpenAI's client is synchronous, so we run it in a thread
        # to avoid blocking the FastAPI async event loop
        response = await asyncio.to_thread(
            self.client.chat.completions.create,
            model=self.model_id,
            messages=messages,
            temperature=temperature,
            max_tokens=1024
        )
        return response.choices[0].message.content
    
    async def moderate(self, text: str) -> dict:
        """Check text against OpenAI's moderation API.
        
        Returns: {"flagged": bool, "categories": {...}}
        Used to block harmful/inappropriate user messages.
        """
        result = await asyncio.to_thread(
            self.client.moderations.create,
            input=text
        )
        return {
            "flagged": result.results[0].flagged,
            "categories": result.results[0].categories
        }
    
    async def embed(self, text: str) -> list[float]:
        """Convert text to a 1536-dimensional vector.
        
        This is the key to RAG — both user queries AND stored documents
        get embedded. Similar meaning = similar vectors = found by search.
        """
        response = await asyncio.to_thread(
            self.client.embeddings.create,
            model=self.embedding_model,
            input=text
        )
        return response.data[0].embedding  # list of 1536 floats

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple chunks of text in a single OpenAI API call.

        Used by the bulk ingestion script to cut down on API round trips
        versus calling embed() once per chunk. Order of the returned
        vectors matches the order of `texts`.
        """
        response = await asyncio.to_thread(
            self.client.embeddings.create,
            model=self.embedding_model,
            input=texts
        )
        return [item.embedding for item in response.data]