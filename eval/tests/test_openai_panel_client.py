"""The live panel client's per-model API routing.

No network. The OpenAI SDK is never constructed here - only the pure routing helpers and the
request-shaping logic are exercised, with a stub standing in for the SDK client.

The routing exists because the chat completions contract is not uniform across the models this
key can reach. Both differences are silent hazards if got wrong, and the temperature one is the
dangerous half: dropping an unsupported temperature would run a judge at the provider default
while `MeasurementVersion.temperature` recorded 0.0.

The expected values below were measured against the live API on 2026-09-05 and are recorded in
`model_probe.json`. If OpenAI changes a model's contract this test is what fails.
"""
from __future__ import annotations

import pytest

from eval.judge.clients.openai_panel import (
    DEFAULT_PANEL_MODEL,
    OpenAIPanelClient,
    _supports_temperature,
    _token_param_for,
)

# (model_id, expected token parameter, accepts temperature) - all probed live.
PROBED = [
    ("gpt-4.1-2025-04-14", "max_tokens", True),
    ("gpt-5.2-2025-12-11", "max_completion_tokens", True),
    ("gpt-5.4-2026-03-05", "max_completion_tokens", True),
    ("gpt-5-2025-08-07", "max_completion_tokens", False),
    ("gpt-5.5-2026-04-23", "max_completion_tokens", False),
]


class StubCompletions:
    """Captures the kwargs the client would have sent."""

    def __init__(self):
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs

        class Msg:
            content = '{"ok": true}'

        class Choice:
            message = Msg()

        class Usage:
            prompt_tokens = 11
            completion_tokens = 7
            prompt_tokens_details = None

        class Resp:
            choices = [Choice()]
            usage = Usage()

        return Resp()


def a_client(model_id: str) -> tuple:
    """Build a client without touching the network or the OpenAI SDK."""
    client = OpenAIPanelClient.__new__(OpenAIPanelClient)
    client.model_id = model_id
    client.token_param = _token_param_for(model_id)
    client.supports_temperature = _supports_temperature(model_id)
    stub = StubCompletions()

    class Chat:
        completions = stub

    class Raw:
        chat = Chat()

    client._client = Raw()
    return client, stub


# ---------------------------------------------------------------------------
# Routing matches what the live API actually accepts
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("model_id,token_param,accepts_temperature", PROBED)
def test_routing_matches_the_live_probe(model_id, token_param, accepts_temperature):
    assert _token_param_for(model_id) == token_param
    assert _supports_temperature(model_id) is accepts_temperature


def test_an_unknown_future_model_defaults_to_the_current_contract():
    """Legacy is the enumerated case, so a new model gets the modern parameter, not the old one."""
    assert _token_param_for("gpt-7-something-2027-01-01") == "max_completion_tokens"
    assert _token_param_for("gpt-6-astra") == "max_completion_tokens"


def test_the_default_model_is_a_pinned_snapshot():
    """Invariant 6. An alias repoints under you and turns stability into model migration."""
    assert DEFAULT_PANEL_MODEL == "gpt-4.1-2025-04-14"
    tail = DEFAULT_PANEL_MODEL.rsplit("-", 3)[-3:]
    assert all(part.isdigit() for part in tail), "default model id carries no date snapshot"


# ---------------------------------------------------------------------------
# Request shaping
# ---------------------------------------------------------------------------
def test_a_legacy_model_is_sent_max_tokens_and_a_temperature():
    client, stub = a_client("gpt-4.1-2025-04-14")
    client.complete("sys", "user", temperature=0.0, max_tokens=1500)
    assert stub.last_kwargs["max_tokens"] == 1500
    assert "max_completion_tokens" not in stub.last_kwargs
    assert stub.last_kwargs["temperature"] == 0.0


def test_a_modern_model_is_sent_max_completion_tokens():
    client, stub = a_client("gpt-5.2-2025-12-11")
    client.complete("sys", "user", temperature=0.0, max_tokens=1500)
    assert stub.last_kwargs["max_completion_tokens"] == 1500
    assert "max_tokens" not in stub.last_kwargs


def test_a_model_without_temperature_support_is_sent_none_at_zero():
    """T=0 is the panel default and means 'no sampling', which is what these models do anyway."""
    client, stub = a_client("gpt-5.5-2026-04-23")
    client.complete("sys", "user", temperature=0.0, max_tokens=800)
    assert "temperature" not in stub.last_kwargs
    assert stub.last_kwargs["max_completion_tokens"] == 800


def test_a_nonzero_temperature_on_an_unsupporting_model_is_refused():
    """The dangerous case. Silently dropping it would attribute provider-default sampling to a
    run whose MeasurementVersion records the temperature that was asked for."""
    client, _ = a_client("gpt-5.5-2026-04-23")
    with pytest.raises(RuntimeError, match="does not accept a temperature"):
        client.complete("sys", "user", temperature=0.3, max_tokens=800)


def test_the_schema_is_sent_as_strict_structured_output():
    client, stub = a_client("gpt-4.1-2025-04-14")
    schema = {"type": "object", "properties": {}}
    client.complete("sys", "user", temperature=0.0, max_tokens=100, schema=schema)
    fmt = stub.last_kwargs["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["strict"] is True
    assert fmt["json_schema"]["schema"] is schema


def test_no_response_format_is_sent_when_no_schema_is_given():
    client, stub = a_client("gpt-4.1-2025-04-14")
    client.complete("sys", "user", temperature=0.0, max_tokens=100)
    assert "response_format" not in stub.last_kwargs


def test_token_counts_come_back_on_the_completion():
    client, _ = a_client("gpt-4.1-2025-04-14")
    completion = client.complete("sys", "user", temperature=0.0, max_tokens=100)
    assert completion.prompt_tokens == 11
    assert completion.completion_tokens == 7
    assert completion.cached_tokens == 0
    assert completion.total_tokens == 18


def test_overrides_beat_the_automatic_routing():
    """An escape hatch for a model whose contract changes before this table is updated."""
    client = OpenAIPanelClient.__new__(OpenAIPanelClient)
    client.model_id = "gpt-4.1-2025-04-14"
    client.token_param = "max_completion_tokens"
    client.supports_temperature = False
    stub = StubCompletions()

    class Chat:
        completions = stub

    class Raw:
        chat = Chat()

    client._client = Raw()
    client.complete("sys", "user", temperature=0.0, max_tokens=42)
    assert stub.last_kwargs["max_completion_tokens"] == 42
    assert "temperature" not in stub.last_kwargs
