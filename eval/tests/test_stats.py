"""Tests for eval/stats.py.

Every estimator here is checked three ways where possible: against an independent published
implementation (scipy, statsmodels), against a hand-computable case where the right answer is
known by construction, and on the degenerate inputs that make naive implementations lie.

Network-free.
"""

from __future__ import annotations

import math

import pytest

from eval.stats import (
    Z_90,
    Z_95,
    Z_POWER_80,
    Estimate,
    VarianceComponents,
    benjamini_hochberg,
    clustered_bootstrap,
    clustered_bootstrap_ci,
    minimum_detectable_effect,
    paired_permutation_test,
    percentile_ci,
    variance_components,
    wilson_interval,
    _inverse_normal_cdf,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
def test_z_constants_match_scipy():
    scipy_stats = pytest.importorskip("scipy.stats")
    assert Z_95 == pytest.approx(scipy_stats.norm.ppf(0.975), abs=1e-12)
    assert Z_90 == pytest.approx(scipy_stats.norm.ppf(0.95), abs=1e-12)
    assert Z_POWER_80 == pytest.approx(scipy_stats.norm.ppf(0.80), abs=1e-12)


@pytest.mark.parametrize("p", [0.001, 0.01, 0.025, 0.2, 0.5, 0.8, 0.975, 0.99, 0.999])
def test_inverse_normal_cdf_matches_scipy(p):
    scipy_stats = pytest.importorskip("scipy.stats")
    assert _inverse_normal_cdf(p) == pytest.approx(scipy_stats.norm.ppf(p), abs=1e-8)


# ---------------------------------------------------------------------------
# Wilson
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "successes,trials", [(0, 12), (5, 12), (12, 12), (2, 20), (150, 300), (1, 1), (7, 12)]
)
def test_wilson_matches_statsmodels(successes, trials):
    proportion = pytest.importorskip("statsmodels.stats.proportion")
    expected = proportion.proportion_confint(successes, trials, alpha=0.05, method="wilson")
    assert wilson_interval(successes, trials) == pytest.approx(expected, abs=1e-10)


def test_wilson_published_worked_example():
    """Brown, Cai & DasGupta (2001), n=20, X=2."""
    lo, hi = wilson_interval(2, 20)
    assert lo == pytest.approx(0.0278, abs=5e-4)
    assert hi == pytest.approx(0.3010, abs=5e-4)


def test_wilson_does_not_claim_certainty_at_the_boundary():
    lo, hi = wilson_interval(12, 12)
    assert hi == pytest.approx(1.0)
    assert 0.0 < lo < 1.0


def test_wilson_zero_trials_is_uninformative():
    assert wilson_interval(0, 0) == (0.0, 1.0)


@pytest.mark.parametrize("successes,trials", [(-1, 10), (11, 10), (0, -1)])
def test_wilson_rejects_impossible_counts(successes, trials):
    with pytest.raises(ValueError):
        wilson_interval(successes, trials)


# ---------------------------------------------------------------------------
# Clustered bootstrap
# ---------------------------------------------------------------------------
def mean_of_means(clusters):
    return sum(sum(c) / len(c) for c in clusters) / len(clusters)


def test_bootstrap_is_reproducible_by_seed():
    clusters = [[1.0, 1.0], [0.0, 0.0], [1.0, 0.0], [1.0, 1.0]]
    assert clustered_bootstrap(clusters, mean_of_means, 200, seed=5) == clustered_bootstrap(
        clusters, mean_of_means, 200, seed=5
    )


def test_bootstrap_differs_with_seed():
    clusters = [[1.0, 1.0], [0.0, 0.0], [1.0, 0.0], [1.0, 1.0]]
    assert clustered_bootstrap(clusters, mean_of_means, 200, seed=1) != clustered_bootstrap(
        clusters, mean_of_means, 200, seed=2
    )


def test_bootstrap_returns_the_requested_number_of_draws():
    assert len(clustered_bootstrap([[1.0], [2.0]], mean_of_means, 137, seed=0)) == 137


def test_bootstrap_of_identical_clusters_has_zero_width():
    lo, hi = clustered_bootstrap_ci([[1.0]] * 10, mean_of_means, 500, seed=0)
    assert lo == pytest.approx(hi)


