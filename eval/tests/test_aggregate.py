"""Tests for L3 aggregation.

The properties that matter: abstentions are counted before they are dropped, disagreement is
routed rather than averaged away, and the per-item interval is clustered by judge because k
samples from one judge are not k independent opinions.

Network-free.
"""

from __future__ import annotations

import math

import pytest

from eval.judge.aggregate import (
    AGGREGATION_VERSION,
    Vote,
    aggregate_all,
    aggregate_dimension,
    aggregate_response,
    build_reliability_matrix,
    iqr,
    judge_clustered_interval,
    median,
    modal_score,
    normalised_entropy,
    summarise_aggregates,
    votes_for,
)
from eval.judge.schemas import DimensionVerdict, Verdict


def a_verdict(judge="judge-a", sample=0, item="q001", **dimensions) -> Verdict:
    if not dimensions:
        dimensions = {"grounding": 3}
    built = {}
    for name, score in dimensions.items():
        if score is None:
            built[name] = DimensionVerdict(
                rationale="no evidence", insufficient_evidence=True, score=None
            )
        else:
            built[name] = DimensionVerdict(rationale="judged", score=score)
    return Verdict(
        item_id=item,
        response_id=f"{item}::waterbot::blue",
        judge_model_id=judge,
        sample_index=sample,
        temperature=0.3,
        prompt_hash="p" * 16,
        rubric_hash="r" * 16,
        corpus_fingerprint="fp",
        dimensions=built,
    )


def votes(*scores, judge="judge-a"):
    return [Vote(judge, i, s) for i, s in enumerate(scores)]


# ---------------------------------------------------------------------------
# Descriptive statistics
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "values", [[1, 2, 3, 4], [3, 3, 3], [1, 4], [2, 2, 3, 4, 4], [1], [1, 1, 2, 4, 4, 4]]
)
def test_median_and_iqr_match_numpy(values):
    numpy = pytest.importorskip("numpy")
    assert median(values) == pytest.approx(float(numpy.median(values)))
    expected = float(numpy.percentile(values, 75) - numpy.percentile(values, 25))
    assert iqr(values) == pytest.approx(expected)


def test_median_of_nothing_raises():
    with pytest.raises(ValueError, match="quantile of nothing"):
        median([])


def test_entropy_is_zero_when_the_panel_is_unanimous():
    assert normalised_entropy([3, 3, 3, 3, 3]) == 0.0


def test_entropy_is_one_when_votes_are_spread_across_every_level():
    assert normalised_entropy([1, 2, 3, 4]) == pytest.approx(1.0)


def test_entropy_is_normalised_against_the_scale_not_the_votes_used():
    """An item where judges used only two levels must not look maximally uncertain."""
    assert normalised_entropy([1, 2]) == pytest.approx(math.log(2) / math.log(4))


def test_entropy_of_nothing_is_zero():
    assert normalised_entropy([]) == 0.0


def test_entropy_needs_a_real_scale():
    with pytest.raises(ValueError, match="at least two levels"):
        normalised_entropy([1, 2], levels=1)


# ---------------------------------------------------------------------------
# Vote extraction
# ---------------------------------------------------------------------------
def test_votes_are_pulled_per_dimension():
    verdicts = [a_verdict(grounding=3, correctness=2)]
    assert [v.score for v in votes_for(verdicts, "grounding")] == [3]
    assert [v.score for v in votes_for(verdicts, "correctness")] == [2]


def test_a_dimension_a_judge_never_scored_yields_no_vote():
    assert votes_for([a_verdict(grounding=3)], "temporal_integrity") == []


def test_abstentions_survive_extraction_rather_than_being_filtered():
    """Dropping first and counting later is how an abstention rate silently becomes zero."""
    extracted = votes_for([a_verdict(grounding=None)], "grounding")
    assert len(extracted) == 1
    assert extracted[0].abstained is True
    assert extracted[0].score is None


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------
def test_a_confident_panel_produces_a_clean_aggregate():
    aggregate = aggregate_dimension("r1", "grounding", votes(3, 3, 3, 3), n_boot=200)
    assert aggregate.median == 3.0
    assert aggregate.mean == 3.0
    assert aggregate.iqr == 0.0
    assert aggregate.entropy == 0.0
    assert aggregate.escalate is False


def test_median_and_mean_are_both_recorded():
    """The median is reported; the mean feeds calibration (spec 0.5)."""
    aggregate = aggregate_dimension("r1", "grounding", votes(1, 3, 3, 4), n_boot=200)
    assert aggregate.median == 3.0
    assert aggregate.mean == pytest.approx(2.75)


