"""L2: the judge panel runner.

Fans one frozen response out to m judges x k samples, validates every verdict mechanically,
repairs once on failure, counts what happened, and stops when the budget says so.

THE TWO VALIDATIONS THE SCHEMA CANNOT EXPRESS
---------------------------------------------
Constrained decoding guarantees the shape of a verdict. It cannot check that the verdict is
about the thing it claims to be about, and both of those checks are cheap and mechanical:

1. **Cited evidence must exist.** A judge citing passage 9 when it was shown 5 is hallucinating
   its own grounding. This is the check that makes "evidence-grounded" mean something rather
   than being a claim in a prompt.
2. **The quoted span must appear in the answer.** Verbatim after whitespace normalisation. This
   is what makes span quoting worth requiring at all; without the check, a judge can quote
   something plausible-sounding that was never said, and the audit trail becomes decorative.

A failure triggers **one** repair attempt, then counts as a hard failure. The repair rate is
reported, never swallowed: parse and validation failures concentrate on hard items, so silent
retries are a bias, not housekeeping.

BUDGET IS ENFORCED HERE, NOT ASKED FOR
--------------------------------------
Cumulative spend is tracked from each response's usage and the run aborts when it crosses the
cap. Not a prompt instruction, not a hook: a hook cannot stop a loop already in flight, and a
prompted instruction is followed most of the time rather than every time. The quota was already
exhausted mid-session once during this project.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple

from eval.judge.cache import CacheStats, VerdictCache, cache_key
from eval.judge.prompting import (
    POINTWISE_V1,
    RenderedPrompt,
    render_pointwise,
    render_repair,
    verdict_json_schema,
)
from eval.judge.rubric import Rubric
from eval.judge.schemas import DimensionVerdict, Response, Verdict

_WHITESPACE = re.compile(r"\s+")

# Bumped when the panel's own behaviour changes in a way that alters verdicts.
PANEL_VERSION = "1.0.0"


class BudgetExceeded(RuntimeError):
    """Raised when a run would cross its spending cap. Aborts rather than continuing."""


class VerdictRejected(RuntimeError):
    """A verdict failed validation twice, including after repair."""


# ---------------------------------------------------------------------------
# The client boundary
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Completion:
    """What a provider returned, plus what it cost."""

    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0  # prompt tokens served from the provider's cache, billed lower

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class JudgeClient(Protocol):
    """One judge model behind a uniform surface.

    ``schema`` is passed for provider-native constrained decoding rather than being described in
    the prompt. Implementations live in ``clients/`` and are the only network-touching code in
    the judge package.
    """

    model_id: str

    def complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float,
        max_tokens: int,
        schema: Optional[Dict[str, Any]] = None,
    ) -> Completion: ...


# ---------------------------------------------------------------------------
# Cost and budget
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Pricing:
    """USD per 1000 tokens. Cached prompt tokens bill lower, which is the point of caching."""

    prompt: float
    completion: float
    cached_prompt: float = 0.0

    def cost(self, completion: Completion) -> float:
        fresh_prompt = max(0, completion.prompt_tokens - completion.cached_tokens)
        return (
            fresh_prompt / 1000 * self.prompt
            + completion.cached_tokens / 1000 * self.cached_prompt
            + completion.completion_tokens / 1000 * self.completion
        )


@dataclass
class Budget:
    """A hard cap, checked before each call and updated after it."""

    cap_usd: Optional[float] = None
    spent_usd: float = 0.0
    calls: int = 0

    def check(self, projected: float = 0.0) -> None:
        if self.cap_usd is None:
            return
        if self.spent_usd + projected > self.cap_usd:
            raise BudgetExceeded(
                f"budget cap ${self.cap_usd:.2f} would be exceeded: "
                f"${self.spent_usd:.4f} already spent, ${projected:.4f} projected for the next "
                "call. Aborting rather than continuing."
            )

    def record(self, amount: float) -> None:
        self.spent_usd += amount
        self.calls += 1

    @property
    def remaining(self) -> Optional[float]:
        return None if self.cap_usd is None else max(0.0, self.cap_usd - self.spent_usd)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cap_usd": self.cap_usd,
            "spent_usd": round(self.spent_usd, 6),
            "calls": self.calls,
            "remaining_usd": None if self.remaining is None else round(self.remaining, 6),
        }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def normalise_span(text: str) -> str:
    """Collapse whitespace and casefold, for comparing a quoted span to an answer.

    Deliberately not more aggressive. Stripping punctuation would let a judge quote a span that
    differs from the answer in ways a reader would notice, which is exactly what the check is
    supposed to catch.
    """
    return _WHITESPACE.sub(" ", text).strip().casefold()


def validate_verdict(verdict: Verdict, response: Response) -> List[str]:
    """Return the problems with a verdict. Empty list means it passed.

    Returned rather than raised so the caller can feed them into the repair prompt, and so every
    problem is reported at once instead of one per attempt.
    """
    problems: List[str] = []
    shown = {p.evidence_id for p in response.passages}
    answer = normalise_span(response.answer)

    for name, dimension in sorted(verdict.dimensions.items()):
        invented = sorted(set(dimension.evidence_ids) - shown)
        if invented:
            problems.append(
                f"{name}: cites evidence {invented} but only {sorted(shown) or 'none'} "
                "was shown"
            )
        span = dimension.quoted_span.strip()
        if span and normalise_span(span) not in answer:
            excerpt = span if len(span) <= 60 else span[:57] + "..."
            problems.append(
                f"{name}: quoted span {excerpt!r} does not appear in the response"
            )
        # An abstention that still cites evidence is incoherent: the judge is saying the
        # evidence is insufficient while pointing at the evidence it used.
        if dimension.insufficient_evidence and dimension.evidence_ids:
            problems.append(
                f"{name}: abstained for insufficient evidence but cited {dimension.evidence_ids}"
            )
    return problems


def parse_verdict(
    raw: str,
    response: Response,
    judge_model_id: str,
    sample_index: int,
    temperature: float,
    prompt_hash: str,
    rubric_hash: str,
    repaired: bool = False,
) -> Verdict:
    """Turn a provider's JSON into a Verdict. Raises on anything that is not one."""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise VerdictRejected(f"output is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise VerdictRejected(f"output is {type(payload).__name__}, expected an object")

    dimensions_raw = payload.get("dimensions")
    if not isinstance(dimensions_raw, dict) or not dimensions_raw:
        raise VerdictRejected("output has no dimensions object")

    dimensions: Dict[str, DimensionVerdict] = {}
    for name, body in dimensions_raw.items():
        try:
            dimensions[name] = DimensionVerdict.model_validate(body)
        except Exception as exc:  # noqa: BLE001 - surfaced as a rejection with context
            raise VerdictRejected(f"dimension {name!r} is malformed: {exc}") from exc

    try:
        return Verdict(
            item_id=response.item_id,
            response_id=response.response_id,
            judge_model_id=judge_model_id,
            sample_index=sample_index,
            temperature=temperature,
            prompt_hash=prompt_hash,
            rubric_hash=rubric_hash,
            corpus_fingerprint="",  # filled by the runner, which knows the run's fingerprint
            dimensions=dimensions,
            failure_modes=payload.get("failure_modes", []),
            overall_confidence=payload.get("overall_confidence", "medium"),
            repaired=repaired,
        )
    except Exception as exc:  # noqa: BLE001
        raise VerdictRejected(f"verdict failed its own contract: {exc}") from exc


