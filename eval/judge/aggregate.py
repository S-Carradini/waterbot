"""L3: turning panel votes into scores that carry their own uncertainty.

Per ``(response, dimension)``: drop abstentions, check whether enough of the panel actually
answered, then compute the centre and the spread. The spread is not diagnostics. It is the
error bar, and it is the whole reason the panel exists.

WHY MEDIAN AND MEAN BOTH
------------------------
The median is the reported centre: robust to one judge being wildly off, and it stays on the
four-point scale annotators were trained on. The mean is what feeds calibration, because
isotonic regression on integer medians has at most four support points and degenerates into a
lookup table (spec 0.5). They are different tools and both are recorded.

WHY DISAGREEMENT IS ROUTED, NOT AVERAGED
----------------------------------------
When a panel splits down the middle, the average is a number no judge actually gave. Averaging
it away manufactures false precision on exactly the items where the measurement is weakest. So
high-spread items escalate to human adjudication and are counted, which turns the panel's
uncertainty into a work queue instead of a silent error.

ALPHA IS NOT COMPUTED HERE
--------------------------
Krippendorff's alpha compares observed disagreement to expected disagreement, and expected
disagreement is estimated from the spread across units. On a single item it is undefined or an
implementation artifact (spec 0.1). This module builds the ``judges x items`` matrix that alpha
needs; alpha itself is computed at the dimension level in L4.

Pure and network-free.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from eval.judge.schemas import DimensionAggregate, Verdict

# Bumped when aggregation semantics change. Part of the measurement version, because a change
# here changes what every downstream number means.
AGGREGATION_VERSION = "1.0.0"

# Defaults for escalation. Deliberately explicit rather than tuned: everything escalating means
# tau is too tight, nothing escalating means it is too loose or the panel has collapsed to one
# opinion. Both are findings about the panel, not knobs to make the output look tidy.
DEFAULT_IQR_THRESHOLD = 1.0
DEFAULT_ENTROPY_THRESHOLD = 0.75
SCALE_LEVELS = 4


def _quantile(values: Sequence[float], q: float) -> float:
    """Linear-interpolation quantile, matching numpy's default.

    Implemented directly so this module has no hard numpy dependency and so the definition is
    visible: with m*k around 15 votes, the choice of quantile convention visibly moves the IQR,
    and a silent difference between this and a reviewer's calculation would be hard to find.
    """
    if not values:
        raise ValueError("cannot take a quantile of nothing")
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = q * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return float(ordered[lower])
    weight = position - lower
    return float(ordered[lower] * (1 - weight) + ordered[upper] * weight)


def median(values: Sequence[float]) -> float:
    return _quantile(values, 0.5)


def iqr(values: Sequence[float]) -> float:
    return _quantile(values, 0.75) - _quantile(values, 0.25)


def normalised_entropy(values: Sequence[int], levels: int = SCALE_LEVELS) -> float:
    """Shannon entropy of the vote distribution, scaled to [0, 1].

    0 means the panel was unanimous, 1 means it was spread uniformly across every level. Divided
    by log(levels) rather than log(number of distinct votes observed), so the number is
    comparable across items - otherwise an item where judges used only two levels would look
    maximally uncertain for using both.
    """
    if not values:
        return 0.0
    if levels < 2:
        raise ValueError("entropy needs at least two levels to be meaningful")
    counts = Counter(values)
    total = len(values)
    entropy = -sum(
        (count / total) * math.log(count / total) for count in counts.values() if count
    )
    return entropy / math.log(levels)


# ---------------------------------------------------------------------------
# Vote extraction
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Vote:
    """One judge's score on one dimension, with the identity needed to cluster it."""

    judge_model_id: str
    sample_index: int
    score: Optional[int]  # None means the judge abstained

    @property
    def abstained(self) -> bool:
        return self.score is None


def votes_for(verdicts: Sequence[Verdict], dimension: str) -> List[Vote]:
    """Pull every vote on one dimension out of a set of verdicts.

    Abstentions come through as ``score=None`` rather than being filtered here, so the caller
    counts them before dropping them. Dropping first and counting later is how an abstention
    rate silently becomes zero.
    """
    votes: List[Vote] = []
    for verdict in verdicts:
        dimension_verdict = verdict.dimensions.get(dimension)
        if dimension_verdict is None:
            continue  # this judge was not asked about this dimension
        votes.append(
            Vote(
                judge_model_id=verdict.judge_model_id,
                sample_index=verdict.sample_index,
                score=dimension_verdict.score,
            )
        )
    return votes


