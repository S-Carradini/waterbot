"""Tests for prompt rendering and the verdict schema (L2).

Two things here are methodological rather than cosmetic and are tested as such: the rationale
property must precede the score in the schema, because models emit properties in schema order;
and the failure-mode set in schemas.py must match rubric.yaml, because the rubric is what
annotators are trained against.

Network-free.
"""

from __future__ import annotations

import json
import typing

import pytest

from eval.judge.prompting import (
    PAIRWISE_V1,
    POINTWISE_V1,
    PromptError,
    format_citations,
    format_evidence,
    load_template,
    pairwise_json_schema,
    render_pairwise,
    render_pointwise,
    render_repair,
    verdict_json_schema,
)
from eval.judge.rubric import load_rubric
from eval.judge.schemas import FailureMode, Passage, Response


@pytest.fixture(scope="module")
def rubric():
    return load_rubric()


def a_passage(evidence_id=1, doc="cap_factsheet.pdf", text="The CAP is 336 miles long."):
    return Passage(
        evidence_id=evidence_id, canonical_doc_id=doc, chunk_id=f"c{evidence_id}",
        text=text, retrieval_rank=evidence_id - 1, retrieval_score=0.9,
    )


def a_response(**kw) -> Response:
    payload = {
        "item_id": "q001",
        "system": "waterbot",
        "persona": "blue",
        "question": "What is the Central Arizona Project?",
        "category": "general_policy",
        "answer": "The Central Arizona Project is a 336-mile aqueduct.",
        "passages": [a_passage(1), a_passage(2, "cap_two.pdf", "It serves Phoenix and Tucson.")],
        "citations": ["cap_factsheet.pdf"],
        "latency_ms": 100,
        "cost_usd": 0.004,
    }
    payload.update(kw)
    return Response(**payload)


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", [POINTWISE_V1, PAIRWISE_V1, "repair_v1"])
def test_every_template_splits_into_system_and_user(name):
    system, user, digest = load_template(name)
    assert system and user and len(digest) == 16


def test_an_unknown_template_lists_what_exists():
    with pytest.raises(PromptError, match="available"):
        load_template("nonexistent_v9")


def test_template_hash_is_stable():
    assert load_template(POINTWISE_V1)[2] == load_template(POINTWISE_V1)[2]


def test_different_templates_hash_differently():
    assert load_template(POINTWISE_V1)[2] != load_template(PAIRWISE_V1)[2]


def test_a_template_without_a_separator_is_rejected(tmp_path):
    (tmp_path / "broken_v1.txt").write_text("no separator here", encoding="utf-8")
    with pytest.raises(PromptError, match="separating system from user"):
        load_template("broken_v1", prompts_dir=str(tmp_path))


def test_an_unfilled_placeholder_raises(tmp_path):
    """A literal {{EVIDENCE}} reaching a judge would be answered anyway."""
    (tmp_path / "leaky_v1.txt").write_text(
        "[ROLE]\nx\n---USER---\n{{QUESTION}} and {{NEVER_FILLED}}", encoding="utf-8"
    )
    with pytest.raises(PromptError, match="never filled"):
        render_pointwise(a_response(), load_rubric(), ["grounding"], "leaky_v1", str(tmp_path))


# ---------------------------------------------------------------------------
# Pointwise rendering
# ---------------------------------------------------------------------------
def test_pointwise_prompt_carries_the_response_content(rubric):
    prompt = render_pointwise(a_response(), rubric)
    assert "Central Arizona Project" in prompt.user
    assert "336-mile aqueduct" in prompt.user
    assert "cap_factsheet.pdf" in prompt.user


def test_rubric_lives_in_the_system_block_so_it_can_be_cached(rubric):
    """The role plus rubric is byte-identical across items and is the largest block."""
    prompt = render_pointwise(a_response(), rubric)
    assert "grounding" in prompt.system
    assert "Central Arizona Project" not in prompt.system