def test_a_split_panel_escalates_rather_than_averaging():
    """The average of a split panel is a number no judge gave."""
    aggregate = aggregate_dimension("r1", "grounding", votes(1, 1, 4, 4), n_boot=200)
    assert aggregate.escalate is True
    assert aggregate.escalation_reason == "panel_disagreement"


def test_escalation_thresholds_are_configurable():
    split = votes(1, 1, 4, 4)
    assert aggregate_dimension(
        "r1", "grounding", split, iqr_threshold=99, entropy_threshold=99, n_boot=200
    ).escalate is False


def test_mostly_abstained_escalates_without_a_score():
    """Two surviving votes out of fifteen is two opinions, not a panel consensus."""
    mixed = votes(3, None, None, None, None, None)
    aggregate = aggregate_dimension("r1", "grounding", mixed, expected_votes=6, n_boot=200)
    assert aggregate.escalate is True
    assert aggregate.escalation_reason == "mostly_abstained"
    assert aggregate.median is None
    assert aggregate.n_abstained == 5


def test_a_fully_abstained_dimension_escalates():
    aggregate = aggregate_dimension("r1", "grounding", votes(None, None), n_boot=200)
    assert aggregate.escalation_reason == "mostly_abstained"
    assert aggregate.n_votes == 0


def test_abstentions_are_counted_but_excluded_from_the_centre():
    mixed = votes(4, 4, 4, None)
    aggregate = aggregate_dimension("r1", "grounding", mixed, expected_votes=4, n_boot=200)
    assert aggregate.n_votes == 3
    assert aggregate.n_abstained == 1
    assert aggregate.median == 4.0  # the abstention is not a zero


def test_just_enough_votes_still_scores():
    """Exactly half the expected votes is the boundary, and it must score rather than escalate."""
    aggregate = aggregate_dimension(
        "r1", "grounding", votes(3, 3, None, None), expected_votes=4, n_boot=200
    )
    assert aggregate.escalation_reason != "mostly_abstained"


# ---------------------------------------------------------------------------
# The clustered interval
# ---------------------------------------------------------------------------
def test_one_judge_gets_no_interval():
    """With a single cluster there is nothing to resample and no honest interval."""
    assert judge_clustered_interval(votes(3, 3, 4, 4)) == (None, None)


def test_the_interval_is_clustered_by_judge_not_by_vote():
    """Five samples from one judge are not five independent opinions.

    Two judges disagreeing completely must produce a wide interval, because resampling judges
    can draw two of the same. Resampling individual votes would average them and report a
    misleadingly tight interval.
    """
    split = [Vote("judge-a", i, 1) for i in range(5)] + [Vote("judge-b", i, 4) for i in range(5)]
    low, high = judge_clustered_interval(split, n_boot=2000, seed=0)
    assert low == pytest.approx(1.0)
    assert high == pytest.approx(4.0)


def test_agreeing_judges_give_a_tight_interval():
    agreeing = [Vote("judge-a", i, 3) for i in range(5)] + [
        Vote("judge-b", i, 3) for i in range(5)
    ]
    low, high = judge_clustered_interval(agreeing, n_boot=500, seed=0)
    assert low == pytest.approx(3.0) and high == pytest.approx(3.0)


def test_the_interval_is_reproducible_by_seed():
    mixed = [Vote("judge-a", i, 2) for i in range(3)] + [Vote("judge-b", i, 4) for i in range(3)]
    assert judge_clustered_interval(mixed, n_boot=300, seed=7) == judge_clustered_interval(
        mixed, n_boot=300, seed=7
    )


def test_the_aggregate_interval_contains_the_mean():
    two_judges = [Vote("judge-a", i, 2) for i in range(3)] + [
        Vote("judge-b", i, 4) for i in range(3)
    ]
    aggregate = aggregate_dimension("r1", "grounding", two_judges, n_boot=500)
    assert aggregate.ci_low <= aggregate.mean <= aggregate.ci_high


# ---------------------------------------------------------------------------
# Whole responses and runs
# ---------------------------------------------------------------------------
def test_a_response_aggregates_every_dimension_scored():
    verdicts = [a_verdict(judge=f"j{i}", grounding=3, correctness=4) for i in range(3)]
    aggregates = aggregate_response("q001::waterbot::blue", verdicts, n_boot=200)
    assert sorted(a.dimension for a in aggregates) == ["correctness", "grounding"]


