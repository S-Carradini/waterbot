"""L4: label pools and active acquisition.

Expert time is the binding constraint on this whole project, so which items get labelled matters
as much as how many. This module decides that, and it enforces the one distinction that keeps the
resulting numbers honest.

TWO POOLS, AND WHY THEY MUST NOT MIX
------------------------------------
The architecture's Algorithm 4 acquires the items the panel disagreed most about, fits
calibration on them, and reports out-of-sample error on them. That is biased twice: the acquired
set is deliberately unrepresentative, so the map is fitted on hard cases and its error is
measured on hard cases, and neither number describes the benchmark.

The fix (spec 0.3) is two pools drawn up front:

* **probe** - stratified random across categories, frozen before any acquisition, roughly 35% of
  budget. Used ONLY for reporting. It is the only unbiased estimate of how the judge performs on
  the benchmark as a whole, and it is worth protecting precisely because it is tempting to fit on.
* **acquire** - uncertainty-sampled from what is left, roughly 65%. Used ONLY for fitting, where
  concentrating labels on contested items genuinely buys a better map per hour of expert time.

The rejected alternative was one pool with inverse-propensity weights. Correct in principle, but
harder to defend in review and more code for the same answer.

INFORMATIVENESS
---------------
Algorithm 4's three terms, kept: panel disagreement, distance to a decision boundary, and
category under-representation. The third is what stops acquisition collapsing onto one category
that happens to be contested, which would leave the map fitted on a corner of the benchmark.

Pure and network-free.
"""

from __future__ import annotations

import math
import random
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from eval.judge.schemas import DimensionAggregate

DEFAULT_PROBE_FRACTION = 0.35

# Algorithm 4's weights. Disagreement dominates, boundary distance refines, and the
# representation term is a corrective rather than a driver.
WEIGHT_DISAGREEMENT = 0.5
WEIGHT_BOUNDARY = 0.3
WEIGHT_REPRESENTATION = 0.2


class PoolError(ValueError):
    """Raised when a pool cannot be built as asked."""


@dataclass(frozen=True)
class Candidate:
    """One (response, dimension) that a human could be asked to score."""

    response_id: str
    dimension: str
    category: str
    panel_mean: Optional[float] = None
    panel_iqr: Optional[float] = None
    n_abstained: int = 0
    escalated: bool = False

    @property
    def key(self) -> Tuple[str, str]:
        return (self.response_id, self.dimension)


@dataclass
class LabelPools:
    """The frozen assignment of candidates to pools."""

    probe: List[Candidate] = field(default_factory=list)
    acquire: List[Candidate] = field(default_factory=list)
    seed: int = 0
    probe_fraction: float = DEFAULT_PROBE_FRACTION

    @property
    def budget(self) -> int:
        return len(self.probe) + len(self.acquire)

    def pool_of(self, response_id: str, dimension: str) -> Optional[str]:
        key = (response_id, dimension)
        if any(c.key == key for c in self.probe):
            return "probe"
        if any(c.key == key for c in self.acquire):
            return "acquire"
        return None

    def category_counts(self, pool: str = "probe") -> Dict[str, int]:
        items = self.probe if pool == "probe" else self.acquire
        return dict(Counter(c.category for c in items))

    def to_dict(self) -> Dict[str, object]:
        return {
            "budget": self.budget,
            "n_probe": len(self.probe),
            "n_acquire": len(self.acquire),
            "probe_fraction": self.probe_fraction,
            "seed": self.seed,
            "probe_categories": self.category_counts("probe"),
            "acquire_categories": self.category_counts("acquire"),
        }


def candidates_from_aggregates(
    aggregates: Sequence[DimensionAggregate],
    categories: Dict[str, str],
) -> List[Candidate]:
    """Build candidates from panel aggregates, given each response's category."""
    candidates = []
    for aggregate in aggregates:
        category = categories.get(aggregate.response_id)
        if category is None:
            raise PoolError(
                f"no category recorded for {aggregate.response_id}; stratification would be "
                "silently wrong"
            )
        candidates.append(
            Candidate(
                response_id=aggregate.response_id,
                dimension=aggregate.dimension,
                category=category,
                panel_mean=aggregate.mean,
                panel_iqr=aggregate.iqr,
                n_abstained=aggregate.n_abstained,
                escalated=aggregate.escalate,
            )
        )
    return candidates


