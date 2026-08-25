"""Data contracts for the judge pipeline.

Every artifact the pipeline reads or writes is defined here, and nowhere else. Written before
any pipeline code, per spec section 3, because these structures are the one place a mistake is
expensive: L2 writes them, L3 reads them, L4 fits on them and L5 reports them, so a silent
schema change corrupts results that were already recorded.

FOUR PROPERTIES ARE DELIBERATE
------------------------------
1. ``extra="forbid"`` everywhere. A typo'd field name is an error at write time rather than a
   silently missing column at analysis time, six weeks later.

2. ``frozen=True`` everywhere. Artifacts under ``eval/results/runs/`` are immutable by
   invariant; making the in-memory objects immutable too means the invariant cannot be violated
   by accident before it is ever written to disk.

3. ``schema_version`` on every persisted model. Verdicts are JSONL and are read back by later
   runs. Without a version, a schema change silently reinterprets historical results.

4. NULL IS NOT ZERO. A dimension that does not apply, or that a judge abstained on, carries
   ``score=None``. Collapsing that to 0.0 penalises a system for our bookkeeping - the same
   class of error as the corpus contamination L0 exists to prevent.

REPLACES eval/judge/schema.py
-----------------------------
An earlier stdlib-dataclass scaffold avoided pydantic to keep dependencies off the production
import path. That concern does not apply: the dependency runs one way, ``eval`` imports
``application`` and never the reverse, so nothing in the served app loads this module. CLAUDE.md
and spec section 3 both require pydantic v2, and ``.context/tools/gen_data_models.py`` already
expects this module name.
"""

from __future__ import annotations

import datetime
import hashlib
import json
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "1"

# The anchored ordinal scale from architecture section 5. Four levels, deliberately even: an odd
# scale gives judges a safe middle to retreat to, which compresses the distribution and destroys
# the resolution the whole panel exists to buy.
Score = Literal[1, 2, 3, 4]

Confidence = Literal["high", "medium", "low"]

# Domain failure modes worth encoding. A closed set, so a typo cannot invent a new mode that
# then reads as zero occurrences of a real one.
#
# MUST stay identical to the failure_modes block in rubric.yaml, which is the human-facing
# authority and the thing annotators are trained against. test_prompting.py asserts the two sets
# match, so they cannot drift apart silently.
#
# The first four are architecture section 5. The last three were added in the rubric: overrefusal
# is what makes the refusal dimension two-sided rather than one-sided, and the other two name
# grounding failures that the four original modes do not cover.
FailureMode = Literal[
    "entity_substitution",
    "jurisdictional_blurring",
    "superseded_policy",
    "unit_or_magnitude_drift",
    "unsupported_specificity",
    "overrefusal",
    "evidence_ignored",
]


def utcnow() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def stable_hash(payload: Any, length: int = 16) -> str:
    """SHA-256 over a canonical JSON dump, truncated.

    Canonical means sorted keys and no incidental whitespace, so logically identical inputs hash
    identically regardless of construction order. Used for prompt, rubric and cache identity,
    where an unstable hash would silently defeat caching or, worse, silently share a cache entry
    between two different configurations.
    """
    if isinstance(payload, str):
        raw = payload
    else:
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:length]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ---------------------------------------------------------------------------
# L0: evidence
# ---------------------------------------------------------------------------
class DuplicateProof(Strict):
    """Evidence for one alias-to-canonical claim.

    The canonical map is not a lookup table, it is a set of claims each carrying its own proof,
    so anyone can re-verify a single edge without trusting the pipeline that produced it. This
    is the part of L0 the architecture calls publishable in its own right.
    """

    alias: str
    canonical: str
    method: Literal["exact_hash", "minhash", "manual"]
    score: float = Field(ge=0.0, le=1.0)
    detected_at: str = Field(default_factory=utcnow)
    note: str = ""

    @model_validator(mode="after")
    def _exact_means_exact(self) -> "DuplicateProof":
        if self.method == "exact_hash" and self.score != 1.0:
            raise ValueError("exact_hash proof must have score 1.0")
        return self


