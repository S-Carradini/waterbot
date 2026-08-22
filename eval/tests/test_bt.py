"""Tests for the Bradley-Terry / Davidson fit (L3).

Milestone 8 asks for golden tests that reproduce published values. The strongest available check
is analytic rather than a table lookup: for two systems, the unpenalised Bradley-Terry maximum
likelihood estimate has the closed form

    theta_a - theta_b = log(wins_a / wins_b)

so the fit can be checked against an exact number rather than against someone else's rounding.
The Davidson model is then checked to reduce to Bradley-Terry as the tie parameter goes to zero.

Network-free.
"""

from __future__ import annotations

import math

import pytest

from eval.judge.bt import (
    BradleyTerryError,
    Comparison,
    bootstrap_strengths,
    build_comparison,
    davidson_probabilities,
    fit_davidson,
    fit_with_intervals,
    position_bias_rate,
    win_graph_is_connected,
)


def duel(wins_a: int, wins_b: int, ties: int = 0, prefix: str = "q"):
    """A two-system comparison set with an exact win/loss/tie split."""
    comparisons = []
    n = 0
    for _ in range(wins_a):
        comparisons.append(Comparison(f"{prefix}{n}", "A", "B", "a")); n += 1
    for _ in range(wins_b):
        comparisons.append(Comparison(f"{prefix}{n}", "A", "B", "b")); n += 1
    for _ in range(ties):
        comparisons.append(Comparison(f"{prefix}{n}", "A", "B", "tie", order_stable=False)); n += 1
    return comparisons


# ---------------------------------------------------------------------------
# The golden check
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "wins_a,wins_b", [(30, 10), (20, 20), (12, 28), (45, 15), (25, 35)]
)
def test_two_system_fit_matches_the_closed_form(wins_a, wins_b):
    """theta_a - theta_b = log(wins_a / wins_b), exactly, with no penalty.

    For two players Bradley-Terry has an analytic MLE: the model-implied win probability equals
    the observed win rate. Checking against that is stronger than checking against a published
    table, because there is no rounding to hide a small error.
    """
    fit = fit_davidson(duel(wins_a, wins_b), prior_strength=0.0)
    observed = fit.strengths["A"] - fit.strengths["B"]
    assert observed == pytest.approx(math.log(wins_a / wins_b), abs=1e-4)


def test_the_fitted_probability_reproduces_the_observed_win_rate():
    """The other face of the same identity, and the one a reader would sanity-check."""
    fit = fit_davidson(duel(30, 10), prior_strength=0.0)
    assert fit.probability("A", "B")["a"] == pytest.approx(0.75, abs=1e-4)


def test_equal_records_give_equal_strengths():
    fit = fit_davidson(duel(20, 20), prior_strength=0.0)
    assert fit.strengths["A"] == pytest.approx(fit.strengths["B"], abs=1e-6)


def test_strengths_are_centred_on_zero():
    """Only differences are identified; centring makes two fits comparable."""
    fit = fit_davidson(duel(30, 10))
    assert sum(fit.strengths.values()) == pytest.approx(0.0, abs=1e-6)


def test_a_transitive_ranking_is_recovered():
    import random

    rng = random.Random(0)
    comparisons = []
    for i in range(40):
        for a, b, p in (("A", "B", 0.75), ("B", "C", 0.70), ("A", "C", 0.85)):
            comparisons.append(
                Comparison(f"q{i}", a, b, "a" if rng.random() < p else "b")
            )
    assert fit_davidson(comparisons).ranking() == ["A", "B", "C"]


# ---------------------------------------------------------------------------
# Davidson reduces to Bradley-Terry
# ---------------------------------------------------------------------------
def test_davidson_probabilities_reduce_to_bradley_terry_at_nu_zero():
    probabilities = davidson_probabilities(0.5, -0.5, nu=0.0)
    assert probabilities["tie"] == 0.0
    assert probabilities["a"] == pytest.approx(1 / (1 + math.exp(-1.0)))


def test_davidson_probabilities_sum_to_one():
    for nu in (0.0, 0.3, 1.0, 5.0):
        total = sum(davidson_probabilities(0.8, -0.2, nu).values())
        assert total == pytest.approx(1.0)


def test_a_larger_tie_parameter_makes_ties_more_likely():
    low = davidson_probabilities(0.5, -0.5, 0.2)["tie"]
    high = davidson_probabilities(0.5, -0.5, 2.0)["tie"]
    assert high > low


def test_a_negative_tie_parameter_is_rejected():
    with pytest.raises(BradleyTerryError, match="non-negative"):
        davidson_probabilities(0.0, 0.0, -1.0)


def test_a_set_with_no_ties_fits_plain_bradley_terry():
    fit = fit_davidson(duel(30, 10))
    assert fit.model == "bradley_terry"
    assert fit.tie_parameter == 0.0