# ---------------------------------------------------------------------------
# Run accounting
# ---------------------------------------------------------------------------
@dataclass
class PanelStats:
    """What actually happened, in the detail needed to trust or distrust the output."""

    requested: int = 0
    from_cache: int = 0
    called: int = 0
    repaired: int = 0
    rejected: int = 0
    abstained_dimensions: int = 0
    scored_dimensions: int = 0
    failures: List[str] = field(default_factory=list)

    @property
    def repair_rate(self) -> float:
        """Reported, never swallowed: failures concentrate on hard items, so this is a bias."""
        return self.repaired / self.called if self.called else 0.0

    @property
    def rejection_rate(self) -> float:
        return self.rejected / self.requested if self.requested else 0.0

    @property
    def abstention_rate(self) -> float:
        total = self.abstained_dimensions + self.scored_dimensions
        return self.abstained_dimensions / total if total else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "requested": self.requested,
            "from_cache": self.from_cache,
            "called": self.called,
            "repaired": self.repaired,
            "repair_rate": self.repair_rate,
            "rejected": self.rejected,
            "rejection_rate": self.rejection_rate,
            "abstained_dimensions": self.abstained_dimensions,
            "scored_dimensions": self.scored_dimensions,
            "abstention_rate": self.abstention_rate,
            "failures": self.failures[:20],
        }