class CorpusIdentity(Strict):
    """The output of L0: what the corpus is, and the fingerprint binding results to it."""

    schema_version: Literal["1"] = SCHEMA_VERSION
    fingerprint: str
    document_count: int = Field(ge=0)
    canonical_count: int = Field(ge=0)
    chunk_count: int = Field(ge=0)
    chunker_version: str
    chunk_size: int = Field(gt=0)
    chunk_overlap: int = Field(ge=0)
    embedding_model: str
    proofs: List[DuplicateProof] = Field(default_factory=list)
    created_at: str = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def _canonical_cannot_exceed_documents(self) -> "CorpusIdentity":
        if self.canonical_count > self.document_count:
            raise ValueError(
                f"canonical_count ({self.canonical_count}) exceeds document_count "
                f"({self.document_count}); deduplication cannot create documents"
            )
        return self


# ---------------------------------------------------------------------------
# L1: frozen responses
# ---------------------------------------------------------------------------
class Passage(Strict):
    """One retrieved passage, as shown to the judge.

    ``text`` is pinned rather than referenced. A pointer into the corpus would silently change
    meaning when the corpus is repaired, which would make old verdicts unreadable at exactly the
    moment RQ5 wants to compare corrupted against repaired.
    """

    evidence_id: int = Field(ge=1)  # 1-based, as numbered in the EVIDENCE block
    canonical_doc_id: str
    chunk_id: str
    text: str = Field(min_length=1)
    retrieval_rank: int = Field(ge=0)
    retrieval_score: float


class Response(Strict):
    """A frozen answer from a system under test, with everything needed to judge it."""

    schema_version: Literal["1"] = SCHEMA_VERSION
    item_id: str
    system: str  # waterbot | realwater
    persona: str  # blue | river
    question: str
    category: str
    answer: str
    passages: List[Passage] = Field(default_factory=list)
    citations: List[str] = Field(default_factory=list)
    latency_ms: int = Field(ge=0)
    cost_usd: float = Field(ge=0.0)

    @model_validator(mode="after")
    def _evidence_ids_are_unique_and_dense(self) -> "Response":
        ids = [p.evidence_id for p in self.passages]
        if len(set(ids)) != len(ids):
            raise ValueError(f"duplicate evidence_id in item {self.item_id}: {ids}")
        if ids and sorted(ids) != list(range(1, len(ids) + 1)):
            # The judge is told to cite by number. Gaps or repeats make a cited number
            # ambiguous, and citation validity is one of the scored dimensions.
            raise ValueError(
                f"evidence_ids for item {self.item_id} must be 1..n with no gaps, got {sorted(ids)}"
            )
        return self

    @property
    def response_id(self) -> str:
        """Content-independent identity: which item, from which system, in which persona."""
        return f"{self.item_id}::{self.system}::{self.persona}"


# ---------------------------------------------------------------------------
# L2: verdicts
# ---------------------------------------------------------------------------
class DimensionVerdict(Strict):
    """One judge's score on one dimension of one response.

    FIELD ORDER IS THE CONTRACT, NOT A STYLE CHOICE.

    Models emit fields in schema order, so this order forces the judge to commit to its evidence
    before it can write a justification, and to a justification before it can write a number:

        evidence_ids -> quoted_span -> rationale -> score

    Rationale-before-score alone was not enough. It stops the number driving the justification,
    but nothing stops both being written after the fact to fit a verdict already decided. Locking
    the cited evidence first is what makes the evidence-subset check in panel.py load-bearing
    rather than decorative: the judge has already said what it looked at.
    """

    evidence_ids: List[int] = Field(default_factory=list)
    quoted_span: str = ""  # from the RESPONSE, checked mechanically in panel.py
    rationale: str = Field(min_length=1)
    insufficient_evidence: bool = False
    score: Optional[Score] = None

    @model_validator(mode="after")
    def _abstention_consistency(self) -> "DimensionVerdict":
        if self.insufficient_evidence != (self.score is None):
            raise ValueError(
                "score must be null if and only if insufficient_evidence is true; "
                f"got score={self.score!r}, insufficient_evidence={self.insufficient_evidence!r}"
            )
        return self