# ---------------------------------------------------------------------------
# The probe pool
# ---------------------------------------------------------------------------
def build_probe_pool(
    candidates: Sequence[Candidate],
    size: int,
    seed: int = 0,
) -> List[Candidate]:
    """Stratified random sample across categories, frozen before any acquisition.

    Stratified rather than simple random because at 7 to 15 items per category a simple random
    draw can miss a category entirely, and a per-category claim then rests on nothing.

    Allocation is proportional with a floor of one per category, so a small category is
    represented even when proportionality would round it away. Remainders go to the largest
    categories, which is where an extra label buys the most precision.
    """
    if size <= 0:
        raise PoolError("probe pool size must be positive")
    if size > len(candidates):
        raise PoolError(
            f"cannot draw a probe pool of {size} from {len(candidates)} candidates"
        )

    by_category: Dict[str, List[Candidate]] = {}
    for candidate in candidates:
        by_category.setdefault(candidate.category, []).append(candidate)
    for group in by_category.values():
        group.sort(key=lambda c: c.key)  # deterministic before shuffling

    categories = sorted(by_category)
    if len(categories) > size:
        raise PoolError(
            f"{len(categories)} categories cannot be represented in a probe pool of {size}"
        )

    total = len(candidates)
    allocation: Dict[str, int] = {}
    for category in categories:
        share = len(by_category[category]) / total
        allocation[category] = max(1, int(size * share))

    # Reconcile rounding against the requested size.
    while sum(allocation.values()) > size:
        largest = max(
            (c for c in categories if allocation[c] > 1), key=lambda c: allocation[c], default=None
        )
        if largest is None:
            break
        allocation[largest] -= 1
    while sum(allocation.values()) < size:
        candidates_with_room = [
            c for c in categories if allocation[c] < len(by_category[c])
        ]
        if not candidates_with_room:
            break
        largest = max(candidates_with_room, key=lambda c: len(by_category[c]))
        allocation[largest] += 1

    rng = random.Random(seed)
    probe: List[Candidate] = []
    for category in categories:
        group = list(by_category[category])
        rng.shuffle(group)
        probe.extend(group[: min(allocation[category], len(group))])
    probe.sort(key=lambda c: c.key)
    return probe


# ---------------------------------------------------------------------------
# Informativeness and acquisition
# ---------------------------------------------------------------------------
def boundary_distance(panel_mean: Optional[float]) -> float:
    """How close a score sits to the nearest half-way point between levels.

    Returns 1.0 at a boundary (2.5, 3.5, ...) and 0.0 at a level's centre. An item the panel put
    squarely on 3 is settled; one it put at 2.51 could round either way, and a human label there
    moves the calibration map most.
    """
    if panel_mean is None:
        return 1.0  # no panel score at all is maximally uncertain
    nearest_boundary = round(panel_mean - 0.5) + 0.5
    distance = abs(panel_mean - nearest_boundary)
    return max(0.0, 1.0 - 2.0 * distance)


def informativeness(
    candidate: Candidate,
    labelled_categories: Counter,
    max_iqr: float = 3.0,
) -> float:
    """Algorithm 4's score: disagreement, boundary proximity, representation.

    The representation term is the one that stops acquisition collapsing onto whichever category
    happens to be most contested, which would fit the map on a corner of the benchmark and
    report it as if it covered the whole.
    """
    disagreement = 0.0 if candidate.panel_iqr is None else min(1.0, candidate.panel_iqr / max_iqr)
    boundary = boundary_distance(candidate.panel_mean)

    total_labelled = sum(labelled_categories.values())
    if total_labelled == 0:
        representation = 1.0
    else:
        share = labelled_categories.get(candidate.category, 0) / total_labelled
        representation = max(0.0, 1.0 - share * len(labelled_categories or [1]))

    return (
        WEIGHT_DISAGREEMENT * disagreement
        + WEIGHT_BOUNDARY * boundary
        + WEIGHT_REPRESENTATION * representation
    )


def build_acquire_pool(
    candidates: Sequence[Candidate],
    size: int,
    exclude: Iterable[Candidate] = (),
    batch_size: int = 25,
) -> List[Candidate]:
    """Uncertainty-sample the acquire pool, rebalancing categories as it goes.

    Selection is batched, and the representation term is recomputed after each batch, so the
    pool self-corrects rather than taking the top-N of a single static ranking. Ties break on the
    candidate key so the result is reproducible.

    Anything already in the probe pool is excluded: an item cannot be both the unbiased estimate
    and the training data.
    """
    if size < 0:
        raise PoolError("acquire pool size cannot be negative")

    excluded: Set[Tuple[str, str]] = {c.key for c in exclude}
    remaining = sorted(
        (c for c in candidates if c.key not in excluded), key=lambda c: c.key
    )
    if size > len(remaining):
        raise PoolError(
            f"cannot acquire {size} candidates; only {len(remaining)} remain after exclusions"
        )

    acquired: List[Candidate] = []
    labelled = Counter()
    while len(acquired) < size and remaining:
        ranked = sorted(
            remaining,
            key=lambda c: (-informativeness(c, labelled), c.key),
        )
        batch = ranked[: min(batch_size, size - len(acquired))]
        acquired.extend(batch)
        labelled.update(c.category for c in batch)
        taken = {c.key for c in batch}
        remaining = [c for c in remaining if c.key not in taken]

    acquired.sort(key=lambda c: c.key)
    return acquired


