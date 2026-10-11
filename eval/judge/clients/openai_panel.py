"""OpenAI client for the L2 judge panel.

Distinct from ``openai_client.OpenAIJudgeClient``, which adapts the *old* binary refusal judge
for M1 and only needs to expose ``.client`` and ``.model_id``. The panel needs the
``JudgeClient`` protocol from ``panel.py``: a ``complete()`` that takes a system and user prompt
plus a JSON schema, and returns a ``Completion`` carrying the text and the token counts.

Until this existed the panel had exactly one implementation, ``FakeClient``, so every one of the
997 tests exercised the machinery and none of them exercised a real model. That is why no panel
score existed.

CONSTRAINED DECODING, NOT PROMPTED FORMATTING. The schema is handed to the provider through
``response_format`` so the shape is enforced by the decoder rather than requested politely in the
prompt. A judge that returns prose where a score was expected is a parse failure this project
counts as a hard failure, and prompting alone produces them at a rate that would pollute the
repair-rate statistic.

Network-touching, and therefore confined to ``clients/`` per the package invariant. The ``openai``
import is deferred to construction so this module stays importable without the SDK.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from eval.judge.panel import Completion

# Pinned snapshot, per invariant 6. An alias silently repoints under you, which turns a
# judge-stability measurement into a model-migration measurement. This is the same snapshot M1
# used, so panel verdicts and M1's binary verdicts are attributable to one model.
DEFAULT_PANEL_MODEL = "gpt-4.1-2025-04-14"

# The API contract is NOT uniform across these models, and both differences are silent hazards.
# Measured by probe on 2026-09-05 (`model_probe.json`):
#
#   model                  token parameter          temperature=0
#   gpt-4.1-2025-04-14     max_tokens               accepted
#   gpt-5.2-2025-12-11     max_completion_tokens    accepted
#   gpt-5.4-2026-03-05     max_completion_tokens    accepted
#   gpt-5-2025-08-07       max_completion_tokens    REJECTED
#   gpt-5.5-2026-04-23     max_completion_tokens    REJECTED
#
# Sending `max_tokens` to a gpt-5 model is a hard error, so that one surfaces immediately.
# Temperature is the dangerous one: a panel silently running some judges at the provider default
# while `MeasurementVersion.temperature` records 0.0 would attribute vendor-default sampling to a
# T=0 measurement. Hence `supports_temperature=False` REFUSES rather than dropping the argument.
# Stated as "which models still take the OLD parameter", not "which take the new one", so a
# model released after this was written defaults to the current contract rather than the legacy
# one. Guessing wrong in this direction produces an immediate hard error; guessing wrong the
# other way would too, but only after someone adds a model and wonders why nothing runs.
_LEGACY_MAX_TOKENS_MODELS = ("gpt-4", "gpt-3", "o1", "o3", "o4")

# Models that reject `temperature` outright. Probed, not assumed - see the table above.
_NO_TEMPERATURE_MODELS = ("gpt-5-", "gpt-5.5", "gpt-5.6", "gpt-6")


def _token_param_for(model_id: str) -> str:
    return ("max_tokens" if model_id.startswith(_LEGACY_MAX_TOKENS_MODELS)
            else "max_completion_tokens")


def _supports_temperature(model_id: str) -> bool:
    return not model_id.startswith(_NO_TEMPERATURE_MODELS)

# OpenAI requires every property to be listed in `required` and `additionalProperties: false`
# throughout when strict structured output is on. `verdict_json_schema` already satisfies both,
# so strict mode is safe to request and is what makes the shape a guarantee rather than a hope.
_STRICT = True


class OpenAIPanelClient:
    """One OpenAI judge behind the panel's ``JudgeClient`` protocol."""

    def __init__(
        self,
        model_id: str = DEFAULT_PANEL_MODEL,
        api_key: Optional[str] = None,
        *,
        timeout: float = 90.0,
        max_retries: int = 2,
        token_param: Optional[str] = None,
        supports_temperature: Optional[bool] = None,
    ) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(
                "The 'openai' package is not installed, so the live panel cannot run. "
                "Install it, or use FakeClient."
            ) from exc

        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set, so the live panel cannot run. "
                "Set it, or use FakeClient."
            )

        self.model_id = model_id
        self.token_param = token_param or _token_param_for(model_id)
        self.supports_temperature = (
            _supports_temperature(model_id) if supports_temperature is None
            else supports_temperature
        )
        self._client: Any = OpenAI(api_key=key, timeout=timeout, max_retries=max_retries)

    def complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float,
        max_tokens: int,
        schema: Optional[Dict[str, Any]] = None,
    ) -> Completion:
        if not self.supports_temperature and temperature != 0.0:
            raise RuntimeError(
                f"{self.model_id} does not accept a temperature, but the panel asked for "
                f"{temperature}. Dropping it would run this judge at the provider default while "
                f"MeasurementVersion recorded {temperature}, so the run is refused instead. Use a "
                f"model that accepts temperature, or configure the panel for this one explicitly."
            )

        kwargs: Dict[str, Any] = {
            "model": self.model_id,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            self.token_param: max_tokens,
        }
        if self.supports_temperature:
            kwargs["temperature"] = temperature
        if schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "verdict", "strict": _STRICT, "schema": schema},
            }

        response = self._client.chat.completions.create(**kwargs)

        text = response.choices[0].message.content or ""
        usage = getattr(response, "usage", None)
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)

        # Prompt caching is billed at a lower rate, so the cost model needs the cached count
        # separately rather than folded into prompt_tokens. Absent on older SDKs; treated as
        # zero rather than guessed.
        cached = 0
        details = getattr(usage, "prompt_tokens_details", None)
        if details is not None:
            cached = int(getattr(details, "cached_tokens", 0) or 0)

        return Completion(
            text=text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cached,
        )
