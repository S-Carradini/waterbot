"""A judge client that never touches the network (L2).

Invariant 3: judge clients are injected and tests use a fake. This one is built to be more than
a stub - it can reproduce every failure the panel is supposed to survive, because a fake that
only ever succeeds tests nothing but the happy path:

* malformed JSON, so the parse path is exercised
* a cited evidence id that was never shown, which is a judge hallucinating its own grounding
* a quoted span absent from the answer, which is the check that makes span quoting worth asking
  for
* abstention, which must never be confused with a zero
* per-sample score variation, so k samples genuinely differ and variance is not an artifact of
  the fake being constant

Scores are deterministic given a seed, so a test asserting a distribution is asserting something
stable rather than hoping.
"""

from __future__ import annotations

import json
import random
from typing import Any, Callable, Dict, List, Optional, Sequence

from eval.judge.panel import Completion


class FakeJudgeClient:
    """Deterministic stand-in for one judge model.

    ``score_for`` receives ``(dimension, sample_index)`` and returns a score, so a test can pin
    an exact distribution. Left unset, scores are drawn from a seeded generator that varies with
    the sample index - which is what makes a k=5 run produce five genuinely different verdicts.
    """

    def __init__(
        self,
        model_id: str = "fake-judge-v1",
        score_for: Optional[Callable[[str, int], Optional[int]]] = None,
        scores: Sequence[int] = (2, 3, 4),
        seed: int = 0,
        abstain_dimensions: Sequence[str] = (),
        confidence: str = "medium",
        failure_modes: Sequence[str] = (),
        malformed_on_call: Optional[Callable[[int], bool]] = None,
        invent_evidence_id: Optional[int] = None,
        bogus_span: Optional[str] = None,
        quote_from_answer: bool = True,
        prompt_tokens: int = 900,
        completion_tokens: int = 180,
        cached_tokens: int = 0,
        raise_on_call: Optional[Callable[[int], bool]] = None,
    ) -> None:
        self.model_id = model_id
        self._score_for = score_for
        self._scores = list(scores)
        self._seed = seed
        self._abstain = set(abstain_dimensions)
        self._confidence = confidence
        self._failure_modes = list(failure_modes)
        self._malformed_on_call = malformed_on_call
        self._invent_evidence_id = invent_evidence_id
        self._bogus_span = bogus_span
        self._quote_from_answer = quote_from_answer
        self._prompt_tokens = prompt_tokens
        self._completion_tokens = completion_tokens
        self._cached_tokens = cached_tokens
        self._raise_on_call = raise_on_call
        self.calls: List[Dict[str, Any]] = []

    # -- prompt reading ---------------------------------------------------
    @staticmethod
    def _dimensions_from(user: str) -> List[str]:
        """Read the dimension list back out of the rendered prompt.

        The fake answers exactly what it was asked, the way a compliant judge would. Scoring a
        dimension nobody asked for would be a different failure and is not what this simulates.
        """
        marker = "Score these dimensions, and only these:"
        for line in user.splitlines():
            if marker in line:
                return [d.strip() for d in line.split(marker, 1)[1].split(",") if d.strip()]
        return ["grounding"]

    @staticmethod
    def _evidence_ids_from(user: str) -> List[int]:
        ids: List[int] = []
        in_evidence = False
        for line in user.splitlines():
            if line.startswith("[EVIDENCE]"):
                in_evidence = True
                continue
            if in_evidence and line.startswith("[") and line.endswith("]"):
                break
            if in_evidence and line.startswith("[") and "]" in line:
                token = line[1 : line.index("]")]
                if token.isdigit():
                    ids.append(int(token))
        return ids

    @staticmethod
    def _answer_from(user: str) -> str:
        if "[RESPONSE]" not in user:
            return ""
        after = user.split("[RESPONSE]", 1)[1]
        for terminator in ("[CITATIONS]", "[TASK]"):
            if terminator in after:
                after = after.split(terminator, 1)[0]
        return after.strip()

    # -- the client surface ----------------------------------------------
    def complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float,
        max_tokens: int,
        schema: Optional[Dict[str, Any]] = None,
    ) -> Completion:
        call_number = len(self.calls) + 1
        self.calls.append(
            {"system": system, "user": user, "temperature": temperature, "schema": schema}
        )

        if self._raise_on_call is not None and self._raise_on_call(call_number):
            raise RuntimeError(f"FakeJudgeClient: injected provider failure on call {call_number}")

        if self._malformed_on_call is not None and self._malformed_on_call(call_number):
            return self._completion("this is not json at all {{{")

        # A repair prompt has no dimension list; echo a minimal valid verdict so the repair path
        # can be tested end to end.
        if "Your previous output was:" in user:
            return self._completion(self._payload(["grounding"], [], "", sample_hint=0))

        dimensions = self._dimensions_from(user)
        evidence_ids = self._evidence_ids_from(user)
        answer = self._answer_from(user)
        # Sample index is not in the prompt, so vary on call count: successive calls to the same
        # client are successive samples, which is exactly how the runner uses it.
        return self._completion(self._payload(dimensions, evidence_ids, answer, call_number))

    def _completion(self, text: str) -> Completion:
        return Completion(
            text=text,
            prompt_tokens=self._prompt_tokens,
            completion_tokens=self._completion_tokens,
            cached_tokens=self._cached_tokens,
        )

    def _span(self, answer: str) -> str:
        if self._bogus_span is not None:
            return self._bogus_span
        if not self._quote_from_answer or not answer:
            return ""
        words = answer.split()
        return " ".join(words[: min(6, len(words))])

    def _payload(
        self, dimensions: Sequence[str], evidence_ids: Sequence[int], answer: str,
        sample_hint: int,
    ) -> str:
        rng = random.Random(f"{self._seed}:{self.model_id}:{sample_hint}")
        cited = list(evidence_ids[:1])
        if self._invent_evidence_id is not None:
            cited = [self._invent_evidence_id]

        body: Dict[str, Any] = {}
        for dimension in dimensions:
            if dimension in self._abstain:
                body[dimension] = {
                    "rationale": f"The evidence does not settle {dimension}.",
                    "quoted_span": "",
                    "evidence_ids": [],
                    "insufficient_evidence": True,
                    "score": None,
                }
                continue
            if self._score_for is not None:
                score = self._score_for(dimension, sample_hint)
            else:
                score = rng.choice(self._scores)
            if score is None:
                body[dimension] = {
                    "rationale": f"Abstaining on {dimension}.",
                    "quoted_span": "",
                    "evidence_ids": [],
                    "insufficient_evidence": True,
                    "score": None,
                }
            else:
                body[dimension] = {
                    "rationale": f"Judged {dimension} against the retrieved passages.",
                    "quoted_span": self._span(answer),
                    "evidence_ids": cited,
                    "insufficient_evidence": False,
                    "score": score,
                }

        return json.dumps(
            {
                "dimensions": body,
                "failure_modes": self._failure_modes,
                "overall_confidence": self._confidence,
            }
        )
