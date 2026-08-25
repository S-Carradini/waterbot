"""Tests for L4 agreement statistics.

ON GOLDEN TESTS FOR ALPHA
-------------------------
Milestone 8 asks for golden tests reproducing published values. For Cohen's kappa, Spearman and
balanced accuracy that is straightforward: sklearn and scipy are independent implementations and
are checked against directly.

For Krippendorff's alpha there is no independent implementation installed - deliberately, since
implementing it rather than adding the package was the decision. Rather than assert against a
constant recalled from a paper, which would be worse than no test if the recall were wrong, alpha
is pinned three ways that can each be verified from first principles:

* a fully hand-computed coincidence matrix, worked out in the test's own comment
* the exact identity relating alpha to Scott's pi for two coders with complete data,
  ``1 - alpha = (1 - pi) * (2N-1)/(2N)``, which holds to machine precision at every sample size
* structural invariants: perfect agreement is 1, no variation is undefined, systematic
  disagreement is negative

Gwet's AC1 is checked against the Cicchetti-Feinstein kappa-paradox table, hand-computed in the
test comment.

Network-free.
"""

from __future__ import annotations

import math
from collections import Counter

import pytest

from eval.judge.agreement import (
    AgreementError,
    agreement_report,
    balanced_accuracy,
    cohens_kappa,
    compare_to_ceiling,
    gwet_ac,
    krippendorff_alpha,
    mae_in_levels,
    raw_agreement,
    spearman_rho,
)

N = None


def scotts_pi(a, b):
    """Independent reference for the alpha identity below."""
    n = len(a)
    disagreements = sum(1 for x, y in zip(a, b) if x != y)
    p_o = 1 - disagreements / n
    counts = Counter(a) + Counter(b)
    p_e = sum((v / (2 * n)) ** 2 for v in counts.values())
    return (p_o - p_e) / (1 - p_e)


# ---------------------------------------------------------------------------
# Krippendorff's alpha
# ---------------------------------------------------------------------------
def test_alpha_matches_a_hand_computed_coincidence_matrix():
    """Two coders, four units, nominal.

        A: 1 1 2 2
        B: 1 2 2 2

    Unit 2 is the only disagreement. Every unit has m=2, so each ordered pair carries weight 1.
    Coincidences: o[1,1]=2, o[1,2]=1, o[2,1]=1, o[2,2]=4, so n=8, n_1=3, n_2=5.
    Observed disagreement sums to 2; expected sums to 2*3*5 = 30.
    alpha = 1 - (n-1) * 2 / 30 = 1 - 14/30 = 0.533333...
    """
    assert krippendorff_alpha([[1, 1, 2, 2], [1, 2, 2, 2]], "nominal") == pytest.approx(
        1 - 14 / 30, abs=1e-9
    )


@pytest.mark.parametrize("n_units,seed", [(8, 0), (25, 1), (60, 2), (200, 3)])
def test_alpha_satisfies_the_scotts_pi_identity(n_units, seed):
    """For two coders with complete data, 1 - alpha = (1 - pi) * (2N-1)/(2N), exactly.

    An analytic identity, so it pins the implementation harder than a rounded published constant
    would, and at every sample size rather than one.
    """
    import random

    rng = random.Random(seed)
    a = [rng.randint(1, 4) for _ in range(n_units)]
    b = [x if rng.random() < 0.7 else rng.randint(1, 4) for x in a]

    alpha = krippendorff_alpha([a, b], "nominal")
    predicted = 1 - (1 - scotts_pi(a, b)) * (2 * n_units - 1) / (2 * n_units)
    assert alpha == pytest.approx(predicted, abs=1e-12)


def test_perfect_agreement_is_one():
    assert krippendorff_alpha([[1, 2, 3, 4], [1, 2, 3, 4]], "nominal") == 1.0


def test_no_variation_is_undefined_not_perfect():
    """Expected disagreement is zero, so alpha is 0/0.

    Returning 1.0 would claim perfect reliability from data that could not have detected
    disagreement in the first place.
    """
    assert krippendorff_alpha([[2, 2, 2], [2, 2, 2]], "nominal") is None