def test_the_system_block_is_identical_across_items(rubric):
    """What makes provider prompt caching actually hit."""
    first = render_pointwise(a_response(item_id="q001"), rubric)
    second = render_pointwise(
        a_response(item_id="q002", question="Different?", answer="Different answer."), rubric
    )
    assert first.system == second.system


def test_dimensions_default_to_the_rubric_applicability_rules(rubric):
    """A negative question has nothing to ground, so only refusal is scored."""
    negative = a_response(category="out_of_scope_negative", citations=[], passages=[])
    prompt = render_pointwise(negative, rubric)
    assert "refusal_appropriateness" in prompt.user
    assert "grounding" not in prompt.user.split("Score these dimensions")[1].split("\n")[0]


def test_dimensions_can_be_overridden(rubric):
    prompt = render_pointwise(a_response(), rubric, ["grounding"])
    line = [l for l in prompt.user.splitlines() if "Score these dimensions" in l][0]
    assert line.strip().endswith("grounding")


def test_a_category_with_no_applicable_dimension_is_refused(rubric):
    with pytest.raises(PromptError, match="nothing to judge"):
        render_pointwise(a_response(), rubric, [])


def test_evidence_is_numbered_as_the_judge_will_cite_it():
    formatted = format_evidence([a_passage(1), a_passage(2, "b.pdf", "Second passage.")])
    assert formatted.index("[1]") < formatted.index("[2]")
    assert "b.pdf" in formatted


def test_evidence_numbering_does_not_depend_on_input_order():
    forward = format_evidence([a_passage(1), a_passage(2)])
    backward = format_evidence([a_passage(2), a_passage(1)])
    assert forward == backward


def test_no_passages_is_stated_rather_than_left_blank():
    """A blank evidence block reads as an omission; the judge should know it is empty."""
    assert "no passages" in format_evidence([])


def test_no_citations_is_stated_rather_than_left_blank():
    assert "no citations" in format_citations([])


def test_prompt_hash_changes_when_the_template_changes(tmp_path, rubric):
    original = (tmp_path / "v1.txt")
    original.write_text("[ROLE]\n{{RUBRIC}}{{FAILURE_MODES}}\n---USER---\n{{QUESTION}}"
                        "{{EVIDENCE}}{{RESPONSE}}{{CITATIONS}}{{DIMENSIONS}}", encoding="utf-8")
    first = render_pointwise(a_response(), rubric, ["grounding"], "v1", str(tmp_path))
    original.write_text("[ROLE]\nEDITED{{RUBRIC}}{{FAILURE_MODES}}\n---USER---\n{{QUESTION}}"
                        "{{EVIDENCE}}{{RESPONSE}}{{CITATIONS}}{{DIMENSIONS}}", encoding="utf-8")
    second = render_pointwise(a_response(), rubric, ["grounding"], "v1", str(tmp_path))
    assert first.prompt_hash != second.prompt_hash


def test_approximate_token_estimate_is_positive(rubric):
    assert render_pointwise(a_response(), rubric).approximate_tokens > 0


# ---------------------------------------------------------------------------
# Pairwise and repair
# ---------------------------------------------------------------------------
def test_pairwise_shows_both_answers(rubric):
    first = a_response(system="waterbot", answer="Answer from WaterBot.")
    second = a_response(system="realwater", answer="Answer from RealWater.")
    prompt = render_pairwise(first, second, rubric)
    assert "Answer from WaterBot." in prompt.user
    assert "Answer from RealWater." in prompt.user


def test_pairwise_states_that_order_carries_no_information(rubric):
    prompt = render_pairwise(a_response(), a_response(system="realwater"), rubric)
    assert "arbitrary" in prompt.system.lower() or "no information" in prompt.system.lower()


def test_pairwise_refuses_to_compare_different_items(rubric):
    with pytest.raises(PromptError, match="different items"):
        render_pairwise(a_response(item_id="q001"), a_response(item_id="q002"), rubric)


def test_repair_prompt_states_the_problems():
    prompt = render_repair("{bad json", ["grounding: cites evidence [9] but only [1] was shown"])
    assert "cites evidence [9]" in prompt.user
    assert "{bad json" in prompt.user


