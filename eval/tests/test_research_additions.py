"""Smoke tests for the changes from the August 2026 research review.

Deliberately thin. These prove the new code runs, produces sane numbers, and still fits the rest
of the system. The exhaustive suites for each piece come later, once the pilot has decided which
rubric arm survives and there are real labels to test against.

Network-free.
"""

from __future__ import annotations

import pytest

from eval.judge.checklist import (
    ArmResult,
    ChecklistError,
    compare_arms,
    load_checklist,
    render_checklist_for_prompt,
    score_checklist,
)
from eval.judge.panel import evaluate_tripwire, strip_evidence, withhold_evidence
from eval.judge.prompting import verdict_json_schema, verdict_schema_hash
from eval.judge.refusal import answer_length, length_effect, refusal_report
from eval.judge.schemas import (
    DimensionVerdict,
    MeasurementVersion,
    Passage,
    Response,
    Verdict,
)


def a_response(item_id="q001", category="general_policy", answer=None, passages=True):
    return Response(
        item_id=item_id,
        system="waterbot",
        persona="blue",
        question="What is the Central Arizona Project?",
        category=category,
        answer=answer or "The Central Arizona Project is a 336-mile aqueduct.",
        passages=[
            Passage(evidence_id=1, canonical_doc_id="cap.pdf", chunk_id="c1",
                    text="The CAP is 336 miles long.", retrieval_rank=0, retrieval_score=0.9)
        ] if passages else [],
        citations=["cap.pdf"] if passages else [],
        latency_ms=100,
        cost_usd=0.004,
    )


def a_verdict(response_id="q001::waterbot::blue", score=3, dimension="grounding", abstain=False):
    body = (
        DimensionVerdict(rationale="no evidence", insufficient_evidence=True, score=None)
        if abstain
        else DimensionVerdict(rationale="judged", score=score, evidence_ids=[1])
    )
    return Verdict(
        item_id=response_id.split("::")[0],
        response_id=response_id,
        judge_model_id="judge-a",
        sample_index=0,
        temperature=0.3,
        prompt_hash="p" * 16,
        rubric_hash="r" * 16,
        corpus_fingerprint="fp",
        dimensions={dimension: body},
    )


# ---------------------------------------------------------------------------
# Evidence-locking and the schema hash
# ---------------------------------------------------------------------------
def test_the_judge_commits_to_evidence_before_it_scores():
    """Models emit fields in schema order, so order is the mechanism, not decoration."""
    properties = list(
        verdict_json_schema(["grounding"], [])["properties"]["dimensions"]["properties"]["grounding"]["properties"]
    )
    assert properties.index("evidence_ids") < properties.index("rationale")
    assert properties.index("rationale") < properties.index("score")


def test_the_verdict_model_uses_the_same_order():
    fields = list(DimensionVerdict.model_fields)
    assert fields.index("evidence_ids") < fields.index("rationale") < fields.index("score")


def test_the_schema_shape_is_now_part_of_the_measurement_version():
    """The gap the reorder exposed: this field did not exist, so the change was invisible."""
    assert "verdict_schema_hash" in MeasurementVersion.model_fields


def test_a_different_verdict_shape_hashes_differently():
    assert verdict_schema_hash(["grounding"], []) != verdict_schema_hash(
        ["grounding", "correctness"], []
    )


def test_the_schema_hash_is_stable_for_the_same_shape():
    assert verdict_schema_hash(["grounding"], ["overrefusal"]) == verdict_schema_hash(
        ["grounding"], ["overrefusal"]
    )


def test_two_versions_differing_only_in_schema_shape_are_incomparable():
    def version(schema_hash):
        return MeasurementVersion(
            corpus_fingerprint="fp", rubric_hash="r" * 16, prompt_hash="p" * 16,
            judge_set=("judge-a",), aggregation_version="1.0.0", k=3, temperature=0.3,
            verdict_schema_hash=schema_hash,
        )

    from eval.judge.schemas import IncompatibleMeasurement

    with pytest.raises(IncompatibleMeasurement, match="verdict_schema_hash"):
        version("aaa").assert_comparable(version("bbb"))


# ---------------------------------------------------------------------------
# The no-context tripwire
# ---------------------------------------------------------------------------
def test_stripping_removes_the_evidence_but_keeps_the_answer():
    stripped = strip_evidence(a_response())
    assert stripped.passages == []
    assert stripped.citations == []
    assert stripped.answer == a_response().answer


