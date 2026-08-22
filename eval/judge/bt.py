"""L3: turning pairwise preferences into a system ranking with intervals.

WHY PAIRWISE AT ALL
-------------------
To compare WaterBot against RealWater, asking "which of these two answers is better?" is more
reliable than scoring each separately and subtracting. Differencing two pointwise scores
inherits both scores' calibration error; a direct comparison does not.

WHY DAVIDSON AND NOT PLAIN BRADLEY-TERRY
----------------------------------------
The architecture's algorithm discards comparisons that flip when presentation order is swapped.
That is a selection bias, and a specific one: order-stability correlates with the outcome,
because close calls flip and blowouts do not. Dropping the close calls conditions the fit on a
variable caused by the thing being measured, and inflates the apparent separation between
systems.

Davidson (1970) extends Bradley-Terry with an explicit tie parameter, so an order-unstable pair
is recorded as a tie and kept:

    P(i beats j) = pi_i / (pi_i + pi_j + nu * sqrt(pi_i * pi_j))
    P(j beats i) = pi_j / (pi_i + pi_j + nu * sqrt(pi_i * pi_j))
    P(tie)       = nu * sqrt(pi_i * pi_j) / (pi_i + pi_j + nu * sqrt(pi_i * pi_j))

with ``pi_i = exp(theta_i)``. At ``nu = 0`` ties become impossible and Davidson reduces exactly
to Bradley-Terry, which is the property the tests use to check the implementation against the
simpler model.

Plain BT on order-stable pairs only is retained as a **sensitivity analysis**, never the
headline (project rule).

INTERVALS COME FROM RESAMPLING QUESTIONS
----------------------------------------
Comparisons on the same question are correlated - they share a question, an evidence set and
whatever makes that question hard. The bootstrap resamples questions and refits, which is the
cluster that matters (spec 4.4, 6.3).

Pure and network-free. scipy is used for optimisation only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

# Identifies the fitting procedure in a measurement version.
BT_VERSION = "1.0.0"

# Weak zero-mean Gaussian prior on the log-strengths and on log(nu), applied as an L2 penalty.
#
# WHY THIS IS NOT OPTIONAL. Bradley-Terry strengths are only identified when the win graph is
# strongly connected (Ford, 1957). If one system never loses - which is entirely possible with
# 6 categories and a strong baseline - the likelihood has no maximum: the fit runs off toward
# infinity and stops wherever the optimiser gives up. The estimate is then a property of the
# stopping rule, not of the data, and every bootstrap resample runs off in the same direction,
# so the interval collapses to zero width and reports false certainty about an infinite number.
#
# A weak prior makes the posterior mode always exist and finite. 0.5 on the log scale is
# deliberately weak: it moves a well-identified fit by very little, and only takes over when the
# data cannot identify the parameter at all. The value is recorded in the fit so a reader can
# see the estimate is penalised, and `separation_detected` says when it was load-bearing.
DEFAULT_PRIOR_STRENGTH = 0.5


class BradleyTerryError(RuntimeError):
    """Raised when a comparison set cannot support a fit."""


@dataclass(frozen=True)
class Comparison:
    """One pairwise judgement on one question.

    ``order_stable`` records whether the two presentation orders agreed. It does not affect the
    Davidson fit - an unstable pair arrives here already recorded as a tie - but it is carried so
    the position-bias rate can be reported and so the stable-only sensitivity fit can select on
    it explicitly rather than by accident.
    """

    item_id: str
    system_a: str
    system_b: str
    outcome: str  # "a", "b", or "tie"

    order_stable: bool = True

    def __post_init__(self) -> None:
        if self.outcome not in ("a", "b", "tie"):
            raise BradleyTerryError(f"outcome must be a, b or tie; got {self.outcome!r}")
        if self.system_a == self.system_b:
            raise BradleyTerryError(f"cannot compare {self.system_a!r} with itself")


@dataclass
class BradleyTerryFit:
    """Fitted latent strengths, on the log scale, with the tie parameter."""

    strengths: Dict[str, float]
    tie_parameter: float
    n_comparisons: int
    n_ties: int
    systems: List[str]
    converged: bool
    model: str = "davidson"
    intervals: Dict[str, Tuple[float, float]] = field(default_factory=dict)
    bootstrap_resamples: int = 0
    bootstrap_seed: int = 0
    prior_strength: float = DEFAULT_PRIOR_STRENGTH
    # True when the win graph is not strongly connected, so the unpenalised estimate would be
    # infinite and the prior is doing the identifying. Reported, never silent: a separated
    # ranking is a real finding (one system never lost) and the strengths must not be read as
    # if the data had pinned them down.
    separation_detected: bool = False

    @property
    def tie_rate(self) -> float:
        return self.n_ties / self.n_comparisons if self.n_comparisons else 0.0

    def ranking(self) -> List[str]:
        """Systems strongest first. Ties in strength break by name, so it is deterministic."""
        return sorted(self.systems, key=lambda s: (-self.strengths[s], s))

    def probability(self, system_a: str, system_b: str) -> Dict[str, float]:
        """Model-implied outcome probabilities for one pair."""
        return davidson_probabilities(
            self.strengths[system_a], self.strengths[system_b], self.tie_parameter
        )

    def separates(self, system_a: str, system_b: str) -> bool:
        """True when the two systems' intervals do not overlap.

        The comparison a report should make. Comparing point estimates is what let an 8.3-point
        swing hide behind a 5-point threshold.
        """
        if system_a not in self.intervals or system_b not in self.intervals:
            raise BradleyTerryError(
                "no bootstrap intervals were computed; refusing to claim separation from "
                "point estimates alone"
            )
        low_a, high_a = self.intervals[system_a]
        low_b, high_b = self.intervals[system_b]
        return bool(high_a < low_b or high_b < low_a)

    def to_dict(self) -> Dict[str, object]:
        return {
            "model": self.model,
            "bt_version": BT_VERSION,
            "strengths": dict(sorted(self.strengths.items())),
            "intervals": {k: list(v) for k, v in sorted(self.intervals.items())},
            "tie_parameter": self.tie_parameter,
            "tie_rate": self.tie_rate,
            "n_comparisons": self.n_comparisons,
            "n_ties": self.n_ties,
            "ranking": self.ranking(),
            "converged": self.converged,
            "bootstrap_resamples": self.bootstrap_resamples,
            "bootstrap_seed": self.bootstrap_seed,
            "prior_strength": self.prior_strength,
            "separation_detected": self.separation_detected,
        }


def davidson_probabilities(theta_a: float, theta_b: float, nu: float) -> Dict[str, float]:
    """Outcome probabilities under Davidson, from log-strengths.

    Computed in a shifted exponential space so that large strength differences do not overflow:
    only the difference between the two matters, so both are shifted by their maximum first.
    """
    if nu < 0:
        raise BradleyTerryError("the tie parameter must be non-negative")
    shift = max(theta_a, theta_b)
    pi_a = math.exp(theta_a - shift)
    pi_b = math.exp(theta_b - shift)
    tie_term = nu * math.sqrt(pi_a * pi_b)
    denominator = pi_a + pi_b + tie_term
    return {
        "a": pi_a / denominator,
        "b": pi_b / denominator,
        "tie": tie_term / denominator,
    }


def _penalised_negative_log_likelihood(
    parameters: Sequence[float],
    comparisons: Sequence[Comparison],
    index: Dict[str, int],
    prior_strength: float,
) -> float:
    """Davidson negative log-likelihood plus a weak L2 penalty (a Gaussian prior).

    The last parameter is ``log(nu)``, so the tie parameter stays positive without a constrained
    optimiser. System 0's strength is pinned at zero by construction - the model is only
    identified up to an additive constant on the log scale.

    The penalty is what makes the objective have a finite minimiser even under complete
    separation. Without it the optimiser walks toward infinity and halts arbitrarily; see the
    note on DEFAULT_PRIOR_STRENGTH.
    """
    *free_strengths, log_nu = parameters
    strengths = [0.0] + list(free_strengths)
    nu = math.exp(log_nu)

    total = 0.0
    for comparison in comparisons:
        theta_a = strengths[index[comparison.system_a]]
        theta_b = strengths[index[comparison.system_b]]
        probabilities = davidson_probabilities(theta_a, theta_b, nu)
        probability = probabilities[comparison.outcome]
        # Guard the log: a probability can underflow to exactly zero when strengths separate
        # completely, and an infinite objective stalls the optimiser rather than steering it.
        total -= math.log(max(probability, 1e-300))

    if prior_strength > 0:
        total += prior_strength * sum(theta * theta for theta in strengths)
        total += prior_strength * log_nu * log_nu
    return total


def win_graph_is_connected(comparisons: Sequence[Comparison]) -> bool:
    """Ford's condition: the maximum likelihood estimate exists iff the win graph is strongly
    connected.

    An edge a -> b means a was preferred to b at least once. A tie contributes edges in both
    directions, since it is evidence that neither dominates. If some group of systems never
    loses to the rest, their strengths are unbounded above and the unpenalised MLE does not
    exist - which is exactly when the prior stops being cosmetic.
    """
    edges: Dict[str, set] = {}
    systems = set()
    for comparison in comparisons:
        systems.add(comparison.system_a)
        systems.add(comparison.system_b)
        edges.setdefault(comparison.system_a, set())
        edges.setdefault(comparison.system_b, set())
        if comparison.outcome in ("a", "tie"):
            edges[comparison.system_a].add(comparison.system_b)
        if comparison.outcome in ("b", "tie"):
            edges[comparison.system_b].add(comparison.system_a)

    if len(systems) < 2:
        return False

    def reachable(start: str, graph: Dict[str, set]) -> set:
        seen, stack = {start}, [start]
        while stack:
            node = stack.pop()
            for neighbour in graph.get(node, ()):
                if neighbour not in seen:
                    seen.add(neighbour)
                    stack.append(neighbour)
        return seen

    reversed_edges: Dict[str, set] = {system: set() for system in systems}
    for source, targets in edges.items():
        for target in targets:
            reversed_edges[target].add(source)

    start = next(iter(sorted(systems)))
    return reachable(start, edges) == systems and reachable(start, reversed_edges) == systems


def fit_davidson(
    comparisons: Sequence[Comparison],
    include_ties: bool = True,
    max_iterations: int = 500,
    prior_strength: float = DEFAULT_PRIOR_STRENGTH,
) -> BradleyTerryFit:
    """Fit Davidson strengths by penalised maximum likelihood.

    ``include_ties=False`` drops tied comparisons and fixes the tie parameter at zero, which is
    plain Bradley-Terry. That is the sensitivity analysis, not the headline: dropping ties
    discards the close calls, which is exactly the selection the tie model exists to avoid.

    ``prior_strength`` is a weak L2 penalty that keeps the estimate finite when the win graph is
    not strongly connected. Set it to 0 for a pure MLE, and expect divergence on separated data.
    """
    from scipy.optimize import minimize

    if not comparisons:
        raise BradleyTerryError("cannot fit a model with no comparisons")
    if prior_strength < 0:
        raise BradleyTerryError("prior_strength must be non-negative")

    used = list(comparisons) if include_ties else [
        c for c in comparisons if c.outcome != "tie"
    ]
    if not used:
        raise BradleyTerryError("every comparison was a tie, and ties were excluded")

    systems = sorted({c.system_a for c in used} | {c.system_b for c in used})
    if len(systems) < 2:
        raise BradleyTerryError(f"need at least two systems, got {systems}")
    index = {system: position for position, system in enumerate(systems)}

    separated = not win_graph_is_connected(used)
    n_ties = sum(1 for c in used if c.outcome == "tie")

    if not include_ties or n_ties == 0:
        # No tie observations means nu is not identified; pin it near zero so the fit reduces to
        # Bradley-Terry rather than wandering on a flat likelihood surface.
        fixed_log_nu = math.log(1e-12)

        def objective(free):
            return _penalised_negative_log_likelihood(
                list(free) + [fixed_log_nu], used, index, prior_strength
            )

        start = [0.0] * (len(systems) - 1)
        result = minimize(objective, start, method="BFGS", options={"maxiter": max_iterations})
        strengths = [0.0] + list(result.x)
        nu = 0.0
    else:
        def objective(parameters):
            return _penalised_negative_log_likelihood(
                parameters, used, index, prior_strength
            )

        start = [0.0] * (len(systems) - 1) + [math.log(0.5)]
        result = minimize(objective, start, method="BFGS", options={"maxiter": max_iterations})
        strengths = [0.0] + list(result.x[:-1])
        nu = math.exp(result.x[-1])

    # Coerce out of numpy at the boundary. scipy returns numpy floats, which are not JSON
    # serialisable and whose comparisons produce numpy booleans - so `separates()` would return
    # something that is not `True` or `False`, and writing a fit to a manifest would raise.
    strengths = [float(s) for s in strengths]
    nu = float(nu)

    # Centre the strengths so the scale is interpretable and two fits are comparable. Only
    # differences are identified, so this changes nothing about the model.
    mean_strength = sum(strengths) / len(strengths)
    centred = {system: float(strengths[i] - mean_strength) for system, i in index.items()}

    return BradleyTerryFit(
        strengths=centred,
        tie_parameter=nu,
        n_comparisons=len(used),
        n_ties=n_ties,
        systems=systems,
        converged=bool(result.success),
        model="davidson" if (include_ties and n_ties) else "bradley_terry",
        prior_strength=prior_strength,
        separation_detected=separated,
    )


def bootstrap_strengths(
    comparisons: Sequence[Comparison],
    n_boot: int = 2000,
    seed: int = 0,
    alpha: float = 0.05,
    include_ties: bool = True,
    prior_strength: float = DEFAULT_PRIOR_STRENGTH,
) -> Dict[str, Tuple[float, float]]:
    """Percentile intervals for each system's strength, resampling QUESTIONS.

    Comparisons on the same question share an evidence set and a difficulty, so they are not
    independent draws. Resampling questions and refitting respects that; resampling individual
    comparisons would not, and would report an interval far too narrow.

    Resamples that cannot be fitted - every draw a tie, or a system missing entirely - are
    skipped rather than counted, and a fit is refused if too few survive to say anything.
    """
    import random

    if not comparisons:
        raise BradleyTerryError("cannot bootstrap an empty comparison set")

    by_item: Dict[str, List[Comparison]] = {}
    for comparison in comparisons:
        by_item.setdefault(comparison.item_id, []).append(comparison)
    items = sorted(by_item)
    if len(items) < 2:
        raise BradleyTerryError(
            f"need at least two questions to resample, got {len(items)}"
        )

    systems = sorted({c.system_a for c in comparisons} | {c.system_b for c in comparisons})
    rng = random.Random(seed)
    draws: Dict[str, List[float]] = {system: [] for system in systems}

    for _ in range(n_boot):
        resampled: List[Comparison] = []
        for _ in range(len(items)):
            resampled.extend(by_item[items[rng.randrange(len(items))]])
        try:
            fit = fit_davidson(
                resampled, include_ties=include_ties, prior_strength=prior_strength
            )
        except BradleyTerryError:
            continue
        if set(fit.systems) != set(systems):
            continue  # a system dropped out of this resample; its strength is not comparable
        for system in systems:
            draws[system].append(fit.strengths[system])

    surviving = min(len(values) for values in draws.values())
    if surviving < max(20, n_boot // 20):
        raise BradleyTerryError(
            f"only {surviving} of {n_boot} bootstrap resamples could be fitted; the comparison "
            "set is too sparse to support an interval"
        )

    intervals: Dict[str, Tuple[float, float]] = {}
    for system, values in draws.items():
        values.sort()
        n = len(values)
        lo_index = max(0, min(int(math.floor((alpha / 2) * n)), n - 1))
        hi_index = max(0, min(int(math.ceil((1 - alpha / 2) * n)) - 1, n - 1))
        intervals[system] = (values[lo_index], values[hi_index])
    return intervals


def fit_with_intervals(
    comparisons: Sequence[Comparison],
    n_boot: int = 2000,
    seed: int = 0,
    include_ties: bool = True,
    prior_strength: float = DEFAULT_PRIOR_STRENGTH,
) -> BradleyTerryFit:
    """The headline fit: Davidson with ties, plus clustered bootstrap intervals."""
    fit = fit_davidson(
        comparisons, include_ties=include_ties, prior_strength=prior_strength
    )
    fit.intervals = bootstrap_strengths(
        comparisons, n_boot=n_boot, seed=seed, include_ties=include_ties,
        prior_strength=prior_strength,
    )
    fit.bootstrap_resamples = n_boot
    fit.bootstrap_seed = seed
    return fit


# ---------------------------------------------------------------------------
# Position bias
# ---------------------------------------------------------------------------
def position_bias_rate(comparisons: Sequence[Comparison]) -> float:
    """Share of comparisons whose verdict flipped purely on presentation order.

    A headline result in its own right, not diagnostics. If a large share of verdicts flip on
    order alone, that is a finding about LLM judges in technical domains and belongs in the
    abstract.
    """
    if not comparisons:
        return 0.0
    return sum(1 for c in comparisons if not c.order_stable) / len(comparisons)


def build_comparison(
    item_id: str,
    system_a: str,
    system_b: str,
    verdict_first: str,
    verdict_second: str,
) -> Comparison:
    """Combine the two presentation orders of one pair into one comparison.

    ``verdict_first`` is the winner when A was shown first; ``verdict_second`` is the winner when
    B was shown first. Both are expressed as "a" or "b" - the system, not the position - so a
    disagreement between them is a genuine flip rather than a bookkeeping artefact.

    Agreement gives a preference. Disagreement becomes a TIE and is kept, because discarding it
    would select on a post-treatment variable.
    """
    for label, value in (("verdict_first", verdict_first), ("verdict_second", verdict_second)):
        if value not in ("a", "b"):
            raise BradleyTerryError(f"{label} must be 'a' or 'b'; got {value!r}")

    stable = verdict_first == verdict_second
    return Comparison(
        item_id=item_id,
        system_a=system_a,
        system_b=system_b,
        outcome=verdict_first if stable else "tie",
        order_stable=stable,
    )
