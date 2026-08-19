"""Statistics for the judge replication experiment (spec 0.7, milestone 1).

Pure and network-free, per the layout rule in CLAUDE.md. Everything here takes
verdicts in and returns numbers out, so it is testable without a key and
without a database.

WHAT IS BEING ESTIMATED, AND THE TRAP IN IT
-------------------------------------------
The design is R replicates of the same judge over the same N frozen responses,
at temperature 0. That yields R x N binary verdicts, but they are NOT R*N
independent Bernoulli trials. They are N items, each measured R times. Items
differ enormously in how hard they are: "Who will win the next presidential
election?" is refused every time, and the interesting variance lives in one or
two borderline items.

So two intervals are computed and both are reported:

* ``wilson_interval`` on the pooled count, which assumes iid trials. It is the
  interval the spec asks for by name, and it is the one a reader will expect,
  but on clustered data it is anti-conservative - too narrow. It is reported
  with that caveat attached, never bare.

* ``clustered_bootstrap_interval``, which resamples ITEMS rather than verdicts
  (spec 6.3). This respects the clustering and is the honest interval for the
  refusal rate as a property of the question population.

They answer different questions and the gap between them is itself a finding.
Wilson describes "this judge on these 12 items". The clustered interval
describes "this judge on questions like these", which is the claim a paper
actually makes.

THE ONE-ITEM DIAGNOSTIC
-----------------------
Spec 0.7's real question is whether a 7/12 vs 8/12 swing is one item flipping.
``per_item_rates`` answers it directly: if eleven items sit at 0.0 or 1.0 and
one sits near 0.5, the swing is one item, and the run-level spread is a single
Bernoulli draw wearing a percentage sign.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

# z for a two-sided 95% interval. Hard-coded rather than pulled from scipy so
# this module has no scientific-stack import at all; the value is checked
# against scipy in the tests.
Z_95 = 1.959963984540054


# ---------------------------------------------------------------------------
# Wilson
# ---------------------------------------------------------------------------
def wilson_interval(successes: int, trials: int, z: float = Z_95) -> Tuple[float, float]:
    """Wilson score interval for a binomial proportion.

    Wilson (1927). Chosen over the Wald interval because at the counts this
    experiment produces - 12 items, proportions that may sit at or near 1.0 -
    Wald degenerates to zero width and is simply wrong. Wilson stays inside
    [0, 1] and does not collapse at the boundary.

    Assumes independent trials. On the pooled R x N verdict count that
    assumption is violated; see the module docstring.
    """
    if trials < 0:
        raise ValueError("trials must be non-negative")
    if not 0 <= successes <= trials:
        raise ValueError(f"successes ({successes}) must be in [0, trials] ({trials})")
    if trials == 0:
        # No information. The honest interval is the whole parameter space.
        return (0.0, 1.0)

    n = float(trials)
    p_hat = successes / n
    denominator = 1.0 + (z * z) / n
    centre = (p_hat + (z * z) / (2.0 * n)) / denominator
    spread = (z / denominator) * math.sqrt(p_hat * (1.0 - p_hat) / n + (z * z) / (4.0 * n * n))
    return (max(0.0, centre - spread), min(1.0, centre + spread))


# ---------------------------------------------------------------------------
# Clustered bootstrap
# ---------------------------------------------------------------------------
def clustered_bootstrap_interval(
    item_refusals: Sequence[int],
    replicates: int,
    n_boot: int = 2000,
    seed: int = 0,
    alpha: float = 0.05,
) -> Tuple[float, float]:
    """Percentile bootstrap CI for the mean refusal rate, resampling items.

    ``item_refusals[i]`` is how many of ``replicates`` runs refused item i.
    Items are the cluster, so items are what gets resampled - resampling
    individual verdicts would treat correlated within-item votes as independent
    and reproduce exactly the understatement that Wilson already has.

    Uses ``random.Random`` rather than numpy so this module stays dependency
    free. B=2000 percentile is the spec's recommendation (6.3).
    """
    import random

    n_items = len(item_refusals)
    if n_items == 0:
        return (0.0, 1.0)
    if replicates <= 0:
        raise ValueError("replicates must be positive")

    rates = [r / replicates for r in item_refusals]
    rng = random.Random(seed)
    means: List[float] = []
    for _ in range(n_boot):
        resampled = [rates[rng.randrange(n_items)] for _ in range(n_items)]
        means.append(sum(resampled) / n_items)
    means.sort()

    lo_idx = int(math.floor((alpha / 2.0) * n_boot))
    hi_idx = int(math.ceil((1.0 - alpha / 2.0) * n_boot)) - 1
    lo_idx = max(0, min(lo_idx, n_boot - 1))
    hi_idx = max(0, min(hi_idx, n_boot - 1))
    return (means[lo_idx], means[hi_idx])


# ---------------------------------------------------------------------------
# Verdict records
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Verdict:
    """One judge decision on one item in one replicate.

    ``refused`` follows the judge's own semantics inverted: the judge returns
    ``hallucinated``, and refused is its negation. Kept explicit here because
    "hallucination rate" and "refusal rate" are complements and mixing them up
    silently inverts every number downstream.
    """

    run_index: int
    question_id: str
    refused: bool
    raw_verdict: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "run_index": self.run_index,
            "question_id": self.question_id,
            "refused": self.refused,
            "raw_verdict": self.raw_verdict,
        }


@dataclass
class ReplicationSummary:
    """Everything the milestone-1 report and plot need."""

    n_items: int
    n_replicates: int
    run_counts: List[int]
    per_item_refusals: Dict[str, int]
    pooled_refusals: int
    pooled_trials: int
    wilson_lo: float
    wilson_hi: float
    boot_lo: float
    boot_hi: float
    boot_seed: int
    n_boot: int
    excluded_runs: List[int] = field(default_factory=list)
    attempted_replicates: int = 0
    noncanonical_replies: int = 0

    # -- descriptive ------------------------------------------------------
    @property
    def pooled_rate(self) -> float:
        return self.pooled_refusals / self.pooled_trials if self.pooled_trials else 0.0

    @property
    def count_min(self) -> int:
        return min(self.run_counts) if self.run_counts else 0

    @property
    def count_max(self) -> int:
        return max(self.run_counts) if self.run_counts else 0

    @property
    def count_mean(self) -> float:
        return sum(self.run_counts) / len(self.run_counts) if self.run_counts else 0.0

    @property
    def count_sd(self) -> float:
        """Sample standard deviation of the per-run refusal count."""
        n = len(self.run_counts)
        if n < 2:
            return 0.0
        mean = self.count_mean
        return math.sqrt(sum((c - mean) ** 2 for c in self.run_counts) / (n - 1))

    @property
    def swing_points(self) -> float:
        """Observed spread in percentage points, comparable to the paper's 8.3."""
        if not self.run_counts or not self.n_items:
            return 0.0
        return 100.0 * (self.count_max - self.count_min) / self.n_items

    @property
    def count_mean_interval(self) -> Tuple[float, float]:
        """Interval for the mean refusal count, in count units.

        The clustered bootstrap interval is on the rate scale, and the mean
        count is that rate times the number of items, so this is the same
        interval rescaled. Exists so the reported mean is never a bare point
        estimate (invariant 7).
        """
        return (self.boot_lo * self.n_items, self.boot_hi * self.n_items)

    @property
    def excluded_fraction(self) -> float:
        """Share of attempted replicates thrown out for provider errors.

        Reported prominently rather than as a footnote: dropping replicates is
        conditioning on something that happened during measurement, and if the
        share is large the remaining sample is no longer obviously the sample
        that was designed.
        """
        if not self.attempted_replicates:
            return 0.0
        return len(self.excluded_runs) / self.attempted_replicates

    @property
    def noncanonical_rate(self) -> float:
        """Share of model replies that were not exactly REFUSED or ANSWERED.

        The judge codes every one of these as REFUSED. A non-zero rate here
        means part of the reported refusal rate is parsing behaviour rather
        than judgement.
        """
        if not self.pooled_trials:
            return 0.0
        return self.noncanonical_replies / self.pooled_trials

    # -- the 0.7 diagnostic ------------------------------------------------
    @property
    def per_item_rates(self) -> Dict[str, float]:
        return {
            qid: refusals / self.n_replicates
            for qid, refusals in self.per_item_refusals.items()
        }

    @property
    def per_item_intervals(self) -> Dict[str, Tuple[float, float]]:
        """Wilson 95% interval per item, over that item's replicates.

        MARGINAL, not simultaneous. With 12 items, roughly one interval in
        twenty is expected to miss its true rate by chance, so these support
        the qualitative claim "this item is unstable" and must not be used to
        single out an item post hoc without a multiplicity adjustment.
        """
        return {
            qid: wilson_interval(refusals, self.n_replicates)
            for qid, refusals in self.per_item_refusals.items()
        }

    @property
    def unstable_items(self) -> List[str]:
        """Items that did not decide the same way in every replicate."""
        return sorted(
            qid for qid, rate in self.per_item_rates.items() if 0.0 < rate < 1.0
        )

    @property
    def is_single_item_swing(self) -> bool:
        """True when the entire run-to-run spread is attributable to one item.

        This is the literal form of the reviewer objection in spec 0.7. If it
        holds, the motivating result is one Bernoulli flip and needs to be
        reframed rather than quoted.
        """
        return len(self.unstable_items) == 1

    def to_dict(self) -> Dict[str, object]:
        return {
            "n_items": self.n_items,
            "n_replicates": self.n_replicates,
            "run_counts": self.run_counts,
            "per_item_refusals": self.per_item_refusals,
            "per_item_rates": self.per_item_rates,
            "pooled_refusals": self.pooled_refusals,
            "pooled_trials": self.pooled_trials,
            "pooled_rate": self.pooled_rate,
            "count_min": self.count_min,
            "count_max": self.count_max,
            "count_mean": self.count_mean,
            "count_mean_95": list(self.count_mean_interval),
            "count_sd": self.count_sd,
            "swing_points": self.swing_points,
            "wilson_95": [self.wilson_lo, self.wilson_hi],
            "wilson_assumes_iid_trials": True,
            "clustered_bootstrap_95": [self.boot_lo, self.boot_hi],
            "bootstrap_seed": self.boot_seed,
            "bootstrap_resamples": self.n_boot,
            "per_item_95": {qid: list(ci) for qid, ci in self.per_item_intervals.items()},
            "per_item_intervals_are_marginal": True,
            "unstable_items": self.unstable_items,
            "is_single_item_swing": self.is_single_item_swing,
            "excluded_runs": self.excluded_runs,
            "attempted_replicates": self.attempted_replicates,
            "excluded_fraction": self.excluded_fraction,
            "noncanonical_replies": self.noncanonical_replies,
            "noncanonical_rate": self.noncanonical_rate,
        }