def test_stripping_is_not_the_same_as_swapping():
    """Two different probes: wrong evidence versus no evidence."""
    donor = a_response(item_id="q050")
    swapped = withhold_evidence(a_response(), donor)
    stripped = strip_evidence(a_response())
    assert swapped.passages and not stripped.passages


def test_the_tripwire_passes_when_removing_evidence_costs_the_system():
    full = [a_verdict(score=4) for _ in range(5)]
    stripped = [a_verdict(score=1) for _ in range(5)]
    result = evaluate_tripwire(full, stripped)
    assert result.metric_survived is True
    assert "metric survives" in result.verdict


def test_the_tripwire_fires_when_scores_hold_up_without_evidence():
    """The failure it exists to catch: scoring confidently on nothing."""
    full = [a_verdict(score=4) for _ in range(5)]
    stripped = [a_verdict(score=4) for _ in range(5)]
    result = evaluate_tripwire(full, stripped)
    assert result.metric_survived is False
    assert "METRIC IS BROKEN" in result.verdict


def test_abstaining_without_evidence_is_correct_behaviour():
    full = [a_verdict(score=4) for _ in range(5)]
    stripped = [a_verdict(abstain=True) for _ in range(5)]
    assert evaluate_tripwire(full, stripped).metric_survived is True


# ---------------------------------------------------------------------------
# Refusal, both directions
# ---------------------------------------------------------------------------
def test_refusal_reports_both_directions():
    responses = [
        a_response("q001", "general_policy"),
        a_response("q002", "out_of_scope_negative"),
    ]
    verdicts = [
        a_verdict("q001::waterbot::blue", score=4, dimension="refusal_appropriateness"),
        a_verdict("q002::waterbot::blue", score=4, dimension="refusal_appropriateness"),
    ]
    report = refusal_report(verdicts, responses)
    assert report.abstention_recall == 1.0
    assert report.over_refusal_rate == 0.0


def test_a_bot_that_refuses_everything_is_caught():
    """The whole reason the pair is reported: this scores perfectly on the old metric."""
    responses = [a_response(f"q{i:03d}", "general_policy") for i in range(4)]
    responses.append(a_response("q999", "out_of_scope_negative"))
    verdicts = [
        a_verdict(f"q{i:03d}::waterbot::blue", score=1, dimension="refusal_appropriateness")
        for i in range(4)
    ]
    verdicts.append(
        a_verdict("q999::waterbot::blue", score=4, dimension="refusal_appropriateness")
    )
    report = refusal_report(verdicts, responses)
    assert report.abstention_recall == 1.0     # perfect on the old metric
    assert report.over_refusal_rate == 1.0     # and catastrophic on the new one
    assert "wrongly declines" in report.verdict
    assert "would have called this a success" in report.verdict


def test_refusal_needs_both_sides_to_report_a_trade_off():
    responses = [a_response("q001", "out_of_scope_negative")]
    verdicts = [a_verdict("q001::waterbot::blue", dimension="refusal_appropriateness")]
    assert refusal_report(verdicts, responses).over_refusal_rate is None


# ---------------------------------------------------------------------------
# Length
# ---------------------------------------------------------------------------
def test_length_is_counted_in_words():
    assert answer_length(a_response(answer="one two three")) == 3