def test_systematic_disagreement_is_negative():
    assert krippendorff_alpha([[1, 2], [2, 1]], "nominal") < 0


def test_ordinal_alpha_differs_from_nominal_on_ordered_data():
    """Being one level apart should cost less than being three levels apart."""
    matrix = [[1, 2, 3, 4, 1, 2], [1, 2, 3, 4, 2, 1]]
    assert krippendorff_alpha(matrix, "ordinal") != krippendorff_alpha(matrix, "nominal")


def test_ordinal_treats_a_near_miss_more_kindly_than_a_far_one():
    near = [[1, 2, 3, 4], [1, 2, 3, 3]]
    far = [[1, 2, 3, 4], [1, 2, 3, 1]]
    assert krippendorff_alpha(near, "ordinal") > krippendorff_alpha(far, "ordinal")


def test_interval_alpha_is_available():
    assert krippendorff_alpha([[1, 2, 3, 4], [1, 2, 3, 3]], "interval") is not None


def test_missing_entries_are_skipped_not_imputed():
    """The reason the architecture chose alpha: abstentions are a native case."""
    complete = krippendorff_alpha([[1, 2, 3, 4], [1, 2, 3, 4]], "nominal")
    with_missing = krippendorff_alpha([[1, 2, 3, 4, 1], [1, 2, 3, 4, N]], "nominal")
    assert with_missing == complete  # the unpaired unit contributes nothing


def test_a_unit_rated_once_contributes_nothing():
    assert krippendorff_alpha([[1, 2, 3], [1, 2, N]], "nominal") == krippendorff_alpha(
        [[1, 2], [1, 2]], "nominal"
    )


def test_alpha_is_undefined_when_nothing_is_rated_twice():
    assert krippendorff_alpha([[1, N], [N, 2]], "nominal") is None


def test_three_coders_are_supported():
    matrix = [[1, 2, 3, 4], [1, 2, 3, 4], [1, 2, 3, 3]]
    assert 0 < krippendorff_alpha(matrix, "ordinal") < 1


def test_an_unknown_level_of_measurement_is_rejected():
    with pytest.raises(AgreementError, match="unknown level_of_measurement"):
        krippendorff_alpha([[1, 2], [1, 2]], "vibes")


def test_ragged_rows_are_rejected():
    with pytest.raises(AgreementError, match="same units"):
        krippendorff_alpha([[1, 2, 3], [1, 2]], "nominal")


def test_an_empty_matrix_is_rejected():
    with pytest.raises(AgreementError, match="empty matrix"):
        krippendorff_alpha([], "nominal")


# ---------------------------------------------------------------------------
# Cohen's kappa, against sklearn
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("weights", [None, "linear", "quadratic"])
def test_kappa_matches_sklearn(weights):
    sklearn_metrics = pytest.importorskip("sklearn.metrics")
    a = [1, 2, 3, 4, 1, 2, 3, 4, 2, 2, 3, 1]
    b = [1, 2, 3, 3, 1, 3, 3, 4, 2, 1, 3, 2]
    expected = sklearn_metrics.cohen_kappa_score(a, b, weights=weights)
    assert cohens_kappa(a, b, weights) == pytest.approx(expected, abs=1e-9)


def test_kappa_of_perfect_agreement_is_one():
    assert cohens_kappa([1, 2, 3, 4], [1, 2, 3, 4]) == pytest.approx(1.0)


def test_kappa_drops_incomplete_pairs():
    assert cohens_kappa([1, 2, 3, N], [1, 2, 3, 4]) == cohens_kappa([1, 2, 3], [1, 2, 3])


def test_kappa_is_undefined_when_one_category_is_used_throughout():
    assert cohens_kappa([2, 2, 2], [2, 2, 2]) is None


def test_kappa_of_no_complete_pairs_is_none():
    assert cohens_kappa([N, N], [1, 2]) is None


