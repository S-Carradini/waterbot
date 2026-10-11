from abc import ABC, abstractmethod

class ModelAdapter(ABC):
    """Abstract interface for LLM providers.
    
    Why this exists: If the client later wants to switch from OpenAI
    to Anthropic/Google/local model, you only write a new adapter —
    nothing else in the codebase changes.
    """
    
    @abstractmethod
    async def generate(self, messages: list[dict], temperature: float = 0.7) -> str:
        """Send messages to LLM, get response text back."""
    
    @abstractmethod
    async def moderate(self, text: str) -> dict:
        """Check if text contains harmful content."""
    
    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Convert text to a vector embedding."""