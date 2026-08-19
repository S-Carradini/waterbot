"""Judge client protocol, a fake for tests, and call accounting.

WHY THIS SHAPE
--------------
The existing refusal judge, ``eval.generation_metrics.judge_hallucination``,
takes an ``llm_adapter`` and touches exactly two attributes on it::

    llm_adapter.model_id
    llm_adapter.client.chat.completions.create(...)

That is a narrow enough surface to satisfy by duck typing, so replication
experiments can drive the real judge without editing a line of it. Milestone 1
is measurement only: if the thing being measured has to be modified to be
measured, the measurement is of something else.

THE CONTAMINATION PROBLEM
-------------------------
``judge_hallucination`` wraps its API call in a bare ``except Exception`` and
falls back to ``_keyword_hallucination_check``, which is deterministic. So an
exhausted quota, a rate limit, or a network blip does not surface as an error.
It surfaces as *perfect judge stability* - the exact conclusion this experiment
exists to test, arrived at for the exact wrong reason.

``CallRecorder`` therefore sits between the judge and the provider and counts
every attempt and every exception. A replicate with any recorded exception is
contaminated: some of its 12 verdicts came from the keyword fallback, not the
model. The experiment reports those runs separately and never folds them into
the headline distribution.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------
class ChatCompletions(Protocol):
    def create(self, **kwargs: Any) -> Any: ...


class ChatNamespace(Protocol):
    completions: ChatCompletions


class RawClient(Protocol):
    chat: ChatNamespace


class JudgeAdapter(Protocol):
    """The two attributes the existing judge actually needs.

    Deliberately smaller than ``application.adapters.openai.OpenAIAdapter``.
    Anything satisfying this can be passed to ``judge_hallucination``.
    """

    model_id: str
    client: RawClient


# ---------------------------------------------------------------------------
# Minimal stand-ins for the OpenAI response objects
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class FakeUsage:
    prompt_tokens: int
    completion_tokens: int


@dataclass(frozen=True)
class FakeMessage:
    content: str


@dataclass(frozen=True)
class FakeChoice:
    message: FakeMessage


@dataclass(frozen=True)
class FakeResponse:
    """Shaped like the subset of ``ChatCompletion`` the judge reads."""

    choices: List[FakeChoice]
    usage: Optional[FakeUsage] = None


# ---------------------------------------------------------------------------
# FakeClient
# ---------------------------------------------------------------------------
class FakeCompletions:
    def __init__(self, owner: "FakeClient") -> None:
        self._owner = owner

    def create(self, **kwargs: Any) -> FakeResponse:
        return self._owner._create(**kwargs)


class FakeChat:
    def __init__(self, owner: "FakeClient") -> None:
        self.completions = FakeCompletions(owner)


class FakeRawClient:
    def __init__(self, owner: "FakeClient") -> None:
        self.chat = FakeChat(owner)


class FakeClient:
    """Network-free judge adapter.

    Two uses, and they must not be confused with each other:

    1. UNIT TESTS. ``FakeClient(fixed="REFUSED")`` gives a deterministic
       verdict so the plumbing can be tested without a key (invariant 3).

    2. PIPELINE REHEARSAL. ``item_refusal_prob`` assigns each benchmark
       question its own probability of drawing REFUSED, so the experiment can
       be run end to end and the statistics exercised against a distribution
       whose true parameters are known. Output from this mode is a simulation,
       never a measurement, and every artifact it produces is stamped as such.

    Matching is by substring: the judge embeds the question verbatim in its
    prompt, so the question text is the item key.
    """

    def __init__(
        self,
        model_id: str = "fake-judge-v0",
        fixed: Optional[str] = None,
        item_refusal_prob: Optional[Dict[str, float]] = None,
        default_refusal_prob: float = 1.0,
        seed: int = 0,
        fail_on_call: Optional[Callable[[int], bool]] = None,
        prompt_tokens: int = 278,
        completion_tokens: int = 1,
    ) -> None:
        if fixed is not None and fixed not in ("REFUSED", "ANSWERED"):
            raise ValueError(f"fixed must be REFUSED or ANSWERED, got {fixed!r}")
        self.model_id = model_id
        self.client = FakeRawClient(self)
        self._fixed = fixed
        self._item_prob = dict(item_refusal_prob or {})
        self._default_prob = default_refusal_prob
        self._rng = random.Random(seed)
        self._fail_on_call = fail_on_call
        self._prompt_tokens = prompt_tokens
        self._completion_tokens = completion_tokens
        self.calls: List[Dict[str, Any]] = []

    def _probability_for(self, prompt: str) -> float:
        for question, p in self._item_prob.items():
            if question in prompt:
                return p
        return self._default_prob

    def _create(self, **kwargs: Any) -> FakeResponse:
        messages = kwargs.get("messages") or []
        prompt = "\n".join(m.get("content", "") for m in messages)
        self.calls.append({"model": kwargs.get("model"), "prompt": prompt})

        if self._fail_on_call is not None and self._fail_on_call(len(self.calls)):
            raise RuntimeError("FakeClient: injected provider failure")

        if self._fixed is not None:
            verdict = self._fixed
        else:
            draw = self._rng.random()
            verdict = "REFUSED" if draw < self._probability_for(prompt) else "ANSWERED"

        return FakeResponse(
            choices=[FakeChoice(FakeMessage(verdict))],
            usage=FakeUsage(self._prompt_tokens, self._completion_tokens),
        )


# ---------------------------------------------------------------------------
# Call accounting
# ---------------------------------------------------------------------------
CANONICAL_VERDICTS = ("REFUSED", "ANSWERED")


@dataclass
class CallLedger:
    """Per-replicate accounting of what actually reached the provider."""

    attempts: int = 0
    errors: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    error_messages: List[str] = field(default_factory=list)
    # Raw completion text, in call order. Captured because the judge reduces
    # the model's reply to a bool with ``"ANSWERED" in verdict``, which codes
    # anything unexpected - a hedge, a truncation at max_tokens=10, a refusal
    # to judge - as REFUSED. Without the raw strings there is no way to tell a
    # decided REFUSED from an undecidable one, and the two would be pooled into
    # the same rate.
    contents: List[str] = field(default_factory=list)

    @property
    def contaminated(self) -> bool:
        """True if any verdict in this replicate came from the keyword fallback."""
        return self.errors > 0

    @property
    def noncanonical(self) -> List[str]:
        """Replies that were neither exactly REFUSED nor exactly ANSWERED."""
        return [c for c in self.contents if c.strip().upper() not in CANONICAL_VERDICTS]

    def reset(self) -> None:
        self.attempts = 0
        self.errors = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.error_messages = []
        self.contents = []

    def snapshot(self) -> "CallLedger":
        return CallLedger(
            attempts=self.attempts,
            errors=self.errors,
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            error_messages=list(self.error_messages),
            contents=list(self.contents),
        )

    def to_dict(self) -> Dict[str, Any]:
        noncanonical = self.noncanonical
        return {
            "attempts": self.attempts,
            "errors": self.errors,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "contaminated": self.contaminated,
            "error_messages": self.error_messages[:5],
            "noncanonical_replies": len(noncanonical),
            "noncanonical_samples": noncanonical[:5],
        }


class _RecordingCompletions:
    def __init__(self, inner: Any, ledger: CallLedger) -> None:
        self._inner = inner
        self._ledger = ledger

    def create(self, **kwargs: Any) -> Any:
        self._ledger.attempts += 1
        try:
            response = self._inner.create(**kwargs)
        except Exception as exc:  # noqa: BLE001 - recorded, then re-raised
            self._ledger.errors += 1
            self._ledger.error_messages.append(f"{type(exc).__name__}: {exc}")
            # Re-raise so the judge behaves exactly as it does in production.
            # We record the fact; we do not change the outcome.
            raise
        usage = getattr(response, "usage", None)
        if usage is not None:
            self._ledger.prompt_tokens += getattr(usage, "prompt_tokens", 0) or 0
            self._ledger.completion_tokens += getattr(usage, "completion_tokens", 0) or 0
        try:
            self._ledger.contents.append(response.choices[0].message.content or "")
        except (AttributeError, IndexError, TypeError):
            # Shape we did not expect. Record it as empty rather than crashing:
            # the judge is about to reduce it to a bool anyway, and an empty
            # string is correctly counted as non-canonical.
            self._ledger.contents.append("")
        return response


class _RecordingChat:
    def __init__(self, inner: Any, ledger: CallLedger) -> None:
        self.completions = _RecordingCompletions(inner.completions, ledger)


class _RecordingRawClient:
    def __init__(self, inner: Any, ledger: CallLedger) -> None:
        self.chat = _RecordingChat(inner.chat, ledger)


class CallRecorder:
    """Wraps a judge adapter and counts what passes through it.

    Transparent by design: it re-raises every exception unchanged, so the judge
    under measurement takes exactly the code path it would take in production,
    including its silent keyword fallback. The only thing that changes is that
    we can now see that the fallback happened.
    """

    def __init__(self, inner: JudgeAdapter) -> None:
        self._inner = inner
        self.ledger = CallLedger()
        self.model_id = inner.model_id
        self.client = _RecordingRawClient(inner.client, self.ledger)