def test_kappa_rejects_unequal_lengths():
    with pytest.raises(AgreementError, match="same items"):
        cohens_kappa([1, 2], [1])


def test_kappa_rejects_unknown_weights():
    with pytest.raises(AgreementError, match="unknown weights"):
        cohens_kappa([1, 2], [1, 2], "cubic")


# ---------------------------------------------------------------------------
# The kappa paradox, and Gwet's answer to it
# ---------------------------------------------------------------------------
def paradox_table():
    """Cicchetti-Feinstein: 118 both-positive, 5 and 2 disagreements, 0 both-negative.

    n=125, raw agreement 118/125 = 0.944.

    Kappa: p_o = 0.944; marginals 123/125 and 120/125, so
    p_e = 0.984*0.96 + 0.016*0.04 = 0.94528, and kappa = (0.944-0.94528)/(1-0.94528) = -0.0234.

    Gwet AC1: pi_+ = (123+120)/250 = 0.972, pi_- = 0.028,
    p_e = 0.972*0.028 + 0.028*0.972 = 0.054432,
    AC1 = (0.944 - 0.054432)/(1 - 0.054432) = 0.9408.
    """
    a = [1] * 118 + [1] * 5 + [0] * 2
    b = [1] * 118 + [0] * 5 + [1] * 2
    return a, b


def test_raw_agreement_on_the_paradox_table():
    a, b = paradox_table()
    assert raw_agreement(a, b) == pytest.approx(0.944, abs=1e-4)


def test_kappa_collapses_under_high_prevalence():
    """The failure this module exists to prevent: 94% agreement, kappa below zero."""
    a, b = paradox_table()
    assert cohens_kappa(a, b) == pytest.approx(-0.0234, abs=1e-3)


def test_gwet_ac1_survives_high_prevalence():
    """Hand-computed above: 0.9408, against kappa's -0.0234 on identical data."""
    a, b = paradox_table()
    assert gwet_ac([a, b], weights=None) == pytest.approx(0.9408, abs=1e-4)


def test_the_report_flags_a_suspected_kappa_paradox():
    """The flag stays active even though AC2 is deferred - it is the warning, not the fix."""
    a, b = paradox_table()
    report = agreement_report([a, b], label="refusal")
    assert report.kappa_paradox_suspected is True
    assert report.gwet_ac2 is None  # deferred by decision 028


def test_the_deferred_ac2_still_answers_the_paradox_when_asked():
    """Kept working and tested, so activating it later is a one-line change."""
    a, b = paradox_table()
    report = agreement_report([a, b], label="refusal", include_deferred=True)
    assert report.kappa_quadratic < 0.4 < report.gwet_ac2


def test_a_balanced_set_does_not_trip_the_paradox_flag():
    a = [1, 2, 3, 4] * 10
    report = agreement_report([a, a], label="balanced")
    assert report.kappa_paradox_suspected is False


def test_gwet_of_perfect_agreement_is_one():
    assert gwet_ac([[1, 2, 3, 4], [1, 2, 3, 4]], weights=None) == pytest.approx(1.0)


def test_weighted_gwet_is_kinder_to_near_misses():
    near = [[1, 2, 3, 4], [1, 2, 3, 3]]
    assert gwet_ac(near, "quadratic") > gwet_ac(near, weights=None)


def test_gwet_supports_more_than_two_raters():
    assert gwet_ac([[1, 2, 3], [1, 2, 3], [1, 2, 4]], "quadratic") is not None


def test_gwet_is_none_when_nothing_is_rated_twice():
    assert gwet_ac([[1, N], [N, 2]], "quadratic") is None


def test_gwet_is_none_with_a_single_category():
    assert gwet_ac([[1, 1], [1, 1]], weights=None) is None


