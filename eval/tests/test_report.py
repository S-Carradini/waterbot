"""Tests for L5 reporting and gating.

Milestone 11's acceptance check is stated exactly: comparing two incompatible runs raises, and
this file asserts it. The other two refusals - no bare point estimates, no gating on a point
difference - are tested the same way, because each exists to prevent a specific mistake this
project has already made once.

Network-free.
"""

from __future__ import annotations

import pytest

from eval.judge.report import (
    GateResult,
    Report,
    ReportError,
    ReportedNumber,
    TestFamily as Family,
    TestResult as Result,
    compare_paired,
    gate,
    minimum_detectable_effect,
    null_differences_from,
    reported,
)
from eval.judge.schemas import IncompatibleMeasurement, MeasurementVersion
from eval.stats import Estimate


def a_version(**kw) -> MeasurementVersion:
    payload = {
        "corpus_fingerprint": "08527fbdf140f811",
        "rubric_hash": "r" * 16,
        "prompt_hash": "p" * 16,
        "judge_set": ("claude-x", "gemini-y", "gpt-z"),
        "aggregation_version": "1.0.0",
        "k": 5,
        "temperature": 0.3,
    }
    payload.update(kw)
    return MeasurementVersion(**payload)


def a_number(label="grounding", value=3.0, low=2.8, high=3.2, version=None) -> ReportedNumber:
    return ReportedNumber(
        label=label,
        estimate=Estimate(value, low, high, method="clustered bootstrap", n=12),
        measurement_version=version or a_version(),
        n_items=12,
    )


# ---------------------------------------------------------------------------
# No bare point estimates
# ---------------------------------------------------------------------------
def test_a_reported_number_carries_an_interval():
    number = reported("grounding", [3.0, 3.5, 2.5, 3.0, 4.0, 2.0], a_version(), n_boot=300)
    assert number.estimate.ci_low <= number.value <= number.estimate.ci_high


def test_a_single_observation_cannot_be_reported():
    """A point estimate alone is exactly what invariant 7 forbids."""
    with pytest.raises(ReportError, match="single observation"):
        reported("grounding", [3.0], a_version())


def test_reporting_nothing_is_refused():
    with pytest.raises(ReportError, match="no observations"):
        reported("grounding", [], a_version())


def test_an_estimate_outside_its_interval_cannot_be_built():
    with pytest.raises(ValueError, match="outside its own interval"):
        Estimate(value=9.0, ci_low=1.0, ci_high=2.0, method="x")


def test_identical_values_give_a_zero_width_interval_without_raising():
    """A genuinely known-exactly quantity is not an error."""
    number = reported("grounding", [3.0] * 8, a_version(), n_boot=200)
    assert number.estimate.width == pytest.approx(0.0)


def test_a_number_formats_with_its_interval():
    assert "[2.800, 3.200]" in a_number().format()


# ---------------------------------------------------------------------------
# The measurement-version guard
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "field,value",
    [
        ("corpus_fingerprint", "deadbeefdeadbeef"),
        ("rubric_hash", "x" * 16),
        ("prompt_hash", "y" * 16),
        ("k", 1),
        ("temperature", 0.0),
        ("aggregation_version", "2.0.0"),
        ("judge_set", ("gpt-z",)),
    ],
)
def test_gating_across_incompatible_versions_raises(field, value):
    """Milestone 11's acceptance check, one parameter at a time.

    Each of these changes what a number MEANS. A rubric edit, a prompt edit, a different judge
    set, a re-chunked corpus - any of them makes the two numbers answers to different questions.
    """
    current = a_number(value=2.5, low=2.3, high=2.7, version=a_version(**{field: value}))
    baseline = a_number(value=3.0, low=2.8, high=3.2)
    with pytest.raises(IncompatibleMeasurement) as excinfo:
        gate(current, baseline)
    assert field in str(excinfo.value)


def test_gating_the_same_version_is_allowed():
    assert gate(a_number(), a_number()).passed is True


