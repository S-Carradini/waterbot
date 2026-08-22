"""L4: agreement statistics, and the human ceiling that makes them interpretable.

WHY THESE ARE IMPLEMENTED HERE RATHER THAN IMPORTED
---------------------------------------------------
Krippendorff's alpha and Gwet's AC2 each need one package (``krippendorff``, ``irrCAC``) for
roughly forty lines of arithmetic. Implementing them keeps ``eval/judge/`` dependency-light like
the rest of the package, and makes the estimator visible - which matters, because every one of
these has a convention that changes the answer and is easy to get silently wrong. Both are
golden-tested against their authors' published worked examples.

THE ONE THING THIS MODULE EXISTS TO PREVENT
-------------------------------------------
Cohen's kappa collapses toward zero under high prevalence even at very high raw agreement - the
kappa paradox. The out-of-scope negative set is exactly that: heavily imbalanced, and the
dimension the current judge handles best. Reporting kappa alone there would make a good judge
look broken.

So agreement is always reported as a set: raw agreement, quadratic weighted kappa, Gwet's AC2,
and - for anything with three or more raters, ordinal scores or missing data - Krippendorff's
alpha. ``AgreementReport`` bundles them so no single number can travel alone.

ABSTENTIONS ARE MISSING, NEVER IMPUTED
--------------------------------------
Every function takes ``None`` for "this rater did not score this item" and handles it natively.
Alpha in particular was chosen by the architecture precisely because it tolerates missing data;
filling those cells would throw away the reason for choosing it.

Pure and network-free.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

Rating = Optional[float]
Matrix = Sequence[Sequence[Rating]]  # rows = raters, columns = units


class AgreementError(ValueError):
    """Raised when a statistic is asked for on data that cannot support it."""


# ---------------------------------------------------------------------------
# Difference functions
# ---------------------------------------------------------------------------
def _nominal_delta(a: float, b: float, *_: object) -> float:
    return 0.0 if a == b else 1.0


def _interval_delta(a: float, b: float, *_: object) -> float:
    return (a - b) ** 2


def _ordinal_delta(a: float, b: float, values: Sequence[float], counts: Dict[float, float]) -> float:
    """Krippendorff's ordinal metric.

    delta^2(c, k) = ( sum of marginal counts from rank c to rank k, minus half of the two
    endpoint counts ) squared.

    The rank distance depends on how many observations fall BETWEEN the two levels, not on the
    numeric gap. Two adjacent levels that almost nobody used are close together; two adjacent
    levels with a crowd between them are far apart. That is what makes it ordinal rather than
    interval, and it is the part an implementation usually gets wrong.
    """
    if a == b:
        return 0.0
    low, high = (a, b) if a < b else (b, a)
    total = 0.0
    for value in values:
        if low <= value <= high:
            total += counts[value]
    total -= (counts[low] + counts[high]) / 2.0
    return total ** 2


_DELTAS = {
    "nominal": _nominal_delta,
    "ordinal": _ordinal_delta,
    "interval": _interval_delta,
}


# ---------------------------------------------------------------------------
# Krippendorff's alpha
# ---------------------------------------------------------------------------
def krippendorff_alpha(
    matrix: Matrix,
    level_of_measurement: str = "ordinal",
) -> Optional[float]:
    """Krippendorff's alpha over units (columns) rated by coders (rows).

    Returns ``None`` when alpha is undefined: fewer than two units carry two or more ratings, or
    every observation is the same value. The second case is worth pausing on - with no variation
    at all, expected disagreement is zero and alpha is 0/0. Reporting 1.0 there would claim
    perfect reliability from data that could not have detected disagreement, so this returns
    ``None`` and leaves the caller to say "no variation to measure".

    ``None`` entries are missing and are simply not counted, which is why the architecture chose
    alpha over kappa for a design with abstentions.
    """
    if level_of_measurement not in _DELTAS:
        raise AgreementError(
            f"unknown level_of_measurement {level_of_measurement!r}; "
            f"expected one of {sorted(_DELTAS)}"
        )
    if not matrix:
        raise AgreementError("cannot compute alpha on an empty matrix")

    widths = {len(row) for row in matrix}
    if len(widths) != 1:
        raise AgreementError(f"every rater must cover the same units; row widths {sorted(widths)}")

    n_units = widths.pop()
    if n_units == 0:
        raise AgreementError("cannot compute alpha with no units")

    # Coincidence matrix: every ordered pair of ratings within a unit, weighted by 1/(m_u - 1).
    coincidences: Dict[Tuple[float, float], float] = {}
    for unit in range(n_units):
        observed = [row[unit] for row in matrix if row[unit] is not None]
        m_u = len(observed)
        if m_u < 2:
            continue  # a unit rated once tells us nothing about agreement
        weight = 1.0 / (m_u - 1)
        for i, first in enumerate(observed):
            for j, second in enumerate(observed):
                if i == j:
                    continue
                key = (float(first), float(second))
                coincidences[key] = coincidences.get(key, 0.0) + weight

    if not coincidences:
        return None

    marginals: Dict[float, float] = {}
    for (first, second), weight in coincidences.items():
        marginals[first] = marginals.get(first, 0.0) + weight
    total = sum(marginals.values())
    if total <= 1:
        return None

    values = sorted(marginals)
    delta = _DELTAS[level_of_measurement]

    observed_disagreement = sum(
        weight * delta(first, second, values, marginals)
        for (first, second), weight in coincidences.items()
    )
    expected_disagreement = 0.0
    for first in values:
        for second in values:
            if first == second:
                pairs = marginals[first] * (marginals[first] - 1)
            else:
                pairs = marginals[first] * marginals[second]
            expected_disagreement += pairs * delta(first, second, values, marginals)
    expected_disagreement /= total - 1

    if expected_disagreement == 0:
        return None  # no variation at all; alpha is 0/0, not 1.0
    return 1.0 - observed_disagreement / expected_disagreement


# ---------------------------------------------------------------------------
# Cohen's kappa
# ---------------------------------------------------------------------------
def cohens_kappa(
    a: Sequence[Rating],
    b: Sequence[Rating],
    weights: Optional[str] = None,
) -> Optional[float]:
    """Cohen's kappa between two raters, optionally linear or quadratic weighted.

    Pairs where either rater abstained are dropped, since kappa has no missing-data channel.
    The number of pairs actually used should always be reported alongside.

    Returns ``None`` when kappa is undefined: no complete pairs, or expected agreement of exactly
    1, which happens when both raters used a single category throughout.
    """
    if len(a) != len(b):
        raise AgreementError(f"raters must cover the same items, got {len(a)} and {len(b)}")
    if weights not in (None, "linear", "quadratic"):
        raise AgreementError(f"unknown weights {weights!r}")

    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if not pairs:
        return None

    categories = sorted({value for pair in pairs for value in pair})
    if len(categories) == 1:
        # Both raters used one category for everything. Agreement is perfect and expected
        # agreement is also perfect, so kappa is 0/0.
        return None

    index = {category: position for position, category in enumerate(categories)}
    size = len(categories)
    n = len(pairs)

    def weight(i: int, j: int) -> float:
        if weights is None:
            return 0.0 if i == j else 1.0
        distance = abs(categories[i] - categories[j])
        span = categories[-1] - categories[0]
        if span == 0:
            return 0.0
        if weights == "linear":
            return distance / span
        return (distance / span) ** 2

    observed = [[0.0] * size for _ in range(size)]
    for x, y in pairs:
        observed[index[x]][index[y]] += 1.0 / n

    rows = [sum(row) for row in observed]
    columns = [sum(observed[i][j] for i in range(size)) for j in range(size)]

    observed_disagreement = sum(
        weight(i, j) * observed[i][j] for i in range(size) for j in range(size)
    )
    expected_disagreement = sum(
        weight(i, j) * rows[i] * columns[j] for i in range(size) for j in range(size)
    )
    if expected_disagreement == 0:
        return None
    return 1.0 - observed_disagreement / expected_disagreement


# ---------------------------------------------------------------------------
# Gwet's AC1 / AC2
# ---------------------------------------------------------------------------
def gwet_ac(matrix: Matrix, weights: Optional[str] = "quadratic") -> Optional[float]:
    """Gwet's AC1 (unweighted) or AC2 (weighted) for any number of raters.

    The reason this is reported alongside kappa. Kappa's chance-agreement term is a product of
    marginals, which grows toward 1 as one category dominates, so kappa collapses toward 0 - or
    below it - even at 94% raw agreement. Gwet's chance term instead asks how often raters would
    agree by chance on the categories that are genuinely hard to call, and stays stable under
    imbalance.

    Returns ``None`` when no unit has two or more ratings, or when only one category was used.
    """
    if weights not in (None, "linear", "quadratic"):
        raise AgreementError(f"unknown weights {weights!r}")
    if not matrix:
        raise AgreementError("cannot compute AC on an empty matrix")

    widths = {len(row) for row in matrix}
    if len(widths) != 1:
        raise AgreementError(f"every rater must cover the same units; row widths {sorted(widths)}")
    n_units = widths.pop()

    columns = []
    for unit in range(n_units):
        observed = [row[unit] for row in matrix if row[unit] is not None]
        if len(observed) >= 2:
            columns.append([float(v) for v in observed])
    if not columns:
        return None

    categories = sorted({value for column in columns for value in column})
    q = len(categories)
    if q < 2:
        return None

    def weight(x: float, y: float) -> float:
        if weights is None:
            return 1.0 if x == y else 0.0
        distance = abs(x - y)
        span = categories[-1] - categories[0]
        if span == 0:
            return 1.0
        if weights == "linear":
            return 1.0 - distance / span
        return 1.0 - (distance / span) ** 2

    # Observed weighted agreement, averaged over units.
    agreements = []
    for column in columns:
        counts = Counter(column)
        r = len(column)
        total = 0.0
        for k in categories:
            for l in categories:
                n_k = counts.get(k, 0)
                n_l = counts.get(l, 0)
                total += weight(k, l) * n_k * (n_l - (1 if k == l else 0))
        agreements.append(total / (r * (r - 1)))
    p_a = sum(agreements) / len(agreements)

    # Chance agreement: category prevalence averaged over units.
    pi: Dict[float, float] = {}
    for category in categories:
        share = sum(
            sum(1 for value in column if value == category) / len(column) for column in columns
        )
        pi[category] = share / len(columns)

    t_w = sum(weight(k, l) for k in categories for l in categories)
    p_e = (t_w / (q * (q - 1))) * sum(pi[k] * (1 - pi[k]) for k in categories)

    if p_e >= 1:
        return None
    return (p_a - p_e) / (1 - p_e)


# ---------------------------------------------------------------------------
# Score-level correspondence
# ---------------------------------------------------------------------------
def spearman_rho(a: Sequence[Rating], b: Sequence[Rating]) -> Optional[float]:
    """Spearman rank correlation, with midranks for ties.

    Rank agreement without assuming the four-point scale has equal intervals - which it does not,
    since the anchors are observable conditions rather than measured quantities.
    """
    if len(a) != len(b):
        raise AgreementError(f"series must be the same length, got {len(a)} and {len(b)}")
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if len(pairs) < 2:
        return None

    def ranks(values: Sequence[float]) -> List[float]:
        order = sorted(range(len(values)), key=lambda i: values[i])
        result = [0.0] * len(values)
        position = 0
        while position < len(order):
            end = position
            while end + 1 < len(order) and values[order[end + 1]] == values[order[position]]:
                end += 1
            midrank = (position + end) / 2.0 + 1.0
            for k in range(position, end + 1):
                result[order[k]] = midrank
            position = end + 1
        return result

    x_ranks = ranks([p[0] for p in pairs])
    y_ranks = ranks([p[1] for p in pairs])
    n = len(pairs)
    mean_x = sum(x_ranks) / n
    mean_y = sum(y_ranks) / n
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in zip(x_ranks, y_ranks))
    variance_x = sum((x - mean_x) ** 2 for x in x_ranks)
    variance_y = sum((y - mean_y) ** 2 for y in y_ranks)
    if variance_x == 0 or variance_y == 0:
        return None  # one series is constant; correlation is undefined
    return covariance / math.sqrt(variance_x * variance_y)


def mae_in_levels(a: Sequence[Rating], b: Sequence[Rating]) -> Optional[float]:
    """Mean absolute error, in scale levels.

    The one agreement number a non-statistician can act on: "off by 0.4 of a level".
    """
    if len(a) != len(b):
        raise AgreementError(f"series must be the same length, got {len(a)} and {len(b)}")
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if not pairs:
        return None
    return sum(abs(x - y) for x, y in pairs) / len(pairs)


def balanced_accuracy(truth: Sequence[Rating], predicted: Sequence[Rating]) -> Optional[float]:
    """Mean of per-class recall. Robust to the negative set's class imbalance.

    Plain accuracy on a set that is 90% one class is mostly a report of the prevalence. Balanced
    accuracy asks how well each class is recovered and averages, so a judge that never predicts
    the rare class cannot score well by ignoring it.
    """
    if len(truth) != len(predicted):
        raise AgreementError("truth and predictions must be the same length")
    pairs = [(t, p) for t, p in zip(truth, predicted) if t is not None and p is not None]
    if not pairs:
        return None

    recalls = []
    for category in sorted({t for t, _ in pairs}):
        actual = [(t, p) for t, p in pairs if t == category]
        recalls.append(sum(1 for _, p in actual if p == category) / len(actual))
    return sum(recalls) / len(recalls) if recalls else None


def raw_agreement(a: Sequence[Rating], b: Sequence[Rating]) -> Optional[float]:
    """Share of complete pairs where the two raters gave the same score.

    Always reported next to kappa, because the gap between them is the paradox made visible.
    """
    if len(a) != len(b):
        raise AgreementError("raters must cover the same items")
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if not pairs:
        return None
    return sum(1 for x, y in pairs if x == y) / len(pairs)


# ---------------------------------------------------------------------------
# The human ceiling
# ---------------------------------------------------------------------------
@dataclass
class AgreementReport:
    """Agreement as a set of numbers, because no one of them survives alone.

    ``n_pairs`` and ``n_missing`` are part of the report, not footnotes: every statistic here is
    computed on complete observations only, and a reader cannot judge the rest without knowing
    how much was dropped.
    """

    label: str
    n_units: int
    n_raters: int
    n_pairs: int
    n_missing: int
    raw: Optional[float] = None
    kappa_quadratic: Optional[float] = None
    kappa_unweighted: Optional[float] = None
    gwet_ac2: Optional[float] = None
    alpha_ordinal: Optional[float] = None
    spearman: Optional[float] = None
    mae: Optional[float] = None
    balanced_accuracy: Optional[float] = None

    @property
    def missing_rate(self) -> float:
        cells = self.n_units * self.n_raters
        return self.n_missing / cells if cells else 0.0

    @property
    def kappa_paradox_suspected(self) -> bool:
        """High raw agreement with near-zero kappa: the signature of prevalence collapse.

        When this is true, kappa is measuring the class balance rather than the raters, and
        Gwet's AC2 is the number to read.
        """
        if self.raw is None or self.kappa_quadratic is None:
            return False
        return self.raw >= 0.80 and self.kappa_quadratic < 0.40

    def to_dict(self) -> Dict[str, object]:
        return {
            "label": self.label,
            "n_units": self.n_units,
            "n_raters": self.n_raters,
            "n_pairs": self.n_pairs,
            "n_missing": self.n_missing,
            "missing_rate": self.missing_rate,
            "raw_agreement": self.raw,
            "kappa_quadratic": self.kappa_quadratic,
            "kappa_unweighted": self.kappa_unweighted,
            "gwet_ac2": self.gwet_ac2,
            "alpha_ordinal": self.alpha_ordinal,
            "spearman": self.spearman,
            "mae_levels": self.mae,
            "balanced_accuracy": self.balanced_accuracy,
            "kappa_paradox_suspected": self.kappa_paradox_suspected,
        }


def agreement_report(matrix: Matrix, label: str = "") -> AgreementReport:
    """Every agreement statistic that applies to this matrix, computed together.

    Pairwise statistics are computed on the first two raters; multi-rater statistics use all of
    them. With three or more raters, alpha and AC2 are the interpretable ones and the pairwise
    numbers are there for comparability with prior work.
    """
    if not matrix:
        raise AgreementError("cannot report agreement on an empty matrix")
    widths = {len(row) for row in matrix}
    if len(widths) != 1:
        raise AgreementError("every rater must cover the same units")

    n_units = widths.pop()
    n_raters = len(matrix)
    n_missing = sum(1 for row in matrix for value in row if value is None)

    first = matrix[0]
    second = matrix[1] if n_raters > 1 else None
    complete = (
        sum(1 for x, y in zip(first, second) if x is not None and y is not None)
        if second is not None
        else 0
    )

    return AgreementReport(
        label=label,
        n_units=n_units,
        n_raters=n_raters,
        n_pairs=complete,
        n_missing=n_missing,
        raw=raw_agreement(first, second) if second is not None else None,
        kappa_quadratic=cohens_kappa(first, second, "quadratic") if second is not None else None,
        kappa_unweighted=cohens_kappa(first, second) if second is not None else None,
        gwet_ac2=gwet_ac(matrix, "quadratic"),
        alpha_ordinal=krippendorff_alpha(matrix, "ordinal"),
        spearman=spearman_rho(first, second) if second is not None else None,
        mae=mae_in_levels(first, second) if second is not None else None,
    )


@dataclass
class CeilingComparison:
    """A judge's agreement set beside the humans', on the same units.

    THE POINT OF THE WHOLE LAYER. Inter-human agreement bounds what any judge can achieve. If
    three experts agree at alpha 0.68, a judge at 0.65 is performing near ceiling, not failing.
    Reporting judge agreement without the human ceiling is uninterpretable, and it is a common
    weakness in this literature that costs nothing to avoid.
    """

    dimension: str
    human: AgreementReport
    judge: AgreementReport

    @property
    def ceiling(self) -> Optional[float]:
        return self.human.alpha_ordinal

    @property
    def attained(self) -> Optional[float]:
        return self.judge.alpha_ordinal

    @property
    def fraction_of_ceiling(self) -> Optional[float]:
        """How much of the achievable agreement the judge reached.

        Undefined when the humans themselves did not agree above chance: dividing by a ceiling at
        or below zero would manufacture a ratio out of a floor.
        """
        if self.ceiling is None or self.attained is None or self.ceiling <= 0:
            return None
        return self.attained / self.ceiling

    @property
    def verdict(self) -> str:
        if self.ceiling is None or self.attained is None:
            return "not enough data to compare"
        if self.ceiling <= 0:
            return "humans did not agree above chance; the ceiling is undefined and no judge " \
                   "result on this dimension is interpretable"
        fraction = self.attained / self.ceiling
        if fraction >= 0.95:
            return "at the human ceiling"
        if fraction >= 0.80:
            return "near the human ceiling"
        if fraction >= 0.50:
            return "materially below the human ceiling"
        return "far below the human ceiling"

    def to_dict(self) -> Dict[str, object]:
        return {
            "dimension": self.dimension,
            "human_ceiling": self.ceiling,
            "judge_attained": self.attained,
            "fraction_of_ceiling": self.fraction_of_ceiling,
            "verdict": self.verdict,
            "human": self.human.to_dict(),
            "judge": self.judge.to_dict(),
        }


def compare_to_ceiling(
    human_matrix: Matrix,
    judge_matrix: Matrix,
    dimension: str,
) -> CeilingComparison:
    """Compute the human ceiling and the judge's attainment against it.

    ``human_matrix`` must be PRE-adjudication labels. Adjudicated labels have had their
    disagreements resolved by a fourth reviewer, so agreement computed on them is agreement with
    the adjudication process rather than between the annotators, and it would overstate the
    ceiling.
    """
    return CeilingComparison(
        dimension=dimension,
        human=agreement_report(human_matrix, label=f"{dimension} (humans)"),
        judge=agreement_report(judge_matrix, label=f"{dimension} (judges)"),
    )