# ---------------------------------------------------------------------------
# Spearman, MAE, balanced accuracy
# ---------------------------------------------------------------------------
def test_spearman_matches_scipy():
    scipy_stats = pytest.importorskip("scipy.stats")
    a = [1, 2, 3, 4, 2, 3, 1, 4]
    b = [1, 3, 3, 4, 2, 2, 1, 3]
    assert spearman_rho(a, b) == pytest.approx(scipy_stats.spearmanr(a, b).statistic, abs=1e-9)


def test_spearman_handles_ties_with_midranks():
    scipy_stats = pytest.importorskip("scipy.stats")
    a = [1, 1, 2, 2, 3, 3]
    b = [1, 2, 2, 3, 3, 4]
    assert spearman_rho(a, b) == pytest.approx(scipy_stats.spearmanr(a, b).statistic, abs=1e-9)


def test_spearman_of_a_constant_series_is_undefined():
    assert spearman_rho([2, 2, 2, 2], [1, 2, 3, 4]) is None


def test_spearman_needs_two_points():
    assert spearman_rho([1], [1]) is None


def test_mae_is_in_levels():
    assert mae_in_levels([1, 2, 3, 4], [2, 2, 3, 3]) == pytest.approx(0.5)


def test_mae_ignores_incomplete_pairs():
    assert mae_in_levels([1, 2, N], [2, 2, 4]) == pytest.approx(0.5)


def test_balanced_accuracy_matches_sklearn():
    sklearn_metrics = pytest.importorskip("sklearn.metrics")
    truth = [1, 1, 1, 1, 1, 1, 1, 1, 0, 0]
    predicted = [1, 1, 1, 1, 1, 1, 1, 0, 0, 1]
    assert balanced_accuracy(truth, predicted) == pytest.approx(
        sklearn_metrics.balanced_accuracy_score(truth, predicted), abs=1e-9
    )


def test_balanced_accuracy_punishes_ignoring_the_rare_class():
    """Plain accuracy would reward always predicting the majority; this must not."""
    truth = [1] * 18 + [0] * 2
    always_majority = [1] * 20
    assert balanced_accuracy(truth, always_majority) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------
def test_only_the_active_metrics_are_computed_by_default():
    """Decision 028: kappa is in use; the other four are built but not reported."""
    a = [1, 2, 3, 4, 2, 3]
    b = [1, 2, 3, 3, 2, 4]
    payload = agreement_report([a, b], label="grounding").to_dict()

    for key in ("raw_agreement", "kappa_quadratic", "kappa_unweighted", "mean_pairwise_kappa"):
        assert payload[key] is not None, f"{key} is active and must be computed"
    for key in ("gwet_ac2", "alpha_ordinal", "spearman", "mae_levels"):
        assert payload[key] is None, f"{key} is deferred and must not be reported by default"
    assert payload["includes_deferred"] is False


def test_the_deferred_metrics_can_still_be_computed_deliberately():
    """The flag is for the analysis that decides whether to activate them, not for reporting."""
    a = [1, 2, 3, 4, 2, 3]
    b = [1, 2, 3, 3, 2, 4]
    payload = agreement_report([a, b], label="grounding", include_deferred=True).to_dict()
    for key in ("gwet_ac2", "alpha_ordinal", "spearman", "mae_levels"):
        assert payload[key] is not None
    assert payload["includes_deferred"] is True


def test_the_report_names_which_metrics_are_active():
    """So a deferred number can never be mistaken for a chosen one."""
    payload = agreement_report([[1, 2, 3], [1, 2, 4]]).to_dict()
    assert "cohens_kappa" in payload["active_metrics"]
    assert "krippendorff_alpha" in payload["deferred_metrics"]


def test_the_report_records_how_much_was_missing():
    """Every statistic here uses complete observations only; the reader needs the denominator."""
    report = agreement_report([[1, 2, N, 4], [1, 2, 3, N]], label="x")
    assert report.n_missing == 2
    assert report.missing_rate == pytest.approx(0.25)
    assert report.n_pairs == 2


def test_a_single_rater_yields_no_pairwise_statistics():
    report = agreement_report([[1, 2, 3]], label="lonely")
    assert report.raw is None and report.kappa_quadratic is None


