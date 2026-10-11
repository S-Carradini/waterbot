"""The Hugging Face judge client's request shaping and structured-output modes.

No network. The OpenAI SDK is never constructed; a stub captures the kwargs the client would
have sent.

The mode logic matters more here than on the OpenAI path. `decisions.md` 009 chose constrained
decoding over prompted JSON because a judge returning prose where a score was expected is a hard
failure this project counts, and prompting alone produces those often enough to pollute the
repair-rate statistic. Hugging Face support depends on the serving provider, so the client
degrades through declared modes - and which mode was used has to be visible, never inferred.
"""
from __future__ import annotations

import json

import pytest

from eval.judge.clients.huggingface_panel import (ALTERNATES, DEFAULT_BASE_URL, PHI_4,
                                                  LLAMA_4_SCOUT, STRUCTURED_MODES,
                                                  HuggingFacePanelClient, _strip_code_fence)

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["rationale", "score"],
    "properties": {
        "rationale": {"type": "string"},
        "score": {"type": ["integer", "null"], "enum": [1, 2, 3, 4, None]},
    },
}


class StubCompletions:
    def __init__(self, content='{"ok": true}'):
        self.last_kwargs = None
        self._content = content

    def create(self, **kwargs):
        self.last_kwargs = kwargs

        class Msg:
            content = self._content

        class Choice:
            message = Msg()

        class Usage:
            prompt_tokens = 120
            completion_tokens = 40
            prompt_tokens_details = None

        class Resp:
            choices = [Choice()]
            usage = Usage()

        return Resp()


def a_client(model_id=LLAMA_4_SCOUT, mode="json_object", content='{"ok": true}'):
    client = HuggingFacePanelClient.__new__(HuggingFacePanelClient)
    client.model_id = model_id
    client.structured_mode = mode
    client.base_url = DEFAULT_BASE_URL
    stub = StubCompletions(content)

    class Chat:
        completions = stub

    class Raw:
        chat = Chat()

    client._client = Raw()
    return client, stub