def test_clustered_interval_is_wider_than_wilson_when_clustering_is_real():
    """The reason both are reported anywhere clustered data appears.

    Five items always 1, seven always 0: huge between-item spread, no within-item spread. Wilson
    sees 125 iid successes in 300 and reports a tight interval; the clustered interval is honest
    about how little is known about the next item.
    """
    clusters = [[1.0] * 25 for _ in range(5)] + [[0.0] * 25 for _ in range(7)]
    wilson_lo, wilson_hi = wilson_interval(125, 300)
    boot_lo, boot_hi = clustered_bootstrap_ci(clusters, mean_of_means, 2000, seed=0)
    assert (boot_hi - boot_lo) > 3 * (wilson_hi - wilson_lo)


def test_bootstrap_rejects_an_empty_sample():
    with pytest.raises(ValueError, match="empty sample"):
        clustered_bootstrap([], mean_of_means)


def test_percentile_ci_brackets_the_bulk_of_the_draws():
    draws = [float(i) for i in range(1000)]
    lo, hi = percentile_ci(draws, alpha=0.05)
    assert lo == pytest.approx(25, abs=2)
    assert hi == pytest.approx(974, abs=2)


def test_percentile_ci_rejects_a_bad_alpha():
    with pytest.raises(ValueError):
        percentile_ci([1.0, 2.0], alpha=1.5)


# ---------------------------------------------------------------------------
# Permutation test
# ---------------------------------------------------------------------------
def test_identical_systems_are_not_significant():
    scores = [3.0, 2.0, 4.0, 1.0, 3.0, 2.0]
    result = paired_permutation_test(scores, scores, n_permutations=2000, seed=0)
    assert result.observed == 0.0
    assert result.p_value > 0.9


def test_a_large_consistent_difference_is_significant():
    a = [4.0] * 20
    b = [1.0] * 20
    result = paired_permutation_test(a, b, n_permutations=2000, seed=0)
    assert result.observed == pytest.approx(3.0)
    assert result.p_value < 0.01


def test_p_value_is_never_exactly_zero():
    """With B permutations the smallest honest claim is 1/(B+1), not 0."""
    result = paired_permutation_test([4.0] * 30, [1.0] * 30, n_permutations=1000, seed=0)
    assert result.p_value == pytest.approx(1 / 1001)
    assert result.p_value > 0


def test_permutation_is_reproducible_by_seed():
    a, b = [3.0, 1.0, 4.0, 1.0, 5.0], [2.0, 2.0, 3.0, 1.0, 4.0]
    first = paired_permutation_test(a, b, n_permutations=500, seed=7)
    second = paired_permutation_test(a, b, n_permutations=500, seed=7)
    assert first.p_value == second.p_value


def test_permutation_requires_paired_input():
    with pytest.raises(ValueError, match="equal lengths"):
        paired_permutation_test([1.0, 2.0], [1.0])


def test_permutation_rejects_empty_input():
    with pytest.raises(ValueError, match="empty sample"):
        paired_permutation_test([], [])


# ---------------------------------------------------------------------------
# Benjamini-Hochberg
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "p_values",
    [
        [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205, 0.212, 0.216],
        [0.01, 0.02, 0.03, 0.04, 0.05],
        [0.5],
        [0.001, 0.001, 0.001],
        [0.9, 0.8, 0.7, 0.01],
    ],
)
def test_bh_matches_statsmodels(p_values):
    multitest = pytest.importorskip("statsmodels.stats.multitest")
    expected_rejected, expected_adjusted, _, _ = multitest.multipletests(
        p_values, alpha=0.05, method="fdr_bh"
    )
    adjusted, rejected = benjamini_hochberg(p_values, alpha=0.05)
    assert adjusted == pytest.approx(list(expected_adjusted), abs=1e-12)
    assert rejected == list(expected_rejected)


def test_bh_preserves_input_order():
    """Adjusted values must line up with the tests that produced them."""
    adjusted, _ = benjamini_hochberg([0.5, 0.001, 0.2])
    assert adjusted[1] < adjusted[2] < adjusted[0]


def test_bh_is_monotone():
    p_values = [0.001, 0.02, 0.03, 0.5, 0.9]
    adjusted, _ = benjamini_hochberg(p_values)
    assert adjusted == sorted(adjusted)


def test_bh_never_exceeds_one():
    adjusted, _ = benjamini_hochberg([0.9, 0.95, 0.99])
    assert all(p <= 1.0 for p in adjusted)


def test_bh_on_an_empty_family():
    assert benjamini_hochberg([]) == ([], [])


def test_bh_rejects_values_outside_the_unit_interval():
    with pytest.raises(ValueError):
        benjamini_hochberg([0.5, 1.5])