# ---------------------------------------------------------------------------
# The runner
# ---------------------------------------------------------------------------
class PanelRunner:
    """Runs a panel of judges over frozen responses.

    Synchronous by design. Concurrency belongs at the call site with a per-provider semaphore,
    and keeping the runner sequential means the cache, the budget and the statistics have no
    shared-state races to reason about. A batch path is a separate concern (spec 4.3) and slots
    in as an alternative client rather than a change here.
    """

    def __init__(
        self,
        clients: Sequence[JudgeClient],
        rubric: Rubric,
        rubric_hash: str,
        corpus_fingerprint: str,
        pricing: Optional[Dict[str, Pricing]] = None,
        cache: Optional[VerdictCache] = None,
        budget: Optional[Budget] = None,
        temperature: float = 0.3,
        samples: int = 5,
        max_tokens: int = 1500,
        template_name: str = POINTWISE_V1,
        allow_unpiloted_rubric: bool = False,
    ) -> None:
        if not clients:
            raise ValueError("a panel needs at least one judge client")
        if samples < 1:
            raise ValueError("samples (k) must be at least 1")

        model_ids = [c.model_id for c in clients]
        if len(set(model_ids)) != len(model_ids):
            raise ValueError(f"judge model ids must be distinct, got {model_ids}")

        if not rubric.is_piloted and not allow_unpiloted_rubric:
            # Architecture section 5 is firm: if two humans cannot agree using these anchors, no
            # model will. Running a panel on an unpiloted rubric produces numbers that cannot be
            # interpreted, so it has to be a deliberate choice.
            raise ValueError(
                "this rubric has not been piloted with human annotators, so panel scores would "
                "not be interpretable. Run the 20-item two-human pilot first, or pass "
                "allow_unpiloted_rubric=True to proceed deliberately."
            )

        self.clients = list(clients)
        self.rubric = rubric
        self.rubric_hash = rubric_hash
        self.corpus_fingerprint = corpus_fingerprint
        self.pricing = pricing or {}
        self.cache = cache if cache is not None else VerdictCache()
        self.budget = budget or Budget()
        self.temperature = temperature
        self.samples = samples
        self.max_tokens = max_tokens
        self.template_name = template_name
        self.stats = PanelStats()

    # -- one verdict ------------------------------------------------------
    def _price(self, model_id: str) -> Optional[Pricing]:
        return self.pricing.get(model_id)

    def _call(self, client: JudgeClient, prompt: RenderedPrompt, schema: Dict) -> Completion:
        pricing = self._price(client.model_id)
        if pricing is not None:
            # Project the cost before spending it, so the cap is a cap rather than a report.
            projected = pricing.cost(
                Completion(text="", prompt_tokens=prompt.approximate_tokens,
                           completion_tokens=self.max_tokens)
            )
            self.budget.check(projected)
        else:
            self.budget.check()

        completion = client.complete(
            prompt.system, prompt.user,
            temperature=self.temperature, max_tokens=self.max_tokens, schema=schema,
        )
        if pricing is not None:
            self.budget.record(pricing.cost(completion))
        else:
            self.budget.record(0.0)
        self.stats.called += 1
        return completion

    def judge_once(
        self,
        response: Response,
        client: JudgeClient,
        sample_index: int,
        dimensions: Optional[Sequence[str]] = None,
        use_cache: bool = True,
    ) -> Verdict:
        """One judge, one sample, with validation and at most one repair."""
        prompt = render_pointwise(response, self.rubric, dimensions, self.template_name)
        names = sorted(
            dimensions
            if dimensions is not None
            else self.rubric.applicable_names(
                response.category, has_citations=bool(response.citations)
            )
        )
        schema = verdict_json_schema(names, [m.name for m in self.rubric.failure_modes])

        key = cache_key(
            judge_model_id=client.model_id,
            prompt_hash=prompt.prompt_hash,
            rubric_hash=self.rubric_hash,
            corpus_fingerprint=self.corpus_fingerprint,
            item_id=response.response_id,
            sample_index=sample_index,
            temperature=self.temperature,
            protocol="pointwise",
        )
        self.stats.requested += 1

        if use_cache:
            cached = self.cache.get(key)
            if cached is not None:
                self.stats.from_cache += 1
                self._count_dimensions(cached)
                return cached

        completion = self._call(client, prompt, schema)
        verdict, problems = self._parse_and_validate(
            completion.text, response, client, sample_index, prompt, repaired=False
        )

        if problems:
            # Exactly one repair attempt. Retrying blind would turn a systematic failure into a
            # cost, and the failure itself is the signal worth keeping.
            repair_prompt = render_repair(completion.text, problems)
            repair_completion = self._call(client, repair_prompt, schema)
            self.stats.repaired += 1
            verdict, problems = self._parse_and_validate(
                repair_completion.text, response, client, sample_index, prompt, repaired=True
            )
            if problems:
                self.stats.rejected += 1
                message = f"{response.response_id} / {client.model_id} / s{sample_index}: " + \
                    "; ".join(problems)
                self.stats.failures.append(message)
                raise VerdictRejected(message)

        if use_cache:
            self.cache.put(key, verdict)
        self._count_dimensions(verdict)
        return verdict

    def _parse_and_validate(
        self,
        raw: str,
        response: Response,
        client: JudgeClient,
        sample_index: int,
        prompt: RenderedPrompt,
        repaired: bool,
    ) -> Tuple[Optional[Verdict], List[str]]:
        try:
            verdict = parse_verdict(
                raw, response, client.model_id, sample_index, self.temperature,
                prompt.prompt_hash, self.rubric_hash, repaired=repaired,
            )
        except VerdictRejected as exc:
            return None, [str(exc)]

        verdict = verdict.model_copy(update={"corpus_fingerprint": self.corpus_fingerprint})
        return verdict, validate_verdict(verdict, response)

    def _count_dimensions(self, verdict: Verdict) -> None:
        for dimension in verdict.dimensions.values():
            if dimension.insufficient_evidence:
                self.stats.abstained_dimensions += 1
            else:
                self.stats.scored_dimensions += 1

    # -- the fan-out ------------------------------------------------------
    def judge_response(
        self,
        response: Response,
        dimensions: Optional[Sequence[str]] = None,
        skip_rejected: bool = True,
    ) -> List[Verdict]:
        """m judges x k samples over one response.

        A rejected verdict is skipped rather than aborting the run by default: one judge failing
        validation twice on one item should not discard the other m*k-1 opinions. The rejection
        is counted, and the rejection rate is reported so a systematically failing judge is
        visible rather than quietly absent.
        """
        verdicts: List[Verdict] = []
        for client in self.clients:
            for sample_index in range(self.samples):
                try:
                    verdicts.append(
                        self.judge_once(response, client, sample_index, dimensions)
                    )
                except VerdictRejected:
                    if not skip_rejected:
                        raise
        return verdicts

    def judge_all(
        self,
        responses: Sequence[Response],
        dimensions: Optional[Sequence[str]] = None,
        skip_rejected: bool = True,
    ) -> List[Verdict]:
        """The whole panel over a frozen set. Stops immediately if the budget is exceeded."""
        verdicts: List[Verdict] = []
        for response in sorted(responses, key=lambda r: r.response_id):
            verdicts.extend(self.judge_response(response, dimensions, skip_rejected))
        return verdicts

    def report(self) -> Dict[str, Any]:
        return {
            "panel_version": PANEL_VERSION,
            "judges": [c.model_id for c in self.clients],
            "samples_per_judge": self.samples,
            "temperature": self.temperature,
            "stats": self.stats.to_dict(),
            "cache": self.cache.stats.to_dict(),
            "budget": self.budget.to_dict(),
        }