# ---------------------------------------------------------------------------
# Structured output modes
# ---------------------------------------------------------------------------
def test_json_schema_mode_sends_a_strict_schema():
    client, stub = a_client(mode="json_schema")
    client.complete("sys", "user", temperature=0.0, max_tokens=900, schema=SCHEMA)
    fmt = stub.last_kwargs["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["strict"] is True
    assert fmt["json_schema"]["schema"] is SCHEMA


def test_json_object_mode_asks_for_json_without_the_schema():
    """Guarantees parseable JSON; the validator enforces shape."""
    client, stub = a_client(mode="json_object")
    client.complete("sys", "user", temperature=0.0, max_tokens=900, schema=SCHEMA)
    assert stub.last_kwargs["response_format"] == {"type": "json_object"}


def test_prompted_mode_puts_the_schema_in_the_user_message():
    """The weakest mode: nothing is enforced, so the schema has to be described."""
    client, stub = a_client(mode="prompted")
    client.complete("sys", "the question", temperature=0.0, max_tokens=900, schema=SCHEMA)
    assert "response_format" not in stub.last_kwargs
    sent = stub.last_kwargs["messages"][1]["content"]
    assert "[OUTPUT FORMAT]" in sent
    assert json.dumps(SCHEMA, indent=2) in sent
    assert sent.startswith("the question")


def test_no_schema_means_no_response_format_in_any_mode():
    for mode in STRUCTURED_MODES:
        client, stub = a_client(mode=mode)
        client.complete("sys", "user", temperature=0.0, max_tokens=900)
        assert "response_format" not in stub.last_kwargs, mode


def test_an_unknown_structured_mode_is_refused():
    """Silently falling back would leave half a panel schema-enforced and half not."""
    with pytest.raises(ValueError, match="unknown structured_mode"):
        HuggingFacePanelClient(model_id=LLAMA_4_SCOUT, api_key="x", structured_mode="vibes")


# ---------------------------------------------------------------------------
# Request shaping
# ---------------------------------------------------------------------------
def test_temperature_and_max_tokens_are_sent():
    client, stub = a_client()
    client.complete("sys", "user", temperature=0.0, max_tokens=4000)
    assert stub.last_kwargs["temperature"] == 0.0
    assert stub.last_kwargs["max_tokens"] == 4000
    assert stub.last_kwargs["model"] == LLAMA_4_SCOUT


def test_system_and_user_messages_are_kept_separate():
    client, stub = a_client()
    client.complete("SYSTEM TEXT", "USER TEXT", temperature=0.0, max_tokens=100)
    messages = stub.last_kwargs["messages"]
    assert messages[0] == {"role": "system", "content": "SYSTEM TEXT"}
    assert messages[1] == {"role": "user", "content": "USER TEXT"}


def test_token_counts_come_back_on_the_completion():
    client, _ = a_client()
    completion = client.complete("sys", "user", temperature=0.0, max_tokens=100)
    assert completion.prompt_tokens == 120
    assert completion.completion_tokens == 40
    assert completion.total_tokens == 160


# ---------------------------------------------------------------------------
# Fence stripping - open models wrap JSON in markdown far more often than OpenAI does
# ---------------------------------------------------------------------------
def test_a_fenced_response_is_unwrapped():
    client, _ = a_client(content='```json\n{"score": 4}\n```')
    completion = client.complete("sys", "user", temperature=0.0, max_tokens=100)
    assert completion.text == '{"score": 4}'


def test_an_unfenced_response_is_untouched():
    client, _ = a_client(content='{"score": 4}')
    completion = client.complete("sys", "user", temperature=0.0, max_tokens=100)
    assert completion.text == '{"score": 4}'


@pytest.mark.parametrize("raw,expected", [
    ('```\n{"a": 1}\n```', '{"a": 1}'),
    ('```json\n{"a": 1}', '{"a": 1}'),
    ('{"a": 1}', '{"a": 1}'),
    ('', ''),
    ('```', '```'),
])
def test_fence_stripping_cases(raw, expected):
    assert _strip_code_fence(raw) == expected


def test_stripping_never_touches_json_containing_backticks():
    payload = '{"rationale": "the response used ``` fences"}'
    assert _strip_code_fence(payload) == payload


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
def test_a_missing_token_is_refused_rather_than_silently_dropping_the_judge(monkeypatch):
    """A panel quietly reduced to one vendor is the exact drift decision 040 recorded."""
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGINGFACE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="HF_TOKEN is not set"):
        HuggingFacePanelClient(model_id=PHI_4)


def test_the_two_configured_models_are_named_constants():
    """So a typo in a config is caught against a single source of truth."""
    assert PHI_4 == "microsoft/phi-4"
    assert LLAMA_4_SCOUT == "meta-llama/Llama-4-Scout-17B-16E-Instruct"
    assert DEFAULT_BASE_URL.startswith("https://")


def test_no_judge_is_a_chinese_origin_model():
    """Owner decision, 2026-09-09, on data-integrity grounds. Pinned as a test so a future
    edit that reintroduces one fails loudly rather than passing review unnoticed."""
    import yaml

    excluded = ("deepseek", "qwen", "zai-org", "glm", "inclusionai", "ling-", "baidu",
                "01-ai", "thudm", "internlm", "moonshot", "minimax", "tencent", "baichuan")
    with open("configs/panel_qualitative.yaml", encoding="utf-8") as fh:
        config = yaml.safe_load(fh)
    for judge in config["panel"]["judges"]:
        low = judge["model_id"].lower()
        assert not any(x in low for x in excluded), f"excluded-origin judge: {judge['model_id']}"
    for alternate in ALTERNATES:
        low = alternate.lower()
        assert not any(x in low for x in excluded), f"excluded-origin alternate: {alternate}"


# test_the_panel_spans_more_than_one_model_family REMOVED on 2026-09-09, same day it was
# written. It guarded configs/panel_qualitative.yaml against collapsing to one vendor - and
# that is exactly what the owner then deliberately chose, after google/gemma-4-31B-it returned
# a 504 on the first live call and then, after the retry fix, sat idle for 6+ minutes with zero
# CPU movement and nothing written. The panel is OpenAI-only (gpt-4.1-2025-04-14,
# gpt-5.4-2026-03-05) by owner decision, not by accident, so a test asserting otherwise would
# be asserting something false about the current design rather than guarding against drift.
# Decision 040's single-vendor limitation is REOPENED, not fixed - see decisions.md.
