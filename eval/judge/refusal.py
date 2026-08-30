"""Refusal, reported as two numbers instead of one.

WHY ONE NUMBER IS NOT ENOUGH
----------------------------
The current harness scores refusal only on the twelve questions the bot should refuse. A bot that
refused *everything* would score perfectly on that metric while being useless.

Refusal has two failure directions and they trade off against each other:

* **Under-refusal** - answering a question it should have declined. Measured on the negatives.
* **Over-refusal** - declining a question it could have answered. Measured on the answerables,
  and completely invisible to the current metric.

So both are always reported together. Either alone is uninterpretable, and reporting only the
first is what makes "refuse everything" look like a winning strategy.

The rubric already scores refusal appropriateness across every category, which is what makes
this computable at all. This module reads those verdicts and reports the pair.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from eval.judge.schemas import Response, Verdict

NEGATIVE_CATEGORY = "out_of_scope_negative"

# On the 4-point scale, a refusal decision scoring 3 or 4 is "correct decision, appropriately
# handled". Below that the judge is saying the decision itself was wrong.
CORRECT_THRESHOLD = 3


@dataclass
class RefusalReport:
    """Both sides of the refusal trade-off, plus the counts behind them."""

    n_negatives: int
    n_answerable: int
    correct_refusals: int
    correct_answers: int
    n_negatives_scored: int = 0
    n_answerable_scored: int = 0

    @property
    def abstention_recall(self) -> Optional[float]:
        """Of the questions it should refuse, how many did it refuse correctly?

        The number the current harness already reports.
        """
        if not self.n_negatives_scored:
            return None
        return self.correct_refusals / self.n_negatives_scored

    @property
    def over_refusal_rate(self) -> Optional[float]:
        """Of the questions it could answer, how many did it wrongly decline?

        The number the current harness cannot see at all.
        """
        if not self.n_answerable_scored:
            return None
        return 1.0 - (self.correct_answers / self.n_answerable_scored)

    @property
    def balanced(self) -> Optional[float]:
        """Mean of the two recalls. One summary number, only ever shown beside the pair.

        Deliberately not the headline: a single number hides which direction the system fails in,
        and the two directions have very different consequences for a policy assistant.
        """
        recall = self.abstention_recall
        over = self.over_refusal_rate
        if recall is None or over is None:
            return None
        return (recall + (1.0 - over)) / 2.0

    @property
    def verdict(self) -> str:
        recall = self.abstention_recall
        over = self.over_refusal_rate
        if recall is None or over is None:
            return "not enough scored items on both sides to report the trade-off"
        if recall >= 0.9 and over <= 0.1:
            return f"refuses well in both directions ({recall:.0%} caught, {over:.0%} over-refused)"
        if recall >= 0.9 and over > 0.25:
            return (
                f"catches {recall:.0%} of what it should refuse, but wrongly declines "
                f"{over:.0%} of answerable questions - the refusal metric alone would have "
                "called this a success"
            )
        if recall < 0.7:
            return f"answers {1 - recall:.0%} of questions it should have refused"
        return f"{recall:.0%} caught, {over:.0%} over-refused"

    def to_dict(self) -> Dict[str, object]:
        return {
            "n_negatives": self.n_negatives,
            "n_answerable": self.n_answerable,
            "n_negatives_scored": self.n_negatives_scored,
            "n_answerable_scored": self.n_answerable_scored,
            "abstention_recall": self.abstention_recall,
            "over_refusal_rate": self.over_refusal_rate,
            "balanced": self.balanced,
            "verdict": self.verdict,
        }


def refusal_report(
    verdicts: Sequence[Verdict],
    responses: Sequence[Response],
    dimension: str = "refusal_appropriateness",
    threshold: int = CORRECT_THRESHOLD,
) -> RefusalReport:
    """Score both directions of refusal from panel verdicts.

    Abstentions are excluded from the denominators rather than counted as failures - a judge
    declining to score is not evidence the system refused wrongly. The scored counts are reported
    separately so the denominator is visible.
    """

    # `is_negative` reads the item's explicit should_refuse flag where it has one and falls back
    # to the category otherwise. Splitting on the category alone put all 30 gold items in
    # `answerable`, because the gold set's categories are topics - so the five refusal items were
    # scored as though they should have been answered, and the report still looked clean.
    is_negative = {r.response_id: r.is_negative for r in responses}

    negatives = [r for r in responses if r.is_negative]
    answerable = [r for r in responses if not r.is_negative]

    correct_refusals = correct_answers = 0
    negatives_scored = answerable_scored = 0

    for verdict in verdicts:
        judgement = verdict.dimensions.get(dimension)
        if judgement is None or judgement.score is None:
            continue
        negative = is_negative.get(verdict.response_id)
        if negative is None:
            continue
        if negative:
            negatives_scored += 1
            if judgement.score >= threshold:
                correct_refusals += 1
        else:
            answerable_scored += 1
            if judgement.score >= threshold:
                correct_answers += 1

    return RefusalReport(
        n_negatives=len(negatives),
        n_answerable=len(answerable),
        correct_refusals=correct_refusals,
        correct_answers=correct_answers,
        n_negatives_scored=negatives_scored,
        n_answerable_scored=answerable_scored,
    )


# ---------------------------------------------------------------------------
# Length control
# ---------------------------------------------------------------------------
@dataclass
class LengthEffect:
    """How much of a score is explained by answer length rather than answer quality.

    Verbosity bias is exploitable: null models that only pad achieve high win rates against real
    systems. This is a regression at analysis time, so it costs nothing beyond what has already
    been run.

    UNDERPOWERED AT THE CURRENT BENCHMARK SIZE. At 60 items across six categories, the
    length-adjusted estimate has an interval wide enough to be uninformative. Report it, read the
    correlation, and do not lean on the adjusted number until the benchmark reaches 150-200.
    """

    n_items: int
    correlation: Optional[float]
    slope: Optional[float]
    raw_mean: Optional[float]
    adjusted_mean: Optional[float]
    mean_length: float

    @property
    def underpowered(self) -> bool:
        return self.n_items < 100

    @property
    def verdict(self) -> str:
        if self.correlation is None:
            return "not enough scored items to estimate a length effect"
        strength = abs(self.correlation)
        caveat = " (underpowered at this benchmark size)" if self.underpowered else ""
        if strength < 0.2:
            return f"little length effect, r={self.correlation:+.2f}{caveat}"
        if strength < 0.5:
            return f"moderate length effect, r={self.correlation:+.2f}{caveat}"
        return (
            f"strong length effect, r={self.correlation:+.2f} - scores track how much was "
            f"written more than what was written{caveat}"
        )

    def to_dict(self) -> Dict[str, object]:
        return {
            "n_items": self.n_items,
            "correlation": self.correlation,
            "slope": self.slope,
            "raw_mean": self.raw_mean,
            "adjusted_mean": self.adjusted_mean,
            "mean_length_words": self.mean_length,
            "underpowered": self.underpowered,
            "verdict": self.verdict,
        }


def answer_length(response: Response) -> int:
    """Length in words. Words rather than characters, because that is what a reader perceives."""
    return len(response.answer.split())


def length_effect(
    verdicts: Sequence[Verdict],
    responses: Sequence[Response],
    dimension: Optional[str] = None,
) -> LengthEffect:
    """Correlate panel score against answer length, and report the length-adjusted mean.

    The adjusted mean is the counterfactual: what the mean score would be if every answer were
    the same length. A large gap between raw and adjusted means the ranking is partly a ranking
    of verbosity.
    """
    lengths_by_response = {r.response_id: answer_length(r) for r in responses}

    pairs: List[Tuple[float, float]] = []
    for verdict in verdicts:
        length = lengths_by_response.get(verdict.response_id)
        if length is None:
            continue
        scores = [
            d.score
            for name, d in verdict.dimensions.items()
            if d.score is not None and (dimension is None or name == dimension)
        ]
        if scores:
            pairs.append((float(length), sum(scores) / len(scores)))

    if len(pairs) < 3:
        return LengthEffect(len(pairs), None, None, None, None, 0.0)

    lengths = [p[0] for p in pairs]
    scores = [p[1] for p in pairs]
    n = len(pairs)
    mean_length = sum(lengths) / n
    mean_score = sum(scores) / n

    variance = sum((x - mean_length) ** 2 for x in lengths)
    if variance == 0:
        # Every answer the same length; nothing to attribute.
        return LengthEffect(n, None, None, mean_score, mean_score, mean_length)

    covariance = sum((x - mean_length) * (y - mean_score) for x, y in pairs)
    slope = covariance / variance
    score_variance = sum((y - mean_score) ** 2 for y in scores)
    correlation = (
        covariance / (variance ** 0.5 * score_variance ** 0.5) if score_variance else None
    )

    # At the mean length the regression passes through the mean score, so the adjusted mean is
    # the raw mean. What the slope buys is the ability to say how much of an individual item's
    # score is length rather than quality.
    return LengthEffect(
        n_items=n,
        correlation=correlation,
        slope=slope,
        raw_mean=mean_score,
        adjusted_mean=mean_score,
        mean_length=mean_length,
    )


def length_adjusted_scores(
    verdicts: Sequence[Verdict],
    responses: Sequence[Response],
    dimension: Optional[str] = None,
) -> Dict[str, float]:
    """Per-response scores with the length trend removed.

    ``adjusted = raw - slope * (length - mean_length)``. What each answer would have scored if it
    had been of average length.
    """
    effect = length_effect(verdicts, responses, dimension)
    if effect.slope is None:
        return {}

    lengths = {r.response_id: answer_length(r) for r in responses}
    adjusted: Dict[str, float] = {}
    for verdict in verdicts:
        length = lengths.get(verdict.response_id)
        if length is None:
            continue
        scores = [
            d.score
            for name, d in verdict.dimensions.items()
            if d.score is not None and (dimension is None or name == dimension)
        ]
        if not scores:
            continue
        raw = sum(scores) / len(scores)
        adjusted[verdict.response_id] = raw - effect.slope * (length - effect.mean_length)
    return adjusted
