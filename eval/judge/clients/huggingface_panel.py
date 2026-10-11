"""Hugging Face judge client for the L2 panel.

Talks to HF Inference Providers through its OpenAI-compatible router
(``https://router.huggingface.co/v1``), so it reuses the already-installed ``openai`` SDK
rather than adding a dependency. Same `JudgeClient` protocol as the OpenAI client: a
``complete()`` returning a ``Completion`` with text and token counts.

WHY THIS EXISTS. Until now the panel could only reach OpenAI, which made M7's requirement -
3+ judges spanning 3+ model FAMILIES - impossible, and forced decision 040 to record a
single-vendor panel as a stated limitation. Two Hugging Face models restore genuine family
diversity, which is the mechanism (error decorrelation) the panel design actually relies on.

STRUCTURED OUTPUT IS NOT GUARANTEED HERE, AND THAT IS A REAL DEVIATION.
`decisions.md` 009 chose constrained decoding over prompted JSON because a judge returning prose
where a score was expected is a hard failure this project counts, and prompting alone produces
those at a rate that pollutes the repair-rate statistic. OpenAI enforces the schema in the
decoder. On HF, support depends on the serving provider behind each model, so this client
degrades in a declared order and RECORDS which mode it used:

    json_schema  -> strict, equivalent to the OpenAI path
    json_object  -> valid JSON guaranteed, shape not enforced; the validator does the work
    prompted     -> nothing enforced; the schema is described in the prompt

`structured_mode` is explicit in the panel config, never silently inferred, because a run where
half the judges were schema-enforced and half were not is not one measurement. Whatever mode a
judge used belongs beside its verdicts in the write-up.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from eval.judge.panel import Completion

# HF Inference Providers, OpenAI-compatible surface.
DEFAULT_BASE_URL = "https://router.huggingface.co/v1"

# Repo ids confirmed SERVED by HF Inference Providers (Novita, +others) as of 2026-09-10 - not
# merely present as weights, which is a different thing and the reason several strong candidates
# were rejected (Llama-4-Maverick is downloadable but "not deployed by any Inference Provider").
#
# Chinese-origin models are excluded by owner decision on data-integrity grounds, so DeepSeek,
# Qwen, GLM and Ling are all out regardless of benchmark standing.
#
# Both probed on 2026-09-10 with the REAL qualitative prompt (10.9K-char system, 7.9K-char
# user, five-dimension verdict) and returned valid strict json_schema in ~8-10s.
LLAMA_4_SCOUT = "meta-llama/Llama-4-Scout-17B-16E-Instruct"  # Meta, MoE 109B total / 17B active
PHI_4 = "microsoft/phi-4"                                    # Microsoft, dense 14B

# Tried and rejected here, recorded so nobody re-adds them:
#   google/gemma-4-31B-it        504 + 6-min stall (2026-09-09), dense 30.7B
#   google/gemma-4-26B-A4B-it    504 after 121s on the real prompt (2026-09-10) - MoE did NOT
#                                fix it; Gemma 4 also emits a ~3K-char reasoning trace before
#                                the JSON, which the 5-dimension prompt pushes past any budget
#   meta-llama/Llama-3.3-70B     returned 4 on every dimension (a judge carrying no information)
#   mistralai/Mistral-Small-3.1  HF router: "not a chat model" (400) - not served for chat
REJECTED_HERE = (
    "google/gemma-4-31B-it",
    "google/gemma-4-26B-A4B-it",
    "meta-llama/Llama-3.3-70B-Instruct",
    "mistralai/Mistral-Small-3.1-24B-Instruct-2503",
)

# Also served and non-Chinese, kept here as documented alternates rather than buried in a commit
# message. gpt-oss shares lineage with the OpenAI judge, so using it would make two of three
# judges one family and leave self-preference unmeasured.
ALTERNATES = (
    "ibm-granite/granite-4.2-30b",                    # IBM
    "mistralai/Mistral-Small-3.1-24B-Instruct-2503",  # Mistral, EU
    "microsoft/phi-4",                                # Microsoft
    "openai/gpt-oss-120b",                            # OpenAI open-weight - see note above
)

STRUCTURED_MODES = ("json_schema", "json_object", "prompted")


class HuggingFacePanelClient:
    """One Hugging Face judge behind the panel's ``JudgeClient`` protocol."""

    def __init__(
        self,
        model_id: str,
        api_key: Optional[str] = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        structured_mode: str = "json_object",
        # 300s, raised from 180 on 2026-09-09. A large open model generating a seven-
        # dimension verdict through the HF router can exceed 180s, and the SDK then retries:
        # three attempts at 180s is a nine-minute stall for one call that fails anyway.
        timeout: float = 300.0,
        # One retry, not two. A call slow enough to time out once will usually time out
        # again, and each attempt is billed.
        max_retries: int = 1,
    ) -> None:
        if structured_mode not in STRUCTURED_MODES:
            raise ValueError(
                f"unknown structured_mode {structured_mode!r}; expected one of {STRUCTURED_MODES}"
            )
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(
                "The 'openai' package is not installed. It is used here as an OpenAI-compatible "
                "HTTP client for the Hugging Face router, not to call OpenAI."
            ) from exc

        key = api_key or os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_API_KEY")
        if not key:
            raise RuntimeError(
                "HF_TOKEN is not set, so the Hugging Face judges cannot run. Add it to .env "
                "(see the HUGGING FACE block there), or drop these judges from the panel config."
            )

        self.model_id = model_id
        self.structured_mode = structured_mode
        self.base_url = base_url
        # Reasoning-style models emit long traces; 1500 is enough for a verdict but not for a
        # model that thinks out loud first, so callers should raise max_tokens for these.
        self._client: Any = OpenAI(
            api_key=key, base_url=base_url, timeout=timeout, max_retries=max_retries
        )

    # -- prompt-side fallback -------------------------------------------------
    @staticmethod
    def _schema_instruction(schema: Dict[str, Any]) -> str:
        """Describe the schema in the prompt, for providers that enforce nothing.

        Only used in `prompted` mode. Spelled out rather than hand-waved because this is the
        weakest mode and the validator downstream is unforgiving.
        """
        return (
            "\n\n[OUTPUT FORMAT]\n"
            "Reply with a single JSON object and nothing else. No prose before or after, no "
            "markdown fences. It must match this JSON Schema exactly, including property "
            "order:\n"
            f"{json.dumps(schema, indent=2)}"
        )

    def complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float,
        max_tokens: int,
        schema: Optional[Dict[str, Any]] = None,
    ) -> Completion:
        if schema is not None and self.structured_mode == "prompted":
            user = user + self._schema_instruction(schema)

        kwargs: Dict[str, Any] = {
            "model": self.model_id,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if schema is not None and self.structured_mode == "json_schema":
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "verdict", "strict": True, "schema": schema},
            }
        elif schema is not None and self.structured_mode == "json_object":
            kwargs["response_format"] = {"type": "json_object"}

        response = self._client.chat.completions.create(**kwargs)

        message = response.choices[0].message
        text = message.content or ""

        # Some served models return the answer after a reasoning trace, or wrapped in a fence.
        # Stripping a fence is safe and reversible; anything more would be guessing at intent,
        # so a malformed body is left for the validator and the repair pass to handle.
        text = _strip_code_fence(text)

        usage = getattr(response, "usage", None)
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
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


def _strip_code_fence(text: str) -> str:
    """Remove a leading ```json fence and its closing pair, if present."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return text
    lines = stripped.splitlines()
    if len(lines) < 2:
        return text
    lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()