class Verdict(Strict):
    """One judge's complete assessment of one response, at one sample index."""

    schema_version: Literal["1"] = SCHEMA_VERSION
    item_id: str
    response_id: str
    judge_model_id: str  # pinned snapshot id, never an alias (invariant 6)
    sample_index: int = Field(ge=0)  # 0..k-1, and part of the cache key (invariant 4)
    temperature: float = Field(ge=0.0)
    prompt_hash: str
    rubric_hash: str
    corpus_fingerprint: str
    dimensions: Dict[str, DimensionVerdict]
    failure_modes: List[FailureMode] = Field(default_factory=list)
    overall_confidence: Confidence = "medium"
    repaired: bool = False  # first parse failed; a reported metric, not an implementation detail
    order_position: Optional[Literal["first", "second"]] = None  # pairwise only
    created_at: str = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def _at_least_one_dimension(self) -> "Verdict":
        if not self.dimensions:
            raise ValueError(f"verdict for {self.item_id} scored no dimensions")
        return self

    @property
    def abstained_dimensions(self) -> List[str]:
        return sorted(n for n, d in self.dimensions.items() if d.insufficient_evidence)


class PairwiseVerdict(Strict):
    """One order-debiased preference between two systems on one item.

    An order-unstable pair becomes an explicit TIE rather than being discarded. Discarding it
    would condition the Bradley-Terry fit on a post-treatment variable - stability correlates
    with the outcome, since close calls flip and blowouts do not - and inflate the apparent
    separation between systems.
    """

    schema_version: Literal["1"] = SCHEMA_VERSION
    item_id: str
    system_a: str
    system_b: str
    judge_model_id: str
    sample_index: int = Field(ge=0)
    preference: Literal["a", "b", "tie"]
    order_stable: bool
    verdict_first: Literal["a", "b"]
    verdict_second: Literal["a", "b"]
    corpus_fingerprint: str
    created_at: str = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def _tie_iff_unstable(self) -> "PairwiseVerdict":
        flipped = self.verdict_first != self.verdict_second
        if flipped != (not self.order_stable):
            raise ValueError("order_stable must be false exactly when the two orders disagree")
        if not self.order_stable and self.preference != "tie":
            raise ValueError("an order-unstable pair must be recorded as a tie")
        return self


# ---------------------------------------------------------------------------
# L3: aggregates
# ---------------------------------------------------------------------------
class DimensionAggregate(Strict):
    """Panel consensus on one (response, dimension), with its spread retained.

    The spread is the point. A median with no IQR is exactly the bare point estimate that let an
    8.3-point swing hide behind a 5-point gate.
    """

    schema_version: Literal["1"] = SCHEMA_VERSION
    response_id: str
    dimension: str
    n_votes: int = Field(ge=0)
    n_abstained: int = Field(ge=0)
    median: Optional[float] = None
    mean: Optional[float] = None
    iqr: Optional[float] = None
    entropy: Optional[float] = None  # normalised, 0 = unanimous, 1 = uniform
    ci_low: Optional[float] = None
    ci_high: Optional[float] = None
    escalate: bool = False
    escalation_reason: Optional[Literal["panel_disagreement", "mostly_abstained"]] = None

    @model_validator(mode="after")
    def _escalation_has_a_reason(self) -> "DimensionAggregate":
        if self.escalate and self.escalation_reason is None:
            raise ValueError("escalate=True requires an escalation_reason")
        if not self.escalate and self.escalation_reason is not None:
            raise ValueError("escalation_reason set on a non-escalated aggregate")
        return self

    @model_validator(mode="after")
    def _interval_is_ordered(self) -> "DimensionAggregate":
        if self.ci_low is not None and self.ci_high is not None and self.ci_low > self.ci_high:
            raise ValueError(f"ci_low ({self.ci_low}) exceeds ci_high ({self.ci_high})")
        return self


# ---------------------------------------------------------------------------
# L4: human labels and calibration
# ---------------------------------------------------------------------------
class HumanLabel(Strict):
    """One annotator's score on one (response, dimension).

    ``pool`` is not metadata. Probe labels are a frozen stratified sample used only for
    reporting; acquire labels are uncertainty-sampled and used only for fitting. Fitting on
    probe, or reporting error on acquire, is the double-bias the architecture's Algorithm 4
    walks straight into, so the distinction is carried on every label.
    """

    schema_version: Literal["1"] = SCHEMA_VERSION
    response_id: str
    dimension: str
    annotator_id: str  # initials or role; never a full name, this file may be released
    score: Optional[Score] = None
    insufficient_evidence: bool = False
    pool: Literal["probe", "acquire"]
    round_index: int = Field(ge=0, default=0)
    adjudicated: bool = False
    notes: str = ""
    created_at: str = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def _abstention_consistency(self) -> "HumanLabel":
        if self.insufficient_evidence != (self.score is None):
            raise ValueError("score must be null if and only if insufficient_evidence is true")
        return self