def summarise(
    verdicts: Sequence[Verdict],
    question_ids: Sequence[str],
    excluded_runs: Optional[Sequence[int]] = None,
    n_boot: int = 2000,
    seed: int = 0,
    noncanonical_replies: int = 0,
) -> ReplicationSummary:
    """Reduce a verdict log to the milestone-1 summary.

    ``excluded_runs`` are replicates whose call ledger recorded a provider
    error. Their verdicts are dropped entirely rather than partially counted:
    a replicate in which some items were judged by the model and others by the
    keyword fallback is not a sample of the judge, it is a mixture of two
    different measuring instruments.
    """
    excluded = set(excluded_runs or ())
    attempted = len({v.run_index for v in verdicts})
    kept = [v for v in verdicts if v.run_index not in excluded]
    if not kept:
        # Every replicate failed. Returning a summary of nothing would present
        # zeros as if they were measurements.
        raise ValueError(
            f"No usable replicates: all {attempted} were excluded for provider errors. "
            "There is nothing to summarise."
        )

    run_indices = sorted({v.run_index for v in kept})
    ids = list(question_ids)

    run_counts: List[int] = []
    for run_index in run_indices:
        run_counts.append(sum(1 for v in kept if v.run_index == run_index and v.refused))

    per_item: Dict[str, int] = {
        qid: sum(1 for v in kept if v.question_id == qid and v.refused) for qid in ids
    }

    pooled_refusals = sum(1 for v in kept if v.refused)
    pooled_trials = len(kept)
    wilson_lo, wilson_hi = wilson_interval(pooled_refusals, pooled_trials)

    n_replicates = len(run_indices)
    boot_lo, boot_hi = clustered_bootstrap_interval(
        [per_item[qid] for qid in ids],
        replicates=max(n_replicates, 1),
        n_boot=n_boot,
        seed=seed,
    )

    return ReplicationSummary(
        n_items=len(ids),
        n_replicates=n_replicates,
        run_counts=run_counts,
        per_item_refusals=per_item,
        pooled_refusals=pooled_refusals,
        pooled_trials=pooled_trials,
        wilson_lo=wilson_lo,
        wilson_hi=wilson_hi,
        boot_lo=boot_lo,
        boot_hi=boot_hi,
        boot_seed=seed,
        n_boot=n_boot,
        excluded_runs=sorted(excluded),
        attempted_replicates=attempted,
        noncanonical_replies=noncanonical_replies,
    )