# ---------------------------------------------------------------------------
# The withheld-evidence probe
# ---------------------------------------------------------------------------
def withhold_evidence(response: Response, donor: Response) -> Response:
    """Same question and answer, evidence swapped for another question's passages.

    A first-class experimental condition, not a script. Instructing a judge to ignore outside
    knowledge does not make it do so; this measures how often it produces a confident,
    non-abstaining verdict when the evidence cannot possibly support one. That rate is an upper
    bound on how much the judge is reasoning from what it already knows about Arizona water
    policy rather than from the corpus.
    """
    if donor.item_id == response.item_id:
        raise ValueError(
            "the donor must be a different item; swapping an item's evidence for its own "
            "measures nothing"
        )
    renumbered = [
        p.model_copy(update={"evidence_id": index})
        for index, p in enumerate(
            sorted(donor.passages, key=lambda p: p.evidence_id), start=1
        )
    ]
    return response.model_copy(update={"passages": renumbered})


def strip_evidence(response: Response) -> Response:
    """Same question and answer, NO evidence at all. The tripwire.

    Distinct from ``withhold_evidence``, and they answer different questions:

    * ``withhold_evidence`` swaps in another item's passages, asking "does the judge reason from
      what it already knows when the evidence is wrong?"
    * ``strip_evidence`` removes evidence entirely, asking "is this metric measuring anything?"

    The second is the sharper test. A controlled study measured reference-free faithfulness at
    0.978 with no context at all, against 0.893-0.902 with real retrieval - the metric scored
    HIGHER on nothing than on evidence, because it was rewarding fluent, self-consistent prose
    rather than grounding.

    If panel scores on stripped responses land near full-system scores, the configuration is not
    measuring grounding and no result from it is publishable. That is a finding about the method,
    and it is the demonstration the evidence layer's whole argument rests on.
    """
    return response.model_copy(update={"passages": [], "citations": []})