def test_a_run_aggregates_every_response():
    verdicts = [
        a_verdict(judge="j1", item="q001"), a_verdict(judge="j2", item="q001"),
        a_verdict(judge="j1", item="q002"), a_verdict(judge="j2", item="q002"),
    ]
    aggregates = aggregate_all(verdicts, n_boot=200)
    assert {a.response_id for a in aggregates} == {
        "q001::waterbot::blue", "q002::waterbot::blue"
    }


def test_the_summary_reports_escalation_rates():
    clean = aggregate_dimension("r1", "grounding", votes(3, 3, 3), n_boot=100)
    split = aggregate_dimension("r2", "grounding", votes(1, 1, 4, 4), n_boot=100)
    report = summarise_aggregates([clean, split])
    assert report.n_aggregates == 2
    assert report.n_escalated == 1
    assert report.escalation_rate == 0.5
    assert report.aggregation_version == AGGREGATION_VERSION


def test_the_summary_flags_thresholds_that_escalate_everything():
    """Everything escalating means tau is too tight; nothing escalating, too loose."""
    all_split = [
        aggregate_dimension(f"r{i}", "grounding", votes(1, 1, 4, 4), n_boot=100)
        for i in range(4)
    ]
    assert summarise_aggregates(all_split).thresholds_look_sane is False


def test_the_summary_flags_a_panel_that_never_disagrees():
    unanimous = [
        aggregate_dimension(f"r{i}", "grounding", votes(3, 3, 3), n_boot=100) for i in range(4)
    ]
    assert summarise_aggregates(unanimous).thresholds_look_sane is False


# ---------------------------------------------------------------------------
# The reliability matrix alpha needs
# ---------------------------------------------------------------------------
def test_modal_score_picks_the_most_common():
    assert modal_score([3, 3, 4]) == 3


def test_modal_score_breaks_ties_downward():
    """The conservative direction: never invent quality no sample claimed."""
    assert modal_score([2, 2, 4, 4]) == 2


def test_modal_score_of_nothing_is_none():
    assert modal_score([]) is None


def test_the_matrix_is_judges_by_items():
    verdicts = [
        a_verdict(judge="judge-a", item="q001", grounding=3),
        a_verdict(judge="judge-b", item="q001", grounding=4),
        a_verdict(judge="judge-a", item="q002", grounding=2),
        a_verdict(judge="judge-b", item="q002", grounding=2),
    ]
    matrix = build_reliability_matrix(verdicts, "grounding")
    assert matrix.shape == (2, 2)
    assert matrix.judges == ["judge-a", "judge-b"]
    assert matrix.items == ["q001", "q002"]
    assert matrix.rows == [[3, 2], [4, 2]]


def test_k_samples_collapse_to_one_modal_score_per_cell():
    """Alpha treats each coder as giving one judgement per unit."""
    verdicts = [a_verdict(judge="judge-a", sample=i, grounding=3) for i in range(5)]
    verdicts += [a_verdict(judge="judge-b", sample=i, grounding=4) for i in range(5)]
    matrix = build_reliability_matrix(verdicts, "grounding")
    assert matrix.shape == (2, 1)
    assert matrix.rows == [[3], [4]]


def test_abstentions_stay_missing_and_are_never_imputed():
    """Alpha handles missing data natively; that is why the architecture chose it."""
    verdicts = [
        a_verdict(judge="judge-a", item="q001", grounding=3),
        a_verdict(judge="judge-b", item="q001", grounding=None),
    ]
    matrix = build_reliability_matrix(verdicts, "grounding")
    assert matrix.rows == [[3], [None]]
    assert matrix.missing == 1
    assert matrix.missing_rate == pytest.approx(0.5)


def test_a_judge_that_never_saw_an_item_is_missing_not_zero():
    verdicts = [
        a_verdict(judge="judge-a", item="q001", grounding=3),
        a_verdict(judge="judge-b", item="q002", grounding=4),
    ]
    matrix = build_reliability_matrix(verdicts, "grounding")
    assert matrix.shape == (2, 2)
    assert matrix.missing == 2


def test_a_column_can_be_read_back_by_item():
    verdicts = [
        a_verdict(judge="judge-a", item="q001", grounding=3),
        a_verdict(judge="judge-b", item="q001", grounding=4),
    ]
    assert build_reliability_matrix(verdicts, "grounding").column("q001") == [3, 4]


def test_the_matrix_serialises():
    verdicts = [a_verdict(judge="judge-a", grounding=3), a_verdict(judge="judge-b", grounding=4)]
    payload = build_reliability_matrix(verdicts, "grounding").to_dict()
    assert payload["shape"] == [2, 1] and payload["dimension"] == "grounding"