class CalibrationMap(Strict):
    """A fitted monotone map from panel score to expected human score."""

    schema_version: Literal["1"] = SCHEMA_VERSION
    calibration_map_id: str
    dimension: str
    kind: Literal["isotonic", "affine", "identity"]
    params: Dict[str, Any] = Field(default_factory=dict)
    n_pairs: int = Field(ge=0)
    n_folds: int = Field(ge=0)
    out_of_fold_mae: float = Field(ge=0.0)
    out_of_fold_mae_sd: float = Field(ge=0.0)
    usable: bool
    created_at: str = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def _usability_matches_error(self) -> "CalibrationMap":
        # Architecture Algorithm 3: above 0.5 levels of out-of-fold error, the honest output is
        # "judge not calibratable at useful resolution". That is a finding, not a failure, and
        # it must not be silently overridden.
        if self.usable and self.out_of_fold_mae > 0.5:
            raise ValueError(
                f"out_of_fold_mae {self.out_of_fold_mae:.3f} exceeds 0.5 levels; "
                "this map is not usable at useful resolution"
            )
        return self


# ---------------------------------------------------------------------------
# L5: measurement identity
# ---------------------------------------------------------------------------
class MeasurementVersion(Strict):
    """Everything that changes what a number MEANS.

    ``report.py`` raises on any attempt to compare or pool across differing values. This is the
    architecture's "refuses to compare across incompatible measurement versions" made
    mechanical rather than remembered.
    """

    corpus_fingerprint: str
    rubric_hash: str
    prompt_hash: str
    judge_set: Tuple[str, ...]  # sorted pinned model ids
    aggregation_version: str
    k: int = Field(ge=1)
    temperature: float = Field(ge=0.0)
    # The SHAPE of a verdict, not just the prompt that asked for it.
    #
    # Without this, reordering the verdict fields changes what every judge emits while leaving
    # every measurement version byte-identical - so the report would compare before and after as
    # though nothing had happened. That is exactly the silent incomparability this class exists
    # to prevent, and it was invisible until the evidence-locking change went to land.
    #
    # Defaulted so historical manifests still load; a run that omits it is flagged rather than
    # silently treated as matching.
    verdict_schema_hash: str = "unversioned"

    @model_validator(mode="after")
    def _judge_set_is_sorted(self) -> "MeasurementVersion":
        if list(self.judge_set) != sorted(self.judge_set):
            raise ValueError("judge_set must be sorted so equal panels compare equal")
        if len(set(self.judge_set)) != len(self.judge_set):
            raise ValueError("judge_set contains duplicates")
        return self

    @property
    def version_id(self) -> str:
        return stable_hash(self.model_dump(mode="json"))

    def assert_comparable(self, other: "MeasurementVersion") -> None:
        """Raise unless two results measure the same thing."""
        if self == other:
            return
        mine = self.model_dump(mode="json")
        theirs = other.model_dump(mode="json")
        differing = [k for k in mine if mine[k] != theirs[k]]
        raise IncompatibleMeasurement(
            "refusing to compare results across incompatible measurement versions; "
            f"differing fields: {', '.join(differing)}"
        )


class IncompatibleMeasurement(RuntimeError):
    """Raised when two results that cannot be compared are compared anyway."""


class RunManifest(Strict):
    """Provenance for one run. Invariant 1: no result is written without one."""

    schema_version: Literal["1"] = SCHEMA_VERSION
    run_id: str
    corpus_fingerprint: str
    dataset_version: str
    measurement_version: MeasurementVersion
    rubric_version: Optional[str] = None
    git_sha: Optional[str] = None
    systems: List[str] = Field(default_factory=list)
    judge_ids: List[str] = Field(default_factory=list)
    samples_per_judge: int = Field(ge=1, default=1)
    seed: int = 0
    budget_usd: Optional[float] = None
    spent_usd: float = 0.0
    created_at: str = Field(default_factory=utcnow)
    notes: str = ""

    @model_validator(mode="after")
    def _fingerprints_agree(self) -> "RunManifest":
        if self.corpus_fingerprint != self.measurement_version.corpus_fingerprint:
            raise ValueError(
                "manifest corpus_fingerprint disagrees with its own measurement version"
            )
        return self