def test_a_report_refuses_a_number_from_another_version():
    report = Report(run_id="r1", measurement_version=a_version())
    with pytest.raises(IncompatibleMeasurement):
        report.add(a_number(version=a_version(k=1)))


def test_a_report_accepts_a_number_from_its_own_version():
    version = a_version()
    report = Report(run_id="r1", measurement_version=version)
    report.add(a_number(version=version))
    assert len(report.numbers) == 1


# ---------------------------------------------------------------------------
# Gating on intervals, never on a point difference
# ---------------------------------------------------------------------------
def test_overlapping_intervals_do_not_fail_the_gate():
    """The failure this project started from: a 5-point gate on 8.3 points of noise."""
    current = a_number(value=2.6, low=2.2, high=3.0)
    baseline = a_number(value=3.0, low=2.7, high=3.3)
    result = gate(current, baseline)
    assert result.passed is True
    assert result.intervals_overlap is True
    assert "not distinguishable from noise" in result.reason


def test_separated_intervals_fail_the_gate():
    current = a_number(value=2.0, low=1.8, high=2.2)
    baseline = a_number(value=3.0, low=2.8, high=3.2)
    result = gate(current, baseline)
    assert result.passed is False
    assert "regression" in result.reason


def test_an_improvement_never_fails_the_gate():
    current = a_number(value=3.8, low=3.6, high=4.0)
    baseline = a_number(value=3.0, low=2.8, high=3.2)
    assert gate(current, baseline).passed is True


def test_a_drop_below_the_mde_does_not_fail_even_when_intervals_separate():
    """The design could not reliably detect a change this small even if it were real."""
    current = a_number(value=2.95, low=2.93, high=2.97)
    baseline = a_number(value=3.00, low=2.98, high=3.02)
    result = gate(current, baseline, mde=0.2)
    assert result.passed is True
    assert result.within_noise is True
    assert "below the minimum detectable effect" in result.reason


def test_a_drop_above_the_mde_with_separated_intervals_fails():
    current = a_number(value=2.0, low=1.9, high=2.1)
    baseline = a_number(value=3.0, low=2.9, high=3.1)
    result = gate(current, baseline, mde=0.2)
    assert result.passed is False
    assert result.within_noise is False


def test_direction_can_be_inverted_for_lower_is_better_metrics():
    """Cost and latency regress upward."""
    current = a_number(label="cost", value=3.0, low=2.9, high=3.1)
    baseline = a_number(label="cost", value=2.0, low=1.9, high=2.1)
    assert gate(current, baseline, higher_is_better=False).passed is False
    assert gate(current, baseline, higher_is_better=True).passed is True


def test_the_gate_result_serialises():
    payload = gate(a_number(), a_number()).to_dict()
    assert "reason" in payload and "intervals_overlap" in payload


# ---------------------------------------------------------------------------
# Declared test families
# ---------------------------------------------------------------------------
def test_a_test_not_declared_in_the_family_is_refused():
    """Declaring the family after seeing results controls nothing."""
    family = Family(name="per-dimension", declared=("grounding", "correctness"))
    with pytest.raises(ReportError, match="was not declared"):
        family.record(Result("temporal_integrity", 0.1, 0.01, 12))


def test_a_family_must_declare_something():
    with pytest.raises(ReportError, match="declares no tests"):
        Family(name="empty", declared=())


def test_a_family_cannot_declare_a_duplicate():
    with pytest.raises(ReportError, match="duplicate test name"):
        Family(name="dupes", declared=("a", "a"))


def test_the_same_test_cannot_be_recorded_twice():
    family = Family(name="f", declared=("a", "b"))
    family.record(Result("a", 0.1, 0.02, 12))
    with pytest.raises(ReportError, match="already recorded"):
        family.record(Result("a", 0.1, 0.02, 12))


def test_an_incomplete_family_cannot_be_adjusted():
    """Correcting across five tests when eight were declared understates the correction."""
    family = Family(name="f", declared=("a", "b", "c"))
    family.record(Result("a", 0.1, 0.001, 12))
    with pytest.raises(ReportError, match="incomplete"):
        family.adjust()