def test_a_length_effect_is_detected_when_longer_scores_higher():
    responses, verdicts = [], []
    for i in range(10):
        rid = f"q{i:03d}"
        responses.append(a_response(rid, answer=" ".join(["word"] * (5 + i * 5))))
        verdicts.append(a_verdict(f"{rid}::waterbot::blue", score=min(4, 1 + i // 3)))
    effect = length_effect(verdicts, responses)
    assert effect.correlation > 0.5
    assert "length effect" in effect.verdict


def test_the_length_report_flags_being_underpowered():
    responses, verdicts = [], []
    for i in range(10):
        rid = f"q{i:03d}"
        responses.append(a_response(rid, answer=" ".join(["word"] * (5 + i))))
        verdicts.append(a_verdict(f"{rid}::waterbot::blue", score=3))
    assert length_effect(verdicts, responses).underpowered is True


# ---------------------------------------------------------------------------
# The checklist rubric
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def checklist():
    return load_checklist()


def test_the_checklist_rubric_loads(checklist):
    assert checklist.dimension_names == [
        "grounding", "correctness", "refusal_appropriateness",
        "citation_validity", "temporal_integrity",
    ]
    assert checklist.total_items() > 15


def test_the_checklist_is_marked_unpiloted(checklist):
    """Same guard as the anchored rubric: no arm is trusted before the pilot."""
    assert checklist.is_piloted is False


def test_refusal_applies_to_every_category(checklist):
    for category in ("general_policy", "out_of_scope_negative", "numeric_extraction"):
        assert "refusal_appropriateness" in checklist.applicable_names(category)


def test_grounding_does_not_apply_to_negatives(checklist):
    assert "grounding" not in checklist.applicable_names("out_of_scope_negative")


def test_ticking_every_box_earns_full_weight(checklist):
    dimension = checklist.get("grounding")
    score = score_checklist(checklist, "grounding", [i.id for i in dimension.items])
    assert score.fraction == 1.0
    assert score.rolled_up(checklist.bands) == 4


def test_ticking_nothing_earns_the_floor(checklist):
    score = score_checklist(checklist, "grounding", [])
    assert score.fraction == 0.0
    assert score.rolled_up(checklist.bands) == 1


def test_the_rollup_is_continuous_before_it_is_banded(checklist):
    """Arm 3's whole point: a weighted fraction has resolution an integer median does not."""
    dimension = checklist.get("grounding")
    fractions = {
        score_checklist(checklist, "grounding", [i.id for i in dimension.items[:n]]).fraction
        for n in range(len(dimension.items) + 1)
    }
    assert len(fractions) == len(dimension.items) + 1


def test_a_tick_from_another_rubric_version_is_refused(checklist):
    with pytest.raises(ChecklistError, match="different rubric version"):
        score_checklist(checklist, "grounding", ["no_such_item"])


def test_changing_a_weight_changes_the_rubric_hash(checklist):
    """A weight change changes what a score means, so it must change the identity."""
    import copy

    from eval.judge.checklist import ChecklistItem, ChecklistRubric

    heavier = copy.deepcopy(checklist.dimensions[0].items[0])
    modified = ChecklistRubric(
        version=checklist.version,
        status=checklist.status,
        dimensions=(
            checklist.dimensions[0].__class__(
                name=checklist.dimensions[0].name,
                question=checklist.dimensions[0].question,
                applies_to=checklist.dimensions[0].applies_to,
                items=(ChecklistItem(heavier.id, heavier.text, heavier.weight + 1),)
                + checklist.dimensions[0].items[1:],
            ),
        ) + checklist.dimensions[1:],
        bands=checklist.bands,
    )
    assert modified.rubric_hash != checklist.rubric_hash


def test_the_checklist_renders_for_a_prompt(checklist):
    rendered = render_checklist_for_prompt(checklist, ["grounding"])
    assert "[ ]" in rendered and "grounding" in rendered


# ---------------------------------------------------------------------------
# Choosing an arm
# ---------------------------------------------------------------------------
def test_the_arm_with_the_best_agreement_wins():
    result = compare_arms([
        ArmResult("anchored", agreement=0.55, mean_seconds_per_item=90, n_items=20),
        ArmResult("checklist", agreement=0.74, mean_seconds_per_item=80, n_items=20),
        ArmResult("rolled_up", agreement=0.72, mean_seconds_per_item=80, n_items=20),
    ])
    assert result["winner"] == "checklist"


def test_a_near_tie_is_broken_on_annotator_time():
    """Annotator hours are the binding constraint; 2% more agreement at twice the cost is a loss."""
    result = compare_arms([
        ArmResult("anchored", agreement=0.72, mean_seconds_per_item=45, n_items=20),
        ArmResult("checklist", agreement=0.74, mean_seconds_per_item=180, n_items=20),
    ])
    assert result["winner"] == "anchored"
    assert "faster per item" in result["reason"]


def test_every_arm_is_reported_not_just_the_winner():
    """The losing arms are a methods result, not waste."""
    result = compare_arms([
        ArmResult("anchored", agreement=0.55, mean_seconds_per_item=90, n_items=20),
        ArmResult("checklist", agreement=0.74, mean_seconds_per_item=80, n_items=20),
    ])
    assert len(result["arms"]) == 2