# ---------------------------------------------------------------------------
# Clustered interval for one item
# ---------------------------------------------------------------------------
def judge_clustered_interval(
    votes: Sequence[Vote],
    n_boot: int = 2000,
    seed: int = 0,
    alpha: float = 0.05,
) -> Tuple[Optional[float], Optional[float]]:
    """Bootstrap interval for the panel mean, resampling JUDGES rather than votes.

    The k samples from one judge are not independent of each other - they share a model, a
    prompt and whatever that model systematically believes. Resampling individual votes would
    treat five samples from one judge as five independent opinions and produce an interval far
    too narrow. The cluster is the judge, so the judge is what gets resampled.

    Returns ``(None, None)`` when there is only one judge: with a single cluster there is
    nothing to resample and no honest interval to report.
    """
    import random

    scored = [v for v in votes if not v.abstained]
    if not scored:
        return (None, None)

    by_judge: Dict[str, List[int]] = {}
    for vote in scored:
        by_judge.setdefault(vote.judge_model_id, []).append(int(vote.score))

    judges = sorted(by_judge)
    if len(judges) < 2:
        return (None, None)

    rng = random.Random(seed)
    means: List[float] = []
    for _ in range(n_boot):
        drawn: List[int] = []
        for _ in range(len(judges)):
            drawn.extend(by_judge[judges[rng.randrange(len(judges))]])
        means.append(sum(drawn) / len(drawn))

    means.sort()
    lo_index = max(0, min(int(math.floor((alpha / 2) * n_boot)), n_boot - 1))
    hi_index = max(0, min(int(math.ceil((1 - alpha / 2) * n_boot)) - 1, n_boot - 1))
    return (means[lo_index], means[hi_index])


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------
def aggregate_dimension(
    response_id: str,
    dimension: str,
    votes: Sequence[Vote],
    expected_votes: Optional[int] = None,
    iqr_threshold: float = DEFAULT_IQR_THRESHOLD,
    entropy_threshold: float = DEFAULT_ENTROPY_THRESHOLD,
    n_boot: int = 2000,
    seed: int = 0,
) -> DimensionAggregate:
    """Collapse the panel's votes on one dimension into one scored aggregate.

    ``expected_votes`` is m*k. When fewer than half of the expected votes carry a score, the
    item escalates as ``mostly_abstained`` rather than being scored from the remainder: a
    median of two surviving votes out of fifteen is not a panel consensus, it is two opinions
    wearing one.
    """
    abstained = sum(1 for v in votes if v.abstained)
    scored = [int(v.score) for v in votes if not v.abstained]
    total_expected = expected_votes if expected_votes is not None else len(votes)

    # Not enough of the panel answered for a consensus to mean anything.
    if not scored or (total_expected and len(scored) < math.ceil(0.5 * total_expected)):
        return DimensionAggregate(
            response_id=response_id,
            dimension=dimension,
            n_votes=len(scored),
            n_abstained=abstained,
            escalate=True,
            escalation_reason="mostly_abstained",
        )

    spread = iqr(scored)
    entropy = normalised_entropy(scored)
    ci_low, ci_high = judge_clustered_interval(votes, n_boot=n_boot, seed=seed)

    disagreement = spread > iqr_threshold or entropy > entropy_threshold
    return DimensionAggregate(
        response_id=response_id,
        dimension=dimension,
        n_votes=len(scored),
        n_abstained=abstained,
        median=median(scored),
        mean=sum(scored) / len(scored),
        iqr=spread,
        entropy=entropy,
        ci_low=ci_low,
        ci_high=ci_high,
        escalate=disagreement,
        escalation_reason="panel_disagreement" if disagreement else None,
    )


def aggregate_response(
    response_id: str,
    verdicts: Sequence[Verdict],
    dimensions: Optional[Sequence[str]] = None,
    expected_votes: Optional[int] = None,
    **kwargs,
) -> List[DimensionAggregate]:
    """Aggregate every dimension the panel scored for one response."""
    if dimensions is None:
        names = sorted({name for v in verdicts for name in v.dimensions})
    else:
        names = sorted(dimensions)
    return [
        aggregate_dimension(
            response_id, name, votes_for(verdicts, name),
            expected_votes=expected_votes, **kwargs,
        )
        for name in names
    ]


def aggregate_all(
    verdicts: Sequence[Verdict],
    dimensions: Optional[Sequence[str]] = None,
    expected_votes: Optional[int] = None,
    **kwargs,
) -> List[DimensionAggregate]:
    """Aggregate a whole run, grouping verdicts by the response they judged."""
    by_response: Dict[str, List[Verdict]] = {}
    for verdict in verdicts:
        by_response.setdefault(verdict.response_id, []).append(verdict)

    aggregates: List[DimensionAggregate] = []
    for response_id in sorted(by_response):
        aggregates.extend(
            aggregate_response(
                response_id, by_response[response_id], dimensions,
                expected_votes=expected_votes, **kwargs,
            )
        )
    return aggregates


# ---------------------------------------------------------------------------
# The judges x items matrix that alpha needs
# ---------------------------------------------------------------------------
def modal_score(scores: Sequence[int]) -> Optional[int]:
    """One judge's representative score for an item across its k samples.

    Mode rather than mean, because alpha treats coders as giving one categorical or ordinal
    judgement per unit and a mean of 2.6 is not a level anyone could have assigned. Ties break
    toward the lower score, which is the conservative direction: it never invents quality that
    no sample claimed.
    """
    present = [s for s in scores if s is not None]
    if not present:
        return None
    counts = Counter(present)
    best = max(counts.values())
    return min(score for score, count in counts.items() if count == best)