def test_the_report_rejects_ragged_input():
    with pytest.raises(AgreementError, match="same units"):
        agreement_report([[1, 2], [1]])


# ---------------------------------------------------------------------------
# The human ceiling
# ---------------------------------------------------------------------------
def test_a_judge_matching_the_humans_is_at_the_ceiling():
    humans = [[1, 2, 3, 4, 2, 3, 1, 4], [1, 2, 3, 3, 2, 4, 1, 4]]
    judges = [[1, 2, 3, 4, 2, 3, 1, 4], [1, 2, 3, 3, 2, 4, 1, 4]]
    comparison = compare_to_ceiling(humans, judges, "grounding")
    assert comparison.fraction_of_ceiling == pytest.approx(1.0)
    assert comparison.verdict == "at the human ceiling"


def test_a_judge_below_the_humans_is_reported_as_such():
    humans = [[1, 2, 3, 4, 1, 2, 3, 4], [1, 2, 3, 4, 1, 2, 3, 4]]
    judges = [[1, 2, 3, 4, 1, 2, 3, 4], [4, 3, 2, 1, 4, 3, 2, 1]]
    comparison = compare_to_ceiling(humans, judges, "grounding")
    assert comparison.fraction_of_ceiling < 0.5
    assert "below the human ceiling" in comparison.verdict


def test_the_ceiling_is_computed_from_kappa_while_alpha_is_deferred():
    """Decision 028's knock-on: the ceiling was alpha-based and is now kappa-based."""
    humans = [[1, 2, 3, 4, 2, 3, 1, 4], [1, 2, 3, 3, 2, 4, 1, 4]]
    comparison = compare_to_ceiling(humans, humans, "grounding")
    assert comparison.ceiling == comparison.human.mean_pairwise_kappa
    assert comparison.human.alpha_ordinal is None


def test_three_annotators_are_not_reduced_to_the_first_two():
    """Cohen's kappa is pairwise; without alpha, a third annotator would otherwise be ignored."""
    three = [[1, 2, 3, 4, 1, 2], [1, 2, 3, 3, 1, 2], [1, 3, 3, 4, 1, 3]]
    report = agreement_report(three)
    assert report.n_raters == 3
    assert report.n_rater_pairs == 3
    assert report.mean_pairwise_kappa is not None


def test_a_modest_judge_score_can_still_be_near_ceiling():
    """The point of the whole layer.

    Humans agreeing at alpha 0.6 means 0.6 is roughly the best anything can do. A judge at 0.55
    is performing well, and reporting 0.55 alone would read as failure.
    """
    import random

    rng = random.Random(0)
    truth = [rng.randint(1, 4) for _ in range(60)]
    noisy = lambda p: [  # noqa: E731
        x if rng.random() < p else rng.randint(1, 4) for x in truth
    ]
    humans = [noisy(0.75), noisy(0.75)]
    judges = [noisy(0.72), noisy(0.72)]

    comparison = compare_to_ceiling(humans, judges, "grounding")
    assert comparison.ceiling < 0.8  # humans do not agree perfectly either
    assert comparison.fraction_of_ceiling > 0.5


def test_an_undefined_ceiling_blocks_interpretation():
    """If the humans did not agree above chance, no judge number on that dimension means much."""
    humans = [[1, 2, 3, 4], [4, 3, 2, 1]]
    judges = [[1, 2, 3, 4], [1, 2, 3, 4]]
    comparison = compare_to_ceiling(humans, judges, "correctness")
    assert comparison.fraction_of_ceiling is None
    assert "undefined" in comparison.verdict


def test_the_comparison_serialises_with_both_sides():
    humans = [[1, 2, 3, 4], [1, 2, 3, 3]]
    judges = [[1, 2, 3, 4], [1, 2, 3, 4]]
    payload = compare_to_ceiling(humans, judges, "grounding").to_dict()
    assert payload["dimension"] == "grounding"
    assert "human" in payload and "judge" in payload
    assert "verdict" in payload
