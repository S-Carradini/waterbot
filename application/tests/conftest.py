"""
Pytest fixtures for WaterBot API tests.

Installs against the real requirements.txt dependencies; external I/O
(OpenAI, PostgreSQL) is prevented by env var config and by
overriding the module-level singletons after import.

POSTGRES_ENABLED is False (no DB env vars) → psycopg2.connect is never called.
"""
import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock

import dotenv
import pytest
from httpx import ASGITransport, AsyncClient

# main.py calls load_dotenv(override=True), which would pull a developer's real
# .env (production database URL, API keys) into the test process. Disable it
# before main is imported so tests never touch real services.
dotenv.load_dotenv = lambda *args, **kwargs: False

# Ensure env vars are set before main.py is imported
os.environ.setdefault("OPENAI_API_KEY", "test-key-not-real")
# The suite sends many requests from one test IP; rate-limit tests swap in strict limiters.
os.environ.setdefault("RATE_LIMIT_PER_SESSION", "100000")
os.environ.setdefault("RATE_LIMIT_PER_IP", "100000")
os.environ.setdefault("RATE_LIMIT_GLOBAL_PER_MINUTE", "100000")
os.environ.pop("ADMIN_USERNAME", None)
os.environ.pop("ADMIN_PASSWORD_HASH", None)
# No DATABASE_URL / DB_HOST → POSTGRES_ENABLED=False → psycopg2.connect never called
os.environ.pop("DATABASE_URL", None)
os.environ.pop("DB_HOST", None)
os.environ.pop("TRANSCRIPT_STORAGE_PATH", None)

# Add application/ dir to path so `import main` works from any working directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _make_llm_adapter():
    adapter = MagicMock()
    adapter.get_embeddings.return_value = MagicMock()
    adapter.safety_checks = AsyncMock(
        return_value=(
            False,
            json.dumps({"user_intent": 0, "prompt_injection": 0, "unrelated_topic": 0}),
        )
    )
    adapter.get_llm_body = AsyncMock(
        return_value=json.dumps({"messages": [], "temperature": 0.5})
    )
    adapter.generate_response = AsyncMock(return_value="Test answer from mock.")
    adapter.generate_blue = AsyncMock(return_value="Test answer from mock.")
    return adapter


class FakeGuard:
    """Stands in for guardrails.Guard: no network. Tests set .result to change the verdict."""

    def __init__(self):
        self.result = None
        self.calls = []

    async def screen(self, text, context=None):
        import guardrails
        self.calls.append((text, list(context or [])))
        if self.result is not None:
            return self.result
        return guardrails.ScreenResult(allowed=True, category="water")


def _make_knowledge_base():
    kb = MagicMock()
    kb.ann_search = AsyncMock(return_value={"documents": ["doc1"], "sources": []})
    kb.knowledge_to_string = AsyncMock(return_value="Mock knowledge content.")
    return kb


@pytest.fixture(scope="session")
def app():
    """
    Import the FastAPI app once per session with all external calls mocked.
    """
    import main as main_module

    main_module.llm_adapter = _make_llm_adapter()
    main_module.knowledge_base = _make_knowledge_base()
    main_module.guard = FakeGuard()

    yield main_module.app


@pytest.fixture(autouse=True)
def _reset_shared_fakes(app):
    """Reset the shared fakes before every test so no verdict leaks between tests."""
    import main
    main.guard.result = None
    main.guard.calls.clear()
    main.llm_adapter.generate_blue.reset_mock(return_value=True, side_effect=True)
    main.llm_adapter.generate_blue.return_value = "Test answer from mock."
    main.llm_adapter.safety_checks.reset_mock()
    yield


@pytest.fixture()
def main_module(app):
    import main
    return main


@pytest.fixture()
async def client(app):
    """Async HTTP client bound to the FastAPI app — no real network."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture()
async def session_client(app):
    """Client that already holds a server-issued, signed session (as after a page load)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        await ac.get("/chat")
        yield ac
