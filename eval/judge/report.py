"""L5: reporting and gating.

The layer that decides what may be said out loud. Three refusals define it:

1. **No bare point estimates.** Every reported number carries an interval, enforced at
   construction rather than checked at review (invariant 7).
2. **No comparison across incompatible measurement versions.** If the rubric, prompt, judge set,
   corpus, k or temperature differ, the two numbers do not measure the same thing and comparing
   them raises.
3. **No gate on a point difference.** The gate compares intervals and checks the difference
   against the minimum detectable effect. A 5-point threshold on a measurement with 8.3 points of
   noise is how this project's original alarm came to be less stable than the thing it monitored.

DECLARED FAMILIES
-----------------
Multiplicity control only works if the family is fixed before the tests run. ``TestFamily`` is
declared in code, tests are registered into it, and ``adjust`` applies Benjamini-Hochberg across
exactly that set. Deciding the family after seeing the p-values is how a false positive becomes a
finding, so the family cannot be inferred at report time.

MDE BY SIMULATION
-----------------
The closed-form MDE in ``eval/stats.py`` assumes normality. Here the scores are bounded ordinals
on a small benchmark, so the honest version bootstraps the observed null and finds the smallest
true shift detected at 80% power. It is slower and it does not assume a shape the data does not
have.

Pure and network-free.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from eval.judge.schemas import IncompatibleMeasurement, MeasurementVersion
from eval.stats import (
    Estimate,
    benjamini_hochberg,
    clustered_bootstrap_ci,
    paired_permutation_test,
)

REPORT_VERSION = "1.0.0"

DEFAULT_POWER = 0.80
DEFAULT_ALPHA = 0.05


class ReportError(ValueError):
    """Raised when a report is asked to state something it cannot support."""


# ---------------------------------------------------------------------------
# Reported numbers
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ReportedNumber:
    """A number cleared for publication: a value, an interval, and where it came from.

    Constructing one without an interval raises. That is the mechanical form of invariant 7 -
    the failure mode is not that someone reports a bad interval, it is that someone reports no
    interval at all and the reader assumes precision that was never measured.
    """

    label: str
    estimate: Estimate
    measurement_version: MeasurementVersion
    n_items: int = 0
    note: str = ""

    @property
    def value(self) -> float:
        return self.estimate.value

    def format(self, digits: int = 3) -> str:
        return f"{self.label}: {self.estimate.format(digits)}"

    def to_dict(self) -> Dict[str, object]:
        return {
            "label": self.label,
            **self.estimate.to_dict(),
            "n_items": self.n_items,
            "measurement_version": self.measurement_version.version_id,
            "note": self.note,
        }


def reported(
    label: str,
    values: Sequence[float],
    measurement_version: MeasurementVersion,
    n_boot: int = 2000,
    seed: int = 0,
    note: str = "",
) -> ReportedNumber:
    """Summarise per-item values into a reportable mean with a clustered interval.

    Resamples items, because the benchmark is a sample of questions and the interval has to cover
    the question sampling as well as the judge noise.
    """
    if not values:
        raise ReportError(f"cannot report {label!r} from no observations")
    if len(values) < 2:
        raise ReportError(
            f"cannot report {label!r} from a single observation; there is no interval to compute "
            "and a point estimate alone is not reportable"
        )

    mean = sum(values) / len(values)
    low, high = clustered_bootstrap_ci(
        list(values), lambda drawn: sum(drawn) / len(drawn), n_boot=n_boot, seed=seed
    )
    # A degenerate resample can leave the mean marginally outside the percentile bounds when
    # every value is identical; clamp rather than raise, since the interval is genuinely zero.
    low, high = min(low, mean), max(high, mean)
    return ReportedNumber(
        label=label,
        estimate=Estimate(mean, low, high, method="clustered bootstrap", n=len(values)),
        measurement_version=measurement_version,
        n_items=len(values),
        note=note,
    )


# ---------------------------------------------------------------------------
# Declared test families
# ---------------------------------------------------------------------------
@dataclass
class TestResult:
    """One comparison within a family."""

    name: str
    observed: float
    p_raw: float
    n_items: int
    p_adjusted: Optional[float] = None
    rejected: Optional[bool] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "observed": self.observed,
            "p_raw": self.p_raw,
            "p_adjusted": self.p_adjusted,
            "rejected": self.rejected,
            "n_items": self.n_items,
        }


@dataclass
class TestFamily:
    """A set of hypothesis tests declared before any of them is run.

    The declaration is the point. Benjamini-Hochberg controls the false discovery rate across a
    family, and choosing the family after seeing the p-values controls nothing at all.
    """

    name: str
    declared: Tuple[str, ...]
    alpha: float = DEFAULT_ALPHA
    results: List[TestResult] = field(default_factory=list)
    _adjusted: bool = False

    def __post_init__(self) -> None:
        if not self.declared:
            raise ReportError(f"family {self.name!r} declares no tests")
        if len(set(self.declared)) != len(self.declared):
            raise ReportError(f"family {self.name!r} declares a duplicate test name")

    def record(self, result: TestResult) -> None:
        if self._adjusted:
            raise ReportError(
                f"family {self.name!r} has already been adjusted; adding a test afterwards would "
                "invalidate the correction"
            )
        if result.name not in self.declared:
            raise ReportError(
                f"{result.name!r} was not declared in family {self.name!r}. Declaring the family "
                "after seeing results is how a false positive becomes a finding."
            )
        if any(existing.name == result.name for existing in self.results):
            raise ReportError(f"{result.name!r} was already recorded in family {self.name!r}")
        self.results.append(result)

    @property
    def complete(self) -> bool:
        return {r.name for r in self.results} == set(self.declared)

    def adjust(self) -> List[TestResult]:
        """Apply BH-FDR across the declared family. Both raw and adjusted are kept.

        Refuses to run on an incomplete family: correcting across five tests when eight were
        declared understates the correction, and the missing three are usually the ones that did
        not look interesting - which is exactly the selection FDR exists to defend against.
        """
        if not self.complete:
            missing = sorted(set(self.declared) - {r.name for r in self.results})
            raise ReportError(
                f"family {self.name!r} is incomplete: {missing} declared but not run. "
                "Adjusting now would understate the correction."
            )
        ordered = sorted(self.results, key=lambda r: self.declared.index(r.name))
        adjusted, rejected = benjamini_hochberg([r.p_raw for r in ordered], self.alpha)
        for result, p_adjusted, is_rejected in zip(ordered, adjusted, rejected):
            result.p_adjusted = p_adjusted
            result.rejected = is_rejected
        self.results = ordered
        self._adjusted = True
        return ordered

    def to_dict(self) -> Dict[str, object]:
        return {
            "family": self.name,
            "alpha": self.alpha,
            "declared": list(self.declared),
            "adjusted": self._adjusted,
            "results": [r.to_dict() for r in self.results],
            "n_rejected": sum(1 for r in self.results if r.rejected),
        }


def compare_paired(
    name: str,
    a: Sequence[float],
    b: Sequence[float],
    n_permutations: int = 10000,
    seed: int = 0,
) -> TestResult:
    """Paired permutation test across items - the right test for one benchmark, two conditions.

    Pairing matters because items differ far more than systems do. An unpaired test throws that
    structure away and loses most of the power the design already bought.
    """
    outcome = paired_permutation_test(a, b, n_permutations=n_permutations, seed=seed)
    return TestResult(
        name=name, observed=outcome.observed, p_raw=outcome.p_value, n_items=len(a)
    )


# ---------------------------------------------------------------------------
# Minimum detectable effect, by simulation
# ---------------------------------------------------------------------------
def minimum_detectable_effect(
    null_differences: Sequence[float],
    power: float = DEFAULT_POWER,
    alpha: float = DEFAULT_ALPHA,
    n_simulations: int = 200,
    n_permutations: int = 500,
    seed: int = 0,
    max_effect: Optional[float] = None,
    steps: int = 20,
) -> Optional[float]:
    """Smallest true shift this design detects at ``power``, found by simulating the null.

    ``null_differences`` are the observed PER-ITEM DIFFERENCES when there is no real effect: two
    runs of the same system, or a pilot comparison known to be null. Their spread is what the
    test has to overcome, and it is the only thing that determines the answer.

    WHY IT MUST BE DIFFERENCES AND NOT ONE CONDITION'S SCORES. An earlier version of this took a
    single condition's values, resampled them and added a constant shift. That makes every paired
    difference exactly equal to the effect - zero variance - and a paired permutation test on
    constant differences detects arbitrarily small effects. It reported an MDE of 0.12 on data
    with a standard deviation of 1.0 at n=12, and the number did not improve with more data.
    The noise in a paired comparison lives in the differences, so the differences are what gets
    bootstrapped.

    The closed form in ``eval/stats.py`` assumes normality; this does not, which matters for
    bounded ordinal scores on a small benchmark. The two should agree closely when the
    differences happen to be roughly normal, and the test suite checks that they do.

    Returns ``None`` when even the largest shift tried is not reliably detected. That is itself
    the finding: the design cannot resolve differences of the size anyone cares about, and no
    gate threshold on it means anything.
    """
    if len(null_differences) < 2:
        raise ReportError("need at least two observations to simulate power")
    if not 0 < power < 1:
        raise ReportError("power must be in (0, 1)")

    spread = _standard_deviation(null_differences)
    if spread == 0:
        # The differences carry no noise at all, so any non-zero shift is detected with
        # certainty. The honest MDE is zero rather than the smallest step this grid happens
        # to try.
        return 0.0

    ceiling = max_effect if max_effect is not None else spread * 3
    rng = random.Random(seed)
    for step in range(1, steps + 1):
        effect = ceiling * step / steps
        detected = 0
        for _ in range(n_simulations):
            drawn = [
                null_differences[rng.randrange(len(null_differences))]
                for _ in range(len(null_differences))
            ]
            shifted = [value + effect for value in drawn]
            # Test the shifted differences against zero, which is what a paired permutation
            # test does: sign-flip each difference and rebuild the null.
            outcome = paired_permutation_test(
                shifted, [0.0] * len(shifted),
                n_permutations=n_permutations, seed=rng.randrange(1 << 30),
            )
            if outcome.p_value <= alpha:
                detected += 1
        if detected / n_simulations >= power:
            return effect
    return None


def null_differences_from(a: Sequence[float], b: Sequence[float]) -> List[float]:
    """Per-item differences between two conditions, for feeding to ``minimum_detectable_effect``.

    Use two runs of the SAME system, or any pair known to differ by nothing, so the spread
    reflects measurement noise rather than a real effect.
    """
    if len(a) != len(b):
        raise ReportError(f"paired series must match, got {len(a)} and {len(b)}")
    return [x - y for x, y in zip(a, b)]


def _standard_deviation(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))


# ---------------------------------------------------------------------------
# Gating
# ---------------------------------------------------------------------------
@dataclass
class GateResult:
    """The verdict of a regression gate, with the reasoning attached."""

    passed: bool
    reason: str
    current: ReportedNumber
    baseline: ReportedNumber
    difference: float
    intervals_overlap: bool
    mde: Optional[float] = None
    within_noise: Optional[bool] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "passed": self.passed,
            "reason": self.reason,
            "current": self.current.to_dict(),
            "baseline": self.baseline.to_dict(),
            "difference": self.difference,
            "intervals_overlap": self.intervals_overlap,
            "mde": self.mde,
            "within_noise": self.within_noise,
        }


def gate(
    current: ReportedNumber,
    baseline: ReportedNumber,
    mde: Optional[float] = None,
    higher_is_better: bool = True,
) -> GateResult:
    """Declare a regression only when the intervals separate AND the drop exceeds the MDE.

    Two conditions, both required, and each rules out a different mistake. Overlapping intervals
    mean the difference is not distinguishable from noise. A drop smaller than the minimum
    detectable effect means the design could not have detected it reliably even if it were real,
    so calling it a regression is calling noise a finding.

    Raises before doing any of this if the two numbers were not measured the same way. That is
    milestone 11's acceptance check, and it is the mechanical form of "refuses to compare across
    incompatible measurement versions".
    """
    current.measurement_version.assert_comparable(baseline.measurement_version)

    difference = current.value - baseline.value
    overlap = not (
        current.estimate.ci_high < baseline.estimate.ci_low
        or baseline.estimate.ci_high < current.estimate.ci_low
    )
    worsened = difference < 0 if higher_is_better else difference > 0
    magnitude = abs(difference)
    within_noise = None if mde is None else magnitude < mde

    if not worsened:
        return GateResult(
            passed=True,
            reason=f"no regression: {current.label} moved {difference:+.3f}",
            current=current, baseline=baseline, difference=difference,
            intervals_overlap=overlap, mde=mde, within_noise=within_noise,
        )
    if overlap:
        return GateResult(
            passed=True,
            reason=(
                f"{current.label} moved {difference:+.3f} but the intervals overlap "
                f"({current.estimate.format()} against {baseline.estimate.format()}), so the "
                "change is not distinguishable from noise"
            ),
            current=current, baseline=baseline, difference=difference,
            intervals_overlap=True, mde=mde, within_noise=within_noise,
        )
    if within_noise:
        return GateResult(
            passed=True,
            reason=(
                f"{current.label} moved {difference:+.3f}, which is below the minimum detectable "
                f"effect of {mde:.3f}. The design could not reliably detect a change this small "
                "even if it were real."
            ),
            current=current, baseline=baseline, difference=difference,
            intervals_overlap=False, mde=mde, within_noise=True,
        )
    return GateResult(
        passed=False,
        reason=(
            f"regression: {current.label} moved {difference:+.3f}, the intervals do not overlap "
            f"({current.estimate.format()} against {baseline.estimate.format()})"
            + (f", and the change exceeds the MDE of {mde:.3f}" if mde is not None else "")
        ),
        current=current, baseline=baseline, difference=difference,
        intervals_overlap=False, mde=mde, within_noise=within_noise,
    )


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------
@dataclass
class Report:
    """Everything cleared for publication from one run."""

    run_id: str
    measurement_version: MeasurementVersion
    numbers: List[ReportedNumber] = field(default_factory=list)
    families: List[TestFamily] = field(default_factory=list)
    gates: List[GateResult] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def add(self, number: ReportedNumber) -> None:
        """Add a number, refusing anything measured differently from the run itself."""
        self.measurement_version.assert_comparable(number.measurement_version)
        self.numbers.append(number)

    def add_family(self, family: TestFamily) -> None:
        if not family._adjusted:
            raise ReportError(
                f"family {family.name!r} has not been FDR-adjusted; raw p-values may not be "
                "reported alone"
            )
        self.families.append(family)

    def to_dict(self) -> Dict[str, object]:
        return {
            "report_version": REPORT_VERSION,
            "run_id": self.run_id,
            "measurement_version": self.measurement_version.model_dump(mode="json"),
            "measurement_version_id": self.measurement_version.version_id,
            "numbers": [n.to_dict() for n in self.numbers],
            "families": [f.to_dict() for f in self.families],
            "gates": [g.to_dict() for g in self.gates],
            "notes": list(self.notes),
        }

    def to_markdown(self) -> str:
        version = self.measurement_version
        lines: List[str] = [
            f"# Run {self.run_id}",
            "",
            f"- measurement version: `{version.version_id}`",
            f"- corpus fingerprint: `{version.corpus_fingerprint}`",
            f"- judges: {', '.join(version.judge_set)} at k={version.k}, T={version.temperature}",
            f"- aggregation: {version.aggregation_version}",
            "",
            "Every number below carries a 95% interval. Numbers from a different measurement "
            "version are not comparable with these and the tooling refuses to compare them.",
            "",
        ]

        if self.numbers:
            lines += ["## Results", "", "| Quantity | Estimate | 95% interval | n |",
                      "|---|---|---|---|"]
            for number in self.numbers:
                lines.append(
                    f"| {number.label} | {number.estimate.value:.3f} | "
                    f"[{number.estimate.ci_low:.3f}, {number.estimate.ci_high:.3f}] | "
                    f"{number.n_items} |"
                )
            lines.append("")

        for family in self.families:
            lines += [
                f"## Test family: {family.name}",
                "",
                f"{len(family.declared)} tests declared in advance; Benjamini-Hochberg applied "
                f"across the family at alpha={family.alpha}.",
                "",
                "| Test | Observed | p (raw) | p (adjusted) | Significant |",
                "|---|---|---|---|---|",
            ]
            for result in family.results:
                mark = "yes" if result.rejected else "no"
                adjusted = "-" if result.p_adjusted is None else f"{result.p_adjusted:.4f}"
                lines.append(
                    f"| {result.name} | {result.observed:+.3f} | {result.p_raw:.4f} | "
                    f"{adjusted} | {mark} |"
                )
            lines.append("")

        if self.gates:
            lines += ["## Gates", ""]
            for result in self.gates:
                status = "PASS" if result.passed else "FAIL"
                lines.append(f"- **{status}** — {result.reason}")
            lines.append("")

        if self.notes:
            lines += ["## Notes", ""] + [f"- {note}" for note in self.notes] + [""]

        return "\n".join(lines)