@dataclass
class ReliabilityMatrix:
    """A ``judges x items`` table of modal scores, with ``None`` for abstentions.

    The input to Krippendorff's alpha at the dimension level (spec 0.1). Abstentions stay as
    ``None`` and are never imputed: alpha handles missing data natively, and that is precisely
    why the architecture chose it over kappa.
    """

    dimension: str
    judges: List[str]
    items: List[str]
    rows: List[List[Optional[int]]]  # rows[judge_index][item_index]

    @property
    def shape(self) -> Tuple[int, int]:
        return (len(self.judges), len(self.items))

    @property
    def missing(self) -> int:
        return sum(1 for row in self.rows for value in row if value is None)

    @property
    def missing_rate(self) -> float:
        cells = len(self.judges) * len(self.items)
        return self.missing / cells if cells else 0.0

    def column(self, item_id: str) -> List[Optional[int]]:
        return [row[self.items.index(item_id)] for row in self.rows]

    def to_dict(self) -> Dict[str, object]:
        return {
            "dimension": self.dimension,
            "judges": self.judges,
            "items": self.items,
            "rows": self.rows,
            "shape": list(self.shape),
            "missing": self.missing,
            "missing_rate": self.missing_rate,
        }


def build_reliability_matrix(
    verdicts: Sequence[Verdict], dimension: str
) -> ReliabilityMatrix:
    """Build the judges x items matrix of per-judge modal scores for one dimension.

    A judge that never scored an item gets ``None`` for that cell, which is different from a
    judge that scored it and abstained - but alpha treats both as missing, and conflating them
    here would be inventing information. The distinction is preserved upstream in the verdict
    log, where the abstention rate is computed.
    """
    by_judge_item: Dict[Tuple[str, str], List[int]] = {}
    judges = set()
    items = set()

    for verdict in verdicts:
        dimension_verdict = verdict.dimensions.get(dimension)
        if dimension_verdict is None:
            continue
        judges.add(verdict.judge_model_id)
        items.add(verdict.item_id)
        if dimension_verdict.score is not None:
            key = (verdict.judge_model_id, verdict.item_id)
            by_judge_item.setdefault(key, []).append(int(dimension_verdict.score))

    judge_list = sorted(judges)
    item_list = sorted(items)
    rows = [
        [modal_score(by_judge_item.get((judge, item), [])) for item in item_list]
        for judge in judge_list
    ]
    return ReliabilityMatrix(dimension, judge_list, item_list, rows)


# ---------------------------------------------------------------------------
# Run-level summary
# ---------------------------------------------------------------------------
@dataclass
class AggregationReport:
    """What the aggregation step produced, in the detail needed to judge whether to trust it."""

    aggregation_version: str
    n_aggregates: int
    n_escalated: int
    escalated_disagreement: int
    escalated_abstention: int
    mean_iqr: Optional[float]
    mean_entropy: Optional[float]
    iqr_threshold: float
    entropy_threshold: float

    @property
    def escalation_rate(self) -> float:
        return self.n_escalated / self.n_aggregates if self.n_aggregates else 0.0

    @property
    def thresholds_look_sane(self) -> bool:
        """Everything escalating means tau is too tight; nothing escalating, too loose.

        Reported rather than enforced. A rate of zero on a real panel usually means the panel has
        collapsed to a single opinion, which is a finding about the judges rather than a
        configuration error to silently correct.
        """
        return 0.0 < self.escalation_rate < 0.5

    def to_dict(self) -> Dict[str, object]:
        return {
            "aggregation_version": self.aggregation_version,
            "n_aggregates": self.n_aggregates,
            "n_escalated": self.n_escalated,
            "escalation_rate": self.escalation_rate,
            "escalated_disagreement": self.escalated_disagreement,
            "escalated_abstention": self.escalated_abstention,
            "mean_iqr": self.mean_iqr,
            "mean_entropy": self.mean_entropy,
            "iqr_threshold": self.iqr_threshold,
            "entropy_threshold": self.entropy_threshold,
            "thresholds_look_sane": self.thresholds_look_sane,
        }


def summarise_aggregates(
    aggregates: Sequence[DimensionAggregate],
    iqr_threshold: float = DEFAULT_IQR_THRESHOLD,
    entropy_threshold: float = DEFAULT_ENTROPY_THRESHOLD,
) -> AggregationReport:
    scored = [a for a in aggregates if a.iqr is not None]
    return AggregationReport(
        aggregation_version=AGGREGATION_VERSION,
        n_aggregates=len(aggregates),
        n_escalated=sum(1 for a in aggregates if a.escalate),
        escalated_disagreement=sum(
            1 for a in aggregates if a.escalation_reason == "panel_disagreement"
        ),
        escalated_abstention=sum(
            1 for a in aggregates if a.escalation_reason == "mostly_abstained"
        ),
        mean_iqr=sum(a.iqr for a in scored) / len(scored) if scored else None,
        mean_entropy=(
            sum(a.entropy for a in scored) / len(scored) if scored else None
        ),
        iqr_threshold=iqr_threshold,
        entropy_threshold=entropy_threshold,
    )
