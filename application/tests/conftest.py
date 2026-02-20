"""
Pytest fixtures for WaterBot API tests.

Patches all external I/O (OpenAI, psycopg2, boto3/Bedrock) before the app
module is imported so the FastAPI startup hooks don't touch real infrastructure.
"""
import json
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient


# ---------------------------------------------------------------------------
# Module-level stubs for heavy optional deps that may not be installed in CI
# ---------------------------------------------------------------------------
def _stub_module(name: str, **attrs):
    """Insert a lightweight stub into sys.modules."""
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules.setdefault(name, mod)


# Stub out langchain sub-packages so import succeeds without the real wheels
_stub_module("langchain")
_stub_module("langchain.embeddings")
_stub_module("langchain_openai", OpenAIEmbeddings=MagicMock)
_stub_module("langchain_community")
_stub_module("langchain_aws")
_stub_module("pgvector")
_stub_module("amazon_transcribe")
_stub_module("langdetect", detect=lambda t: "en", DetectorFactory=MagicMock())


# ---------------------------------------------------------------------------
# Shared mock factories
# ---------------------------------------------------------------------------
def _make_llm_adapter():
    """Return an async-capable mock that satisfies OpenAIAdapter's interface."""
    adapter = MagicMock()
    adapter.get_embeddings.return_value = MagicMock()
    adapter.safety_checks = AsyncMock(
        return_value=(False, json.dumps({"user_intent": 0, "prompt_injection": 0, "unrelated_topic": 0}))
    )
    adapter.get_llm_body = AsyncMock(return_value=json.dumps({"messages": [], "temperature": 0.5}))
    adapter.generate_response = AsyncMock(return_value="This is a test answer.")
    return adapter


def _make_knowledge_base():
    """Return an async-capable mock that satisfies BedrockKnowledgeBase / RAGManager interface."""
    kb = MagicMock()
    kb.ann_search = AsyncMock(return_value={"documents": ["doc1"], "sources": []})
    kb.knowledge_to_string = AsyncMock(return_value="Some knowledge content.")
    return kb


# ---------------------------------------------------------------------------
# App fixture — patches everything before importing main
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def app():
    """
    Build and return the FastAPI app with all external calls mocked.
    Scope is 'session' so the app is constructed only once per test run.
    """
    mock_adapter = _make_llm_adapter()
    mock_kb = _make_knowledge_base()

    # Patch psycopg2 so DB connections never happen
    mock_psycopg2 = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []
    mock_conn.cursor.return_value = mock_cursor
    mock_psycopg2.connect.return_value = mock_conn
    mock_psycopg2.OperationalError = Exception
    mock_psycopg2.ProgrammingError = Exception
    mock_psycopg2.extras = MagicMock()
    mock_psycopg2.extras.DictCursor = MagicMock()
    mock_psycopg2.extras.execute_values = MagicMock()

    patches = [
        patch("psycopg2.connect", mock_psycopg2.connect),
        patch("psycopg2.extras.execute_values", mock_psycopg2.extras.execute_values),
        # Prevent boto3 session creation
        patch("boto3.Session", MagicMock()),
        patch("boto3.client", MagicMock()),
    ]

    for p in patches:
        p.start()

    # Now safe to import main
    import importlib
    import os

    os.environ.setdefault("OPENAI_API_KEY", "test-key")
    os.environ.setdefault("AWS_KB_ID", "test-kb-id")  # skip pgvector path

    # Import (or reload) the module so patches are in effect
    if "main" in sys.modules:
        importlib.reload(sys.modules["main"])
    else:
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))
        import main  # noqa: F401

    import main as main_module

    # Override the module-level singletons with mocks
    main_module.llm_adapter = mock_adapter
    main_module.knowledge_base = mock_kb

    yield main_module.app

    for p in patches:
        p.stop()


@pytest.fixture()
async def client(app):
    """Async HTTP client wired to the FastAPI app (no real network)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