def test_bh_is_less_aggressive_than_bonferroni():
    """The reason to use it: Bonferroni over 30 tests would reject almost nothing."""
    p_values = [0.001 * i for i in range(1, 31)]
    adjusted, rejected = benjamini_hochberg(p_values, alpha=0.05)
    bonferroni_rejections = sum(1 for p in p_values if p * len(p_values) <= 0.05)
    assert sum(rejected) > bonferroni_rejections


# ---------------------------------------------------------------------------
# Minimum detectable effect
# ---------------------------------------------------------------------------
def test_mde_matches_the_closed_form():
    mde = minimum_detectable_effect(sd=1.0, n=100, alpha=0.05, power=0.80, paired=True)
    assert mde == pytest.approx((Z_95 + Z_POWER_80) * 0.1, abs=1e-9)


def test_mde_shrinks_with_more_data():
    assert minimum_detectable_effect(1.0, 1000) < minimum_detectable_effect(1.0, 10)


def test_mde_grows_with_noise():
    assert minimum_detectable_effect(2.0, 50) > minimum_detectable_effect(1.0, 50)


def test_unpaired_designs_need_a_larger_effect():
    """Pairing is what buys power when items differ more than systems do."""
    assert minimum_detectable_effect(1.0, 50, paired=False) > minimum_detectable_effect(
        1.0, 50, paired=True
    )


def test_mde_exposes_a_gate_narrower_than_its_noise_floor():
    """The concrete failure in the current harness: a 5-point gate on 8.3 points of swing.

    The unit of the CI gate is a RUN, not an item: it compares one run's headline number against
    a baseline run's. So n is the number of runs compared, which is 2. At a run-to-run standard
    deviation of about 4 points - one item flipping on twelve - the smallest difference the gate
    can actually resolve is around 8 points, so a 5-point threshold fires on noise.
    """
    run_to_run_sd_points = 4.0
    mde_points = minimum_detectable_effect(sd=run_to_run_sd_points, n=2)
    assert mde_points > 5.0

    # Averaging over more runs is what would make a 5-point gate meaningful.
    assert minimum_detectable_effect(sd=run_to_run_sd_points, n=12) < 5.0


@pytest.mark.parametrize("kwargs", [{"sd": -1.0, "n": 10}, {"sd": 1.0, "n": 1}])
def test_mde_rejects_impossible_designs(kwargs):
    with pytest.raises(ValueError):
        minimum_detectable_effect(**kwargs)


# ---------------------------------------------------------------------------
# Variance components
# ---------------------------------------------------------------------------
def build_scores(item_effects, judge_effects, replicates=2, noise=None):
    """Construct a balanced design with known components."""
    scores = {}
    for i, item_effect in enumerate(item_effects):
        for j, judge_effect in enumerate(judge_effects):
            values = []
            for r in range(replicates):
                extra = 0.0 if noise is None else noise[(i, j, r)]
                values.append(item_effect + judge_effect + extra)
            scores[(f"item{i}", f"judge{j}")] = values
    return scores


def test_pure_item_variance_is_attributed_to_items():
    """Judges agree perfectly and never wobble: all variance is real item difference."""
    scores = build_scores([1.0, 2.0, 3.0, 4.0], [0.0, 0.0, 0.0])
    components = variance_components(scores)
    assert components.sigma2_items > 1.0
    assert components.sigma2_judges == pytest.approx(0.0, abs=1e-9)
    assert components.sigma2_interaction == pytest.approx(0.0, abs=1e-9)
    assert components.sigma2_residual == pytest.approx(0.0, abs=1e-9)
    assert components.generalizability() == pytest.approx(1.0)


def test_pure_judge_variance_is_attributed_to_judges():
    """Judges disagree on level but rank items identically: severity, not noise about items."""
    scores = build_scores([0.0, 0.0, 0.0, 0.0], [1.0, 2.0, 3.0])
    components = variance_components(scores)
    assert components.sigma2_judges > 0.5
    assert components.sigma2_items == pytest.approx(0.0, abs=1e-9)