def test_adjustment_applies_bh_across_the_declared_family():
    family = Family(name="f", declared=("a", "b", "c", "d"))
    for name, p in (("a", 0.001), ("b", 0.02), ("c", 0.30), ("d", 0.80)):
        family.record(Result(name, 0.1, p, 12))
    results = family.adjust()
    assert all(r.p_adjusted is not None for r in results)
    assert all(r.p_adjusted >= r.p_raw for r in results)


def test_adjusted_p_values_are_monotone_in_the_raw_ones():
    family = Family(name="f", declared=("a", "b", "c"))
    for name, p in (("a", 0.001), ("b", 0.02), ("c", 0.40)):
        family.record(Result(name, 0.1, p, 12))
    adjusted = [r.p_adjusted for r in family.adjust()]
    assert adjusted == sorted(adjusted)


def test_a_family_cannot_grow_after_adjustment():
    family = Family(name="f", declared=("a", "b"))
    family.record(Result("a", 0.1, 0.01, 12))
    family.record(Result("b", 0.1, 0.02, 12))
    family.adjust()
    with pytest.raises(ReportError, match="already been adjusted"):
        family.record(Result("a", 0.1, 0.03, 12))


def test_raw_p_values_are_kept_alongside_adjusted():
    family = Family(name="f", declared=("a", "b"))
    family.record(Result("a", 0.1, 0.01, 12))
    family.record(Result("b", 0.1, 0.60, 12))
    family.adjust()
    payload = family.to_dict()
    assert all("p_raw" in r and "p_adjusted" in r for r in payload["results"])


def test_a_report_refuses_an_unadjusted_family():
    report = Report(run_id="r1", measurement_version=a_version())
    family = Family(name="f", declared=("a",))
    family.record(Result("a", 0.1, 0.01, 12))
    with pytest.raises(ReportError, match="not been FDR-adjusted"):
        report.add_family(family)


# ---------------------------------------------------------------------------
# Paired comparison
# ---------------------------------------------------------------------------
def test_identical_systems_are_not_significant():
    scores = [3.0, 2.0, 4.0, 1.0, 3.0, 2.0, 3.0, 4.0]
    result = compare_paired("waterbot vs realwater", scores, scores, n_permutations=1000)
    assert result.observed == 0.0
    assert result.p_raw > 0.9


def test_a_consistent_difference_is_significant():
    a = [4.0] * 20
    b = [2.0] * 20
    result = compare_paired("a vs b", a, b, n_permutations=1000)
    assert result.observed == pytest.approx(2.0)
    assert result.p_raw < 0.01


def test_the_comparison_records_the_item_count():
    assert compare_paired("x", [1.0, 2.0, 3.0], [1.0, 2.0, 3.0], n_permutations=200).n_items == 3


# ---------------------------------------------------------------------------
# Minimum detectable effect
# ---------------------------------------------------------------------------
def test_a_noisy_small_benchmark_needs_a_large_effect():
    """The number that stops a gate threshold being set below the noise floor."""
    import random

    rng = random.Random(0)
    null_differences = [rng.gauss(0.0, 1.0) for _ in range(12)]
    mde = minimum_detectable_effect(
        null_differences, n_simulations=80, n_permutations=250, seed=1
    )
    assert mde is not None
    assert mde > 0.5  # at n=12 with unit noise, only large differences are resolvable


def test_the_simulated_mde_agrees_with_the_closed_form_on_normal_data():
    """A cross-check, not a duplicate.

    The simulation makes no normality assumption, so on data that happens to be normal it should
    land close to the analytic answer. It runs slightly conservative because a permutation test
    on a bootstrap resample has a little less power than the normal approximation, and because
    the grid search returns the first step clearing the power target.
    """
    import random

    from eval.stats import minimum_detectable_effect as closed_form

    rng = random.Random(0)
    null_differences = [rng.gauss(0.0, 1.0) for _ in range(30)]
    simulated = minimum_detectable_effect(
        null_differences, n_simulations=100, n_permutations=300, seed=1
    )
    analytic = closed_form(sd=1.0, n=30)
    assert analytic <= simulated <= analytic * 1.8