def test_a_set_with_ties_fits_davidson():
    fit = fit_davidson(duel(20, 10, ties=10))
    assert fit.model == "davidson"
    assert fit.tie_parameter > 0


def test_the_tie_parameter_stays_finite_when_ties_dominate():
    """An unpenalised fit runs away here; the prior is what keeps it reportable."""
    fit = fit_davidson(duel(10, 0, ties=10))
    assert 0 < fit.tie_parameter < 100


# ---------------------------------------------------------------------------
# Ties are kept, not discarded
# ---------------------------------------------------------------------------
def test_dropping_ties_changes_the_estimate():
    """Which is the point: the discarded comparisons are the close calls."""
    comparisons = duel(20, 10, ties=20)
    with_ties = fit_davidson(comparisons, include_ties=True)
    without = fit_davidson(comparisons, include_ties=False)
    assert with_ties.n_comparisons != without.n_comparisons
    assert without.model == "bradley_terry"


def test_the_stable_only_fit_is_available_as_a_sensitivity_analysis():
    comparisons = duel(20, 10, ties=20)
    stable_only = [c for c in comparisons if c.order_stable]
    fit = fit_davidson(stable_only)
    assert fit.n_comparisons == 30


def test_a_set_of_only_ties_cannot_be_fitted_without_them():
    with pytest.raises(BradleyTerryError, match="every comparison was a tie"):
        fit_davidson(duel(0, 0, ties=10), include_ties=False)


def test_tie_rate_is_reported():
    assert fit_davidson(duel(20, 10, ties=20)).tie_rate == pytest.approx(20 / 50)


# ---------------------------------------------------------------------------
# Separation
# ---------------------------------------------------------------------------
def test_a_connected_win_graph_is_detected():
    import random

    rng = random.Random(1)
    comparisons = [
        Comparison(f"q{i}", "A", "B", "a" if rng.random() < 0.7 else "b") for i in range(30)
    ]
    assert win_graph_is_connected(comparisons) is True


def test_a_system_that_never_loses_breaks_connectivity():
    assert win_graph_is_connected(duel(20, 0)) is False


def test_a_tie_connects_both_directions():
    """A tie is evidence neither dominates, so it identifies the pair."""
    assert win_graph_is_connected(duel(0, 0, ties=5)) is True


def test_complete_separation_is_flagged_and_stays_finite():
    """The unpenalised estimate is infinite here; the fit must say so rather than pretend."""
    comparisons = []
    for i in range(12):
        comparisons += [
            Comparison(f"q{i}", "A", "B", "a"),
            Comparison(f"q{i}", "B", "C", "a"),
            Comparison(f"q{i}", "A", "C", "a"),
        ]
    fit = fit_davidson(comparisons)
    assert fit.separation_detected is True
    assert all(abs(strength) < 50 for strength in fit.strengths.values())
    assert fit.ranking() == ["A", "B", "C"]


def test_a_well_identified_fit_is_not_flagged():
    import random

    rng = random.Random(2)
    comparisons = [
        Comparison(f"q{i}", "A", "B", "a" if rng.random() < 0.7 else "b") for i in range(40)
    ]
    assert fit_davidson(comparisons).separation_detected is False


def test_the_prior_barely_moves_a_well_identified_fit():
    """Weak by design: it should only take over when the data cannot identify the parameter."""
    comparisons = duel(30, 10)
    unpenalised = fit_davidson(comparisons, prior_strength=0.0)
    penalised = fit_davidson(comparisons, prior_strength=0.5)
    difference = abs(
        (penalised.strengths["A"] - penalised.strengths["B"])
        - (unpenalised.strengths["A"] - unpenalised.strengths["B"])
    )
    assert difference < 0.15


def test_the_prior_strength_is_recorded():
    """A reader must be able to see the estimate is penalised."""
    assert fit_davidson(duel(30, 10), prior_strength=0.25).to_dict()["prior_strength"] == 0.25


def test_a_negative_prior_is_rejected():
    with pytest.raises(BradleyTerryError, match="non-negative"):
        fit_davidson(duel(10, 10), prior_strength=-1.0)


# ---------------------------------------------------------------------------
# Bootstrap intervals
# ---------------------------------------------------------------------------
def test_intervals_are_reproducible_by_seed():
    comparisons = duel(30, 10)
    first = bootstrap_strengths(comparisons, n_boot=200, seed=3)
    second = bootstrap_strengths(comparisons, n_boot=200, seed=3)
    assert first == second


def test_intervals_contain_the_point_estimate():
    import random

    rng = random.Random(4)
    comparisons = [
        Comparison(f"q{i}", "A", "B", "a" if rng.random() < 0.75 else "b") for i in range(40)
    ]
    fit = fit_with_intervals(comparisons, n_boot=300, seed=0)
    for system in fit.systems:
        low, high = fit.intervals[system]
        assert low <= fit.strengths[system] <= high