def test_replicate_noise_lands_in_the_residual():
    noise = {}
    for i in range(4):
        for j in range(3):
            noise[(i, j, 0)] = 0.5
            noise[(i, j, 1)] = -0.5
    scores = build_scores([1.0, 2.0, 3.0, 4.0], [0.0, 0.0, 0.0], noise=noise)
    components = variance_components(scores)
    # Each cell holds {mean+0.5, mean-0.5}. The unbiased variance of two points half a unit
    # either side of their mean is (0.5^2 + 0.5^2) / (2-1) = 0.5, which is what an ANOVA mean
    # square estimates. 0.25 would be the population variance, which is not the estimand.
    assert components.sigma2_residual == pytest.approx(0.5, abs=1e-9)
    assert components.sigma2_items > 0.0


def test_generalizability_improves_with_more_judges():
    """The decision-study question: does adding judges buy precision here?"""
    components = VarianceComponents(
        sigma2_items=1.0, sigma2_judges=0.2, sigma2_interaction=0.6,
        sigma2_residual=0.4, n_items=12, n_judges=1, n_replicates=1,
    )
    assert components.generalizability(3, 1) > components.generalizability(1, 1)


def test_decision_study_finds_the_cheapest_adequate_design():
    components = VarianceComponents(
        sigma2_items=1.0, sigma2_judges=0.1, sigma2_interaction=0.5,
        sigma2_residual=0.5, n_items=12, n_judges=1, n_replicates=1,
    )
    design = components.decision_study(target=0.80)
    assert design is not None
    m, k = design
    assert components.generalizability(m, k) >= 0.80
    # Nothing strictly cheaper clears the bar.
    for cheaper_m in range(1, m + 1):
        for cheaper_k in range(1, k + 1):
            if cheaper_m * cheaper_k < m * k:
                assert components.generalizability(cheaper_m, cheaper_k) < 0.80


def test_decision_study_returns_none_when_the_target_is_unreachable():
    """An honest 'more judges will not save this' rather than a silently capped answer."""
    hopeless = VarianceComponents(
        sigma2_items=0.001, sigma2_judges=0.1, sigma2_interaction=5.0,
        sigma2_residual=5.0, n_items=12, n_judges=3, n_replicates=5,
    )
    assert hopeless.decision_study(target=0.95, max_judges=4, max_replicates=4) is None


def test_single_replicate_designs_confound_interaction_and_residual():
    """Reported as residual 0 rather than pretending the two can be separated."""
    scores = build_scores([1.0, 2.0, 3.0], [0.0, 0.5], replicates=1)
    components = variance_components(scores)
    assert components.sigma2_residual == 0.0
    assert components.n_replicates == 1


def test_unbalanced_designs_are_rejected():
    scores = {("i1", "j1"): [1.0, 2.0], ("i1", "j2"): [1.0], ("i2", "j1"): [1.0, 2.0],
              ("i2", "j2"): [1.0, 1.0]}
    with pytest.raises(ValueError, match="balanced"):
        variance_components(scores)


def test_incomplete_designs_are_rejected():
    """A missing cell silently averaged over would understate the noise."""
    scores = {("i1", "j1"): [1.0], ("i1", "j2"): [1.0], ("i2", "j1"): [1.0]}
    with pytest.raises(ValueError, match="complete"):
        variance_components(scores)


def test_too_few_judges_is_rejected():
    scores = {("i1", "j1"): [1.0], ("i2", "j1"): [2.0]}
    with pytest.raises(ValueError, match="at least 2 items and 2 judges"):
        variance_components(scores)


def test_components_serialise():
    scores = build_scores([1.0, 2.0, 3.0], [0.0, 0.2])
    payload = variance_components(scores).to_dict()
    assert "generalizability" in payload and "sigma2_items" in payload


# ---------------------------------------------------------------------------
# Estimate
# ---------------------------------------------------------------------------
def test_estimate_requires_the_value_inside_its_interval():
    with pytest.raises(ValueError, match="outside its own interval"):
        Estimate(value=5.0, ci_low=1.0, ci_high=2.0, method="bootstrap")


def test_estimate_rejects_an_inverted_interval():
    with pytest.raises(ValueError, match="exceeds ci_high"):
        Estimate(value=1.5, ci_low=2.0, ci_high=1.0, method="bootstrap")


def test_estimate_formats_with_its_interval():
    estimate = Estimate(value=0.4467, ci_low=0.1967, ci_high=0.6967, method="clustered", n=12)
    assert estimate.format() == "0.447 [0.197, 0.697]"
    assert estimate.width == pytest.approx(0.5)


def test_a_degenerate_interval_is_allowed():
    """A genuinely known-exactly quantity, e.g. a count, is not an error."""
    assert Estimate(value=1.0, ci_low=1.0, ci_high=1.0, method="exact").width == 0.0