def build_pools(
    candidates: Sequence[Candidate],
    budget: int,
    probe_fraction: float = DEFAULT_PROBE_FRACTION,
    seed: int = 0,
    batch_size: int = 25,
) -> LabelPools:
    """Draw both pools. The probe pool is frozen first, before anything is acquired.

    Order matters and is not an implementation detail: acquiring first would let the acquisition
    rule see - and therefore shape - what the probe pool could contain, and the probe pool would
    no longer be a random sample of the benchmark.
    """
    if not candidates:
        raise PoolError("no candidates to draw from")
    if budget <= 0:
        raise PoolError("budget must be positive")
    if budget > len(candidates):
        raise PoolError(f"budget {budget} exceeds {len(candidates)} candidates")
    if not 0 < probe_fraction < 1:
        raise PoolError("probe_fraction must be strictly between 0 and 1")

    probe_size = max(1, round(budget * probe_fraction))
    acquire_size = budget - probe_size
    if acquire_size <= 0:
        raise PoolError(
            f"a budget of {budget} at probe_fraction {probe_fraction} leaves nothing to acquire"
        )

    probe = build_probe_pool(candidates, probe_size, seed=seed)
    acquire = build_acquire_pool(candidates, acquire_size, exclude=probe, batch_size=batch_size)
    return LabelPools(probe=probe, acquire=acquire, seed=seed, probe_fraction=probe_fraction)


# ---------------------------------------------------------------------------
# Assignment to annotators
# ---------------------------------------------------------------------------
def assign_to_annotators(
    pools: LabelPools,
    annotators: Sequence[str],
    overlap: int,
    seed: int = 0,
) -> Dict[str, List[Candidate]]:
    """Split the pools across annotators, with a deliberate overlap.

    ``overlap`` is how many candidates every annotator scores in common. Those are the only items
    that can produce an inter-human agreement number, so the human ceiling is bounded by this
    parameter rather than by the total budget - a fact worth knowing before booking hours.

    The overlap is drawn from the probe pool, because agreement measured on uncertainty-sampled
    items would describe agreement on hard cases rather than on the benchmark.
    """
    if not annotators:
        raise PoolError("no annotators to assign to")
    if len(set(annotators)) != len(annotators):
        raise PoolError(f"annotator ids must be distinct, got {list(annotators)}")
    if overlap < 0:
        raise PoolError("overlap cannot be negative")
    if overlap > len(pools.probe):
        raise PoolError(
            f"overlap of {overlap} exceeds the probe pool ({len(pools.probe)}); the human "
            "ceiling can only be measured on shared items"
        )

    rng = random.Random(seed)
    probe = sorted(pools.probe, key=lambda c: c.key)
    rng.shuffle(probe)
    shared = sorted(probe[:overlap], key=lambda c: c.key)
    shared_keys = {c.key for c in shared}

    rest = [c for c in pools.probe if c.key not in shared_keys] + list(pools.acquire)
    rest.sort(key=lambda c: c.key)
    rng.shuffle(rest)

    assignments: Dict[str, List[Candidate]] = {a: list(shared) for a in annotators}
    for index, candidate in enumerate(rest):
        assignments[annotators[index % len(annotators)]].append(candidate)
    for annotator in assignments:
        assignments[annotator].sort(key=lambda c: c.key)
    return assignments


def human_ceiling_capacity(assignments: Dict[str, List[Candidate]]) -> int:
    """How many items every annotator scored in common.

    The sample size behind the human ceiling. Reported up front because a ceiling computed on a
    handful of shared items has an interval wide enough to be useless, and that is worth
    discovering while annotators can still be booked rather than afterwards.
    """
    if not assignments:
        return 0
    key_sets = [{c.key for c in items} for items in assignments.values()]
    shared = set.intersection(*key_sets) if key_sets else set()
    return len(shared)