def test_more_data_gives_a_narrower_interval():
    import random

    def build(n, seed):
        rng = random.Random(seed)
        return [
            Comparison(f"q{i}", "A", "B", "a" if rng.random() < 0.75 else "b")
            for i in range(n)
        ]

    small = fit_with_intervals(build(15, 5), n_boot=300, seed=0)
    large = fit_with_intervals(build(150, 5), n_boot=300, seed=0)
    width = lambda f: f.intervals["A"][1] - f.intervals["A"][0]  # noqa: E731
    assert width(large) < width(small)


def test_the_bootstrap_resamples_questions_not_comparisons():
    """Comparisons on one question are not independent draws, and the interval must show it.

    Both sets below hold 24 comparisons with the same 16:8 outcome split. They differ only in how
    those comparisons are grouped:

    * 3 questions, each internally unanimous - the realistic case, since a question that is easy
      for one system tends to be easy on every comparison drawn from it.
    * 24 questions with one comparison each - fully independent.

    Resampling questions must give the first a wider interval, because it has three independent
    units rather than twenty-four. A bootstrap that resampled individual comparisons would report
    the same width for both and understate the uncertainty of the clustered design.

    Worth noting for anyone changing this: the effect exists only when clusters are internally
    correlated. Spread the same outcomes evenly across questions and the two designs agree, which
    is correct rather than a bug.
    """
    unanimous_clusters = (
        [Comparison("q0", "A", "B", "a") for _ in range(8)]
        + [Comparison("q1", "A", "B", "a") for _ in range(8)]
        + [Comparison("q2", "A", "B", "b") for _ in range(8)]
    )
    independent = (
        [Comparison(f"q{i}", "A", "B", "a") for i in range(16)]
        + [Comparison(f"q{i}", "A", "B", "b") for i in range(16, 24)]
    )

    clustered = bootstrap_strengths(unanimous_clusters, n_boot=400, seed=0)
    unclustered = bootstrap_strengths(independent, n_boot=400, seed=0)
    assert (clustered["A"][1] - clustered["A"][0]) > (
        unclustered["A"][1] - unclustered["A"][0]
    )


def test_separation_can_be_claimed_only_from_intervals():
    fit = fit_davidson(duel(30, 10))
    with pytest.raises(BradleyTerryError, match="refusing to claim separation"):
        fit.separates("A", "B")


def test_overlapping_intervals_do_not_separate():
    fit = fit_with_intervals(duel(21, 19), n_boot=300, seed=0)
    assert fit.separates("A", "B") is False


def test_a_bootstrap_needs_more_than_one_question():
    with pytest.raises(BradleyTerryError, match="at least two questions"):
        bootstrap_strengths([Comparison("q1", "A", "B", "a")], n_boot=50)


def test_an_empty_comparison_set_is_refused():
    with pytest.raises(BradleyTerryError, match="no comparisons"):
        fit_davidson([])


def test_a_single_system_cannot_be_ranked():
    with pytest.raises(BradleyTerryError):
        fit_davidson([Comparison("q1", "A", "A", "a")])


# ---------------------------------------------------------------------------
# Order and position bias
# ---------------------------------------------------------------------------
def test_agreeing_orders_give_a_stable_preference():
    comparison = build_comparison("q1", "A", "B", "a", "a")
    assert comparison.outcome == "a" and comparison.order_stable is True


def test_a_flipped_verdict_becomes_a_tie_and_is_kept():
    """Discarding it would select on a post-treatment variable."""
    comparison = build_comparison("q1", "A", "B", "a", "b")
    assert comparison.outcome == "tie" and comparison.order_stable is False


def test_build_comparison_rejects_a_position_instead_of_a_system():
    with pytest.raises(BradleyTerryError, match="must be 'a' or 'b'"):
        build_comparison("q1", "A", "B", "first", "a")


def test_position_bias_rate_counts_flips():
    comparisons = [
        build_comparison("q1", "A", "B", "a", "a"),
        build_comparison("q2", "A", "B", "a", "b"),
        build_comparison("q3", "A", "B", "b", "a"),
        build_comparison("q4", "A", "B", "b", "b"),
    ]
    assert position_bias_rate(comparisons) == 0.5


def test_position_bias_of_nothing_is_zero():
    assert position_bias_rate([]) == 0.0


def test_an_invalid_outcome_is_rejected():
    with pytest.raises(BradleyTerryError, match="outcome must be"):
        Comparison("q1", "A", "B", "maybe")


def test_the_fit_serialises_with_its_ranking_and_intervals():
    payload = fit_with_intervals(duel(30, 10), n_boot=200, seed=0).to_dict()
    assert payload["ranking"] == ["A", "B"]
    assert set(payload["intervals"]) == {"A", "B"}
    assert "separation_detected" in payload and "prior_strength" in payload