@dataclass(frozen=True)
class TripwireResult:
    """What the no-context run showed, and whether the metric survived it."""

    n_items: int
    full_mean: Optional[float]
    stripped_mean: Optional[float]
    stripped_abstention_rate: float
    threshold: float = 0.5

    @property
    def drop(self) -> Optional[float]:
        """How far scores fell when the evidence was taken away. Should be large."""
        if self.full_mean is None or self.stripped_mean is None:
            return None
        return self.full_mean - self.stripped_mean

    @property
    def metric_survived(self) -> bool:
        """True when removing the evidence actually cost the system something.

        Either scores drop by more than the threshold, or the judge abstains on most stripped
        items - both are correct behaviour. Scoring confidently on nothing is the failure.
        """
        if self.stripped_abstention_rate >= 0.5:
            return True
        return self.drop is not None and self.drop >= self.threshold

    @property
    def verdict(self) -> str:
        if self.full_mean is None or self.stripped_mean is None:
            return "not enough scored items to judge the metric"
        if self.metric_survived:
            return (
                f"metric survives: removing the evidence cost {self.drop:.2f} levels "
                f"({self.full_mean:.2f} -> {self.stripped_mean:.2f}), abstention rose to "
                f"{self.stripped_abstention_rate:.0%}"
            )
        return (
            f"METRIC IS BROKEN: scoring {self.stripped_mean:.2f} with no evidence against "
            f"{self.full_mean:.2f} with it, a drop of only {self.drop:.2f} levels, and the judge "
            f"abstained on just {self.stripped_abstention_rate:.0%}. This configuration is not "
            "measuring grounding, and no result from it is publishable."
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "n_items": self.n_items,
            "full_mean": self.full_mean,
            "stripped_mean": self.stripped_mean,
            "drop": self.drop,
            "stripped_abstention_rate": self.stripped_abstention_rate,
            "threshold": self.threshold,
            "metric_survived": self.metric_survived,
            "verdict": self.verdict,
        }


def _mean_score(verdicts: Sequence[Verdict]) -> Optional[float]:
    scores = [
        d.score
        for v in verdicts
        for d in v.dimensions.values()
        if d.score is not None
    ]
    return sum(scores) / len(scores) if scores else None


def evaluate_tripwire(
    full_verdicts: Sequence[Verdict],
    stripped_verdicts: Sequence[Verdict],
    threshold: float = 0.5,
) -> TripwireResult:
    """Compare panel scores with and without evidence. The whole tripwire, in one number."""
    total = sum(len(v.dimensions) for v in stripped_verdicts)
    abstained = sum(len(v.abstained_dimensions) for v in stripped_verdicts)
    return TripwireResult(
        n_items=len({v.response_id for v in stripped_verdicts}),
        full_mean=_mean_score(full_verdicts),
        stripped_mean=_mean_score(stripped_verdicts),
        stripped_abstention_rate=abstained / total if total else 0.0,
        threshold=threshold,
    )


def parametric_reliance(verdicts: Sequence[Verdict]) -> Dict[str, float]:
    """Share of withheld-evidence verdicts that still scored confidently.

    A well-behaved judge shown irrelevant evidence should abstain. Every dimension it scores
    anyway - especially at high confidence - is a dimension it answered from memory.
    """
    if not verdicts:
        return {"n_verdicts": 0, "confident_rate": 0.0, "scored_rate": 0.0}

    scored = 0
    total = 0
    confident = 0
    for verdict in verdicts:
        for dimension in verdict.dimensions.values():
            total += 1
            if not dimension.insufficient_evidence:
                scored += 1
                if verdict.overall_confidence == "high":
                    confident += 1
    return {
        "n_verdicts": len(verdicts),
        "n_dimensions": total,
        "scored_rate": scored / total if total else 0.0,
        "confident_rate": confident / total if total else 0.0,
    }