def test_repair_prompt_forbids_changing_the_judgement():
    """Otherwise repair becomes a second chance to score, not a correction."""
    prompt = render_repair("x", ["y"])
    assert "not change your scores" in prompt.user.lower() or \
           "do not change your scores" in prompt.user.lower()


def test_repair_handles_empty_previous_output():
    assert "(empty)" in render_repair("", ["timed out"]).user


# ---------------------------------------------------------------------------
# The schema
# ---------------------------------------------------------------------------
def test_rationale_precedes_score_in_the_schema():
    """Methodological, not cosmetic: models emit properties in schema order.

    Forcing the justification before the number measurably improves accuracy and makes every
    disagreement auditable. If this ordering is ever lost, the rationale becomes a post-hoc
    explanation of a number already chosen.
    """
    schema = verdict_json_schema(["grounding"], ["entity_substitution"])
    properties = list(schema["properties"]["dimensions"]["properties"]["grounding"]["properties"])
    assert properties.index("rationale") < properties.index("score")


def test_schema_requires_every_requested_dimension():
    schema = verdict_json_schema(["grounding", "correctness"], [])
    assert schema["properties"]["dimensions"]["required"] == ["grounding", "correctness"]


def test_schema_forbids_extra_properties():
    """A judge inventing a field would otherwise pass silently."""
    schema = verdict_json_schema(["grounding"], [])
    assert schema["additionalProperties"] is False
    assert schema["properties"]["dimensions"]["additionalProperties"] is False


def test_schema_allows_a_null_score_for_abstention():
    schema = verdict_json_schema(["grounding"], [])
    score = schema["properties"]["dimensions"]["properties"]["grounding"]["properties"]["score"]
    assert None in score["enum"]
    assert "null" in score["type"]


def test_schema_constrains_failure_modes_to_the_known_set():
    schema = verdict_json_schema(["grounding"], ["entity_substitution", "overrefusal"])
    assert schema["properties"]["failure_modes"]["items"]["enum"] == [
        "entity_substitution", "overrefusal"
    ]


def test_schema_needs_at_least_one_dimension():
    with pytest.raises(PromptError, match="at least one dimension"):
        verdict_json_schema([], [])


def test_schema_is_json_serialisable():
    """It is sent over the wire; a non-serialisable schema fails at the worst moment."""
    json.dumps(verdict_json_schema(["grounding"], ["overrefusal"]))
    json.dumps(pairwise_json_schema())


def test_pairwise_schema_offers_a_tie():
    """Order-unstable comparisons become ties rather than being discarded."""
    assert "tie" in pairwise_json_schema()["properties"]["winner"]["enum"]


# ---------------------------------------------------------------------------
# The rubric and the code must agree
# ---------------------------------------------------------------------------
def test_failure_modes_in_code_match_the_rubric(rubric):
    """rubric.yaml is what annotators are trained against; schemas.py is what the code accepts.

    If they drift, a judge reports a real failure mode that the schema rejects, or the schema
    accepts a mode no human was ever asked about. Either way the counts stop meaning anything.
    """
    in_code = set(typing.get_args(FailureMode))
    in_rubric = {mode.name for mode in rubric.failure_modes}
    assert in_code == in_rubric, (
        f"only in schemas.py: {sorted(in_code - in_rubric)}; "
        f"only in rubric.yaml: {sorted(in_rubric - in_code)}"
    )


def test_rubric_dimensions_cover_the_architecture_five(rubric):
    assert set(rubric.dimension_names) == {
        "grounding", "correctness", "refusal_appropriateness",
        "citation_validity", "temporal_integrity",
    }


def test_refusal_applies_to_every_category(rubric):
    """Scored across all questions, which is what makes over-refusal visible at all."""
    for category in ["general_policy", "numeric_extraction", "out_of_scope_negative",
                     "multi_hop", "entity_grounding", "temporal_realtime"]:
        assert "refusal_appropriateness" in rubric.applicable_names(category)