def test_more_data_lowers_the_detectable_effect():
    import random

    rng = random.Random(0)
    small = [rng.gauss(0.0, 1.0) for _ in range(12)]
    rng = random.Random(0)
    large = [rng.gauss(0.0, 1.0) for _ in range(120)]
    mde_small = minimum_detectable_effect(small, n_simulations=60, n_permutations=250, seed=2)
    mde_large = minimum_detectable_effect(large, n_simulations=60, n_permutations=250, seed=2)
    assert mde_large < mde_small


def test_differences_with_no_noise_detect_anything():
    """Zero spread in the differences means any real shift is certain to be detected."""
    assert minimum_detectable_effect([0.0] * 10, n_simulations=10, n_permutations=50) == 0.0


def test_mde_needs_more_than_one_observation():
    with pytest.raises(ReportError, match="at least two"):
        minimum_detectable_effect([0.5])


def test_an_undetectable_design_returns_none():
    """Itself the finding: no gate threshold on this design means anything."""
    import random

    rng = random.Random(3)
    very_noisy = [rng.gauss(0.0, 5.0) for _ in range(4)]
    assert minimum_detectable_effect(
        very_noisy, n_simulations=30, n_permutations=100, seed=4, max_effect=0.01
    ) is None


def test_null_differences_are_built_from_paired_runs():
    assert null_differences_from([3.0, 2.0], [2.5, 2.0]) == [0.5, 0.0]


def test_null_differences_reject_mismatched_series():
    with pytest.raises(ReportError, match="paired series must match"):
        null_differences_from([1.0, 2.0], [1.0])


# ---------------------------------------------------------------------------
# The rendered report
# ---------------------------------------------------------------------------
def build_report() -> Report:
    version = a_version()
    report = Report(run_id="run-001", measurement_version=version)
    report.add(reported("grounding", [3.0, 3.5, 2.5, 3.0, 4.0, 2.0], version, n_boot=200))
    report.add(reported("correctness", [2.0, 2.5, 3.0, 2.0, 3.5, 2.5], version, n_boot=200))

    family = Family(name="per-dimension", declared=("grounding", "correctness"))
    family.record(compare_paired("grounding", [3, 3, 4, 3, 4, 3], [2, 2, 3, 2, 3, 2], 500))
    family.record(compare_paired("correctness", [2, 3, 2, 3, 2, 3], [2, 3, 2, 3, 2, 3], 500))
    family.adjust()
    report.add_family(family)

    report.gates.append(gate(a_number(version=version), a_number(version=version)))
    return report


def test_every_number_in_the_rendered_report_shows_an_interval():
    """Invariant 7, checked on the rendered output a reader actually sees."""
    markdown = build_report().to_markdown()
    results_section = markdown.split("## Results", 1)[1].split("## ", 1)[0]
    rows = [
        line for line in results_section.splitlines()
        if line.startswith("|") and not line.startswith("|---") and "Quantity" not in line
    ]
    assert rows
    for row in rows:
        assert "[" in row and "]" in row


def test_the_report_states_its_measurement_version():
    markdown = build_report().to_markdown()
    assert "measurement version" in markdown
    assert "08527fbdf140f811" in markdown


def test_the_report_shows_raw_and_adjusted_p_values():
    markdown = build_report().to_markdown()
    assert "p (raw)" in markdown and "p (adjusted)" in markdown


def test_the_report_names_how_many_tests_were_declared():
    assert "2 tests declared in advance" in build_report().to_markdown()


def test_the_report_serialises():
    payload = build_report().to_dict()
    assert payload["run_id"] == "run-001"
    assert len(payload["numbers"]) == 2
    assert payload["families"][0]["family"] == "per-dimension"
    assert "measurement_version_id" in payload
