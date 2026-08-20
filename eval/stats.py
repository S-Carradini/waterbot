"""Statistics shared across the judge layers.

Lives outside ``eval/judge/`` because L3 (aggregation), L4 (calibration) and L5 (reporting) all
need the same estimators, and because keeping them in one module means there is exactly one
implementation of each to test and to get right.

THE THREAD RUNNING THROUGH ALL OF IT
------------------------------------
The current harness reports bare point estimates and gates on a 5-point drop while exhibiting
8.3 points of noise. Every function here exists to make that impossible: intervals rather than
estimates, clustered resampling rather than iid, explicit multiplicity control, and a published
minimum detectable effect so a gate threshold narrower than the noise floor is visible as an
error rather than shipped as a standard.

DEVIATION FROM THE SPEC, RECORDED DELIBERATELY
----------------------------------------------
Spec 6.4 suggests fitting variance components with statsmodels ``MixedLM``. This module uses
classical ANOVA-based estimators (Cronbach, Brennan) instead. Two reasons: they are closed-form,
so they reproduce exactly and can be golden-tested against a published worked example, and they
do not fail to converge on the small, unbalanced samples this project will actually have. The
estimand is identical.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

# z for common two-sided intervals. Hard-coded so this module has no hard scientific-stack
# dependency; the values are checked against scipy in the tests.
Z_95 = 1.959963984540054
Z_90 = 1.6448536269514722
Z_POWER_80 = 0.8416212335729143  # z at 0.80, the conventional power target


# ---------------------------------------------------------------------------
# Proportions
# ---------------------------------------------------------------------------
def wilson_interval(successes: int, trials: int, z: float = Z_95) -> Tuple[float, float]:
    """Wilson score interval for a binomial proportion.

    Preferred over Wald because at the counts this project produces - twelve items, proportions
    that sit at or near 1.0 - Wald collapses to zero width and claims certainty. Wilson stays
    inside [0, 1] and keeps a sensible width at the boundary.

    Assumes independent trials. Where the data are clustered (votes within an item, items within
    a document family) use ``clustered_bootstrap_ci`` instead, or report both and say which is
    which.
    """
    if trials < 0:
        raise ValueError("trials must be non-negative")
    if not 0 <= successes <= trials:
        raise ValueError(f"successes ({successes}) must be in [0, trials] ({trials})")
    if trials == 0:
        return (0.0, 1.0)

    n = float(trials)
    p_hat = successes / n
    denominator = 1.0 + (z * z) / n
    centre = (p_hat + (z * z) / (2.0 * n)) / denominator
    spread = (z / denominator) * math.sqrt(p_hat * (1.0 - p_hat) / n + (z * z) / (4.0 * n * n))
    return (max(0.0, centre - spread), min(1.0, centre + spread))


# ---------------------------------------------------------------------------
# Resampling
# ---------------------------------------------------------------------------
def clustered_bootstrap(
    clusters: Sequence,
    stat_fn: Callable[[List], float],
    n_boot: int = 2000,
    seed: int = 0,
) -> List[float]:
    """Bootstrap distribution of ``stat_fn``, resampling whole clusters.

    ``scipy.stats.bootstrap`` resamples rows independently, which is wrong here: votes within a
    question are correlated, and so are items drawn from the same document family. Resampling at
    the cluster level is what keeps the interval honest (spec 6.3).

    ``clusters`` is a sequence of arbitrary objects - a list of per-item vote lists, a list of
    document groups - and ``stat_fn`` maps a resampled list of them to one number.
    """
    n = len(clusters)
    if n == 0:
        raise ValueError("cannot bootstrap an empty sample")
    if n_boot < 1:
        raise ValueError("n_boot must be positive")

    rng = random.Random(seed)
    draws: List[float] = []
    for _ in range(n_boot):
        resampled = [clusters[rng.randrange(n)] for _ in range(n)]
        draws.append(stat_fn(resampled))
    return draws


def percentile_ci(draws: Sequence[float], alpha: float = 0.05) -> Tuple[float, float]:
    """Percentile interval from a bootstrap distribution.

    Percentile is adequate at B=2000 for the quantities here. BCa would add bias correction and
    is worth it only where the statistic is visibly skewed; if that turns out to matter, it is a
    change in one place.
    """
    if not draws:
        raise ValueError("no bootstrap draws")
    if not 0 < alpha < 1:
        raise ValueError("alpha must be in (0, 1)")

    ordered = sorted(draws)
    n = len(ordered)
    lo_index = max(0, min(int(math.floor((alpha / 2.0) * n)), n - 1))
    hi_index = max(0, min(int(math.ceil((1.0 - alpha / 2.0) * n)) - 1, n - 1))
    return (ordered[lo_index], ordered[hi_index])


def clustered_bootstrap_ci(
    clusters: Sequence,
    stat_fn: Callable[[List], float],
    n_boot: int = 2000,
    seed: int = 0,
    alpha: float = 0.05,
) -> Tuple[float, float]:
    """Convenience wrapper: resample clusters, return a percentile interval."""
    return percentile_ci(clustered_bootstrap(clusters, stat_fn, n_boot, seed), alpha)


# ---------------------------------------------------------------------------
# Permutation testing
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PermutationResult:
    observed: float
    p_value: float
    n_permutations: int
    seed: int

    def to_dict(self) -> Dict[str, float]:
        return {
            "observed": self.observed,
            "p_value": self.p_value,
            "n_permutations": self.n_permutations,
            "seed": self.seed,
        }


def paired_permutation_test(
    a: Sequence[float],
    b: Sequence[float],
    n_permutations: int = 10000,
    seed: int = 0,
) -> PermutationResult:
    """Two-sided paired permutation test on the mean difference.

    For system A against system B on the same items, shuffle the system labels *within* each item
    and rebuild the null. Pairing matters: items differ far more than systems do, and an unpaired
    test throws that structure away and loses most of the power.

    No normality assumption, which is what makes it appropriate for bounded ordinal scores where
    a t-test's assumptions are visibly false.

    The p-value uses the (r + 1) / (n + 1) convention, which never returns exactly zero. A
    reported p of 0 is always a lie about resolution: with 10,000 permutations the smallest
    honest statement is p < 1e-4.
    """
    if len(a) != len(b):
        raise ValueError(f"paired test needs equal lengths, got {len(a)} and {len(b)}")
    if not a:
        raise ValueError("cannot test an empty sample")
    if n_permutations < 1:
        raise ValueError("n_permutations must be positive")

    differences = [x - y for x, y in zip(a, b)]
    observed = sum(differences) / len(differences)

    rng = random.Random(seed)
    at_least_as_extreme = 0
    for _ in range(n_permutations):
        total = 0.0
        for difference in differences:
            # Swapping the labels within a pair flips the sign of its difference.
            total += difference if rng.random() < 0.5 else -difference
        if abs(total / len(differences)) >= abs(observed) - 1e-12:
            at_least_as_extreme += 1

    p_value = (at_least_as_extreme + 1) / (n_permutations + 1)
    return PermutationResult(observed, p_value, n_permutations, seed)


# ---------------------------------------------------------------------------
# Multiplicity
# ---------------------------------------------------------------------------
def benjamini_hochberg(p_values: Sequence[float], alpha: float = 0.05) -> Tuple[List[float], List[bool]]:
    """Benjamini-Hochberg FDR adjustment.

    Returns ``(adjusted_p_values, rejected)`` in the input order.

    The test surface here is large - five dimensions times six categories times systems times
    ablation cells - and the architecture document does not address it. Families must be declared
    in code before running, and both raw and adjusted p-values reported. Implemented directly
    rather than delegated so the module stays dependency-light; it is checked against
    ``statsmodels.stats.multitest.multipletests`` in the tests.
    """
    n = len(p_values)
    if n == 0:
        return ([], [])
    if any(not 0.0 <= p <= 1.0 for p in p_values):
        raise ValueError("p-values must lie in [0, 1]")

    order = sorted(range(n), key=lambda i: p_values[i])
    adjusted = [0.0] * n

    # Step up from the largest p-value, enforcing monotonicity as we go.
    running_min = 1.0
    for rank in range(n - 1, -1, -1):
        index = order[rank]
        value = p_values[index] * n / (rank + 1)
        running_min = min(running_min, value)
        adjusted[index] = min(1.0, running_min)

    return (adjusted, [p <= alpha for p in adjusted])


# ---------------------------------------------------------------------------
# Minimum detectable effect
# ---------------------------------------------------------------------------
def minimum_detectable_effect(
    sd: float,
    n: int,
    alpha: float = 0.05,
    power: float = 0.80,
    paired: bool = True,
) -> float:
    """Smallest true difference this design can resolve, in the units of ``sd``.

    Published alongside every comparison so the paper cannot over-claim and, just as important,
    so a CI gate threshold cannot be set narrower than the noise floor. That is exactly the
    failure the current harness has: a 5-point gate on a measurement with 8.3 points of swing.

    ``sd`` is the standard deviation of the paired differences when ``paired`` is true, and the
    within-group standard deviation otherwise.
    """
    if sd < 0:
        raise ValueError("sd must be non-negative")
    if n < 2:
        raise ValueError("need at least 2 observations")
    if not 0 < alpha < 1 or not 0 < power < 1:
        raise ValueError("alpha and power must be in (0, 1)")

    z_alpha = _z_from_two_sided_alpha(alpha)
    z_power = _z_from_power(power)
    standard_error = sd / math.sqrt(n) if paired else sd * math.sqrt(2.0 / n)
    return (z_alpha + z_power) * standard_error


def _z_from_two_sided_alpha(alpha: float) -> float:
    if abs(alpha - 0.05) < 1e-12:
        return Z_95
    if abs(alpha - 0.10) < 1e-12:
        return Z_90
    return _inverse_normal_cdf(1.0 - alpha / 2.0)


def _z_from_power(power: float) -> float:
    if abs(power - 0.80) < 1e-12:
        return Z_POWER_80
    return _inverse_normal_cdf(power)


def _inverse_normal_cdf(p: float) -> float:
    """Acklam's rational approximation, refined by one Halley step.

    Accurate to well past the precision anything here reports. Present so alpha and power are not
    silently restricted to the two hard-coded values.
    """
    if not 0.0 < p < 1.0:
        raise ValueError("p must be in (0, 1)")

    a = [-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
         1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00]
    b = [-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
         6.680131188771972e01, -1.328068155288572e01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
         -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00,
         3.754408661907416e00]

    p_low, p_high = 0.02425, 1.0 - 0.02425
    if p < p_low:
        q = math.sqrt(-2.0 * math.log(p))
        x = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    elif p <= p_high:
        q = p - 0.5
        r = q * q
        x = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
            (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
    else:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        x = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)

    error = 0.5 * math.erfc(-x / math.sqrt(2.0)) - p
    u = error * math.sqrt(2.0 * math.pi) * math.exp(x * x / 2.0)
    return x - u / (1.0 + x * u / 2.0)


# ---------------------------------------------------------------------------
# Variance components (generalizability theory)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class VarianceComponents:
    """A crossed items x judges design, with k replicates per cell.

    ``sigma2_items`` is signal: real differences between the things being measured. Everything
    else is noise, and the split says which knob buys precision - more judges, or more samples
    from the judges you have. That answers RQ2 with one table instead of a sweep.
    """

    sigma2_items: float
    sigma2_judges: float
    sigma2_interaction: float
    sigma2_residual: float
    n_items: int
    n_judges: int
    n_replicates: int

    @property
    def total(self) -> float:
        return (
            self.sigma2_items + self.sigma2_judges
            + self.sigma2_interaction + self.sigma2_residual
        )

    def relative_error_variance(self, n_judges: int, n_replicates: int) -> float:
        """Error variance for a decision made by averaging over m judges and k samples."""
        if n_judges < 1 or n_replicates < 1:
            raise ValueError("n_judges and n_replicates must be at least 1")
        return (
            self.sigma2_interaction / n_judges
            + self.sigma2_residual / (n_judges * n_replicates)
        )

    def generalizability(self, n_judges: Optional[int] = None,
                         n_replicates: Optional[int] = None) -> float:
        """Coefficient in [0, 1]: the share of observed variance that is real item difference.

        The analogue of reliability. Defaults to the design as measured.
        """
        m = self.n_judges if n_judges is None else n_judges
        k = self.n_replicates if n_replicates is None else n_replicates
        error = self.relative_error_variance(m, k)
        denominator = self.sigma2_items + error
        if denominator <= 0:
            return 0.0
        return self.sigma2_items / denominator

    def decision_study(self, target: float = 0.80, max_judges: int = 8,
                       max_replicates: int = 10) -> Optional[Tuple[int, int]]:
        """Cheapest (judges, samples) reaching ``target`` reliability, or None.

        Cost is judges x samples, which is exactly the call count, so the cheapest design that
        clears the bar is the one to run. Ties break toward fewer judges, because adding a judge
        family costs integration work that adding a sample does not.
        """
        best: Optional[Tuple[int, int]] = None
        best_cost = None
        for m in range(1, max_judges + 1):
            for k in range(1, max_replicates + 1):
                if self.generalizability(m, k) >= target:
                    cost = m * k
                    if best_cost is None or cost < best_cost:
                        best, best_cost = (m, k), cost
        return best

    def to_dict(self) -> Dict[str, float]:
        return {
            "sigma2_items": self.sigma2_items,
            "sigma2_judges": self.sigma2_judges,
            "sigma2_interaction": self.sigma2_interaction,
            "sigma2_residual": self.sigma2_residual,
            "total": self.total,
            "generalizability": self.generalizability(),
            "n_items": self.n_items,
            "n_judges": self.n_judges,
            "n_replicates": self.n_replicates,
        }


def variance_components(scores: Dict[Tuple[str, str], List[float]]) -> VarianceComponents:
    """Estimate variance components for a balanced crossed items x judges design.

    ``scores`` maps ``(item_id, judge_id)`` to that cell's replicate scores. Every cell must hold
    the same number of replicates, and every judge must have scored every item; unbalanced data
    needs a mixed model rather than these closed forms, and silently averaging over a hole would
    understate the noise.

    Estimators are the classical ANOVA ones. Negative estimates are truncated at zero, which is
    standard practice and happens when a component's true value is near zero.
    """
    if not scores:
        raise ValueError("no scores supplied")

    items = sorted({item for item, _ in scores})
    judges = sorted({judge for _, judge in scores})
    n_items, n_judges = len(items), len(judges)
    if n_items < 2 or n_judges < 2:
        raise ValueError(
            f"need at least 2 items and 2 judges, got {n_items} items and {n_judges} judges"
        )

    replicate_counts = {len(v) for v in scores.values()}
    if len(replicate_counts) != 1:
        raise ValueError(f"design must be balanced; replicate counts seen: {sorted(replicate_counts)}")
    n_replicates = replicate_counts.pop()
    if n_replicates < 1:
        raise ValueError("each cell needs at least one replicate")

    missing = [(i, j) for i in items for j in judges if (i, j) not in scores]
    if missing:
        raise ValueError(f"design must be complete; {len(missing)} cells missing, e.g. {missing[0]}")

    cell_means: Dict[Tuple[str, str], float] = {
        key: sum(values) / len(values) for key, values in scores.items()
    }
    grand = sum(cell_means.values()) / len(cell_means)
    item_means = {
        i: sum(cell_means[(i, j)] for j in judges) / n_judges for i in items
    }
    judge_means = {
        j: sum(cell_means[(i, j)] for i in items) / n_items for j in judges
    }

    ss_items = n_judges * n_replicates * sum((item_means[i] - grand) ** 2 for i in items)
    ss_judges = n_items * n_replicates * sum((judge_means[j] - grand) ** 2 for j in judges)
    ss_interaction = n_replicates * sum(
        (cell_means[(i, j)] - item_means[i] - judge_means[j] + grand) ** 2
        for i in items
        for j in judges
    )
    ss_residual = sum(
        (value - cell_means[key]) ** 2 for key, values in scores.items() for value in values
    )

    df_items = n_items - 1
    df_judges = n_judges - 1
    df_interaction = df_items * df_judges
    df_residual = n_items * n_judges * (n_replicates - 1)

    ms_items = ss_items / df_items
    ms_judges = ss_judges / df_judges
    ms_interaction = ss_interaction / df_interaction
    # With one replicate per cell there is no residual df: interaction and residual are
    # confounded, and the interaction term absorbs both. Reported as residual 0 rather than
    # pretending the two can be separated.
    ms_residual = ss_residual / df_residual if df_residual > 0 else 0.0

    sigma2_residual = max(0.0, ms_residual)
    sigma2_interaction = max(0.0, (ms_interaction - ms_residual) / n_replicates)
    sigma2_items = max(0.0, (ms_items - ms_interaction) / (n_judges * n_replicates))
    sigma2_judges = max(0.0, (ms_judges - ms_interaction) / (n_items * n_replicates))

    return VarianceComponents(
        sigma2_items=sigma2_items,
        sigma2_judges=sigma2_judges,
        sigma2_interaction=sigma2_interaction,
        sigma2_residual=sigma2_residual,
        n_items=n_items,
        n_judges=n_judges,
        n_replicates=n_replicates,
    )


# ---------------------------------------------------------------------------
# Reporting helper
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Estimate:
    """A number that cannot be reported without its interval.

    ``report.py`` rejects bare point estimates (invariant 7). Making the interval part of the
    type means the rejection happens at construction, not at review.
    """

    value: float
    ci_low: float
    ci_high: float
    method: str
    n: int = 0

    def __post_init__(self) -> None:
        if self.ci_low > self.ci_high:
            raise ValueError(f"ci_low ({self.ci_low}) exceeds ci_high ({self.ci_high})")
        if not (self.ci_low <= self.value <= self.ci_high):
            raise ValueError(
                f"estimate {self.value} lies outside its own interval "
                f"[{self.ci_low}, {self.ci_high}]"
            )

    @property
    def width(self) -> float:
        return self.ci_high - self.ci_low

    def format(self, digits: int = 3) -> str:
        return f"{self.value:.{digits}f} [{self.ci_low:.{digits}f}, {self.ci_high:.{digits}f}]"

    def to_dict(self) -> Dict[str, object]:
        return {
            "value": self.value,
            "ci_low": self.ci_low,
            "ci_high": self.ci_high,
            "method": self.method,
            "n": self.n,
        }
