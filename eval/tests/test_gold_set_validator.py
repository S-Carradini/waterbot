"""Tests for the gold set validator.

A validator that passes bad data is worse than no validator, because it converts "we have not
checked" into "we checked and it is fine". Every rule in docs/GOLD_SET_SPEC.md section 7 gets a
test that it fires, and a test that it does not fire on good data.
"""

from __future__ import annotations

import json

import pytest

from eval.validate_gold_set import CATEGORY_TARGETS, validate


def good_question(qid: str = "q001", category: str = "general_policy", **overrides) -> dict:
    """A question that must pass every rule. Overrides break it on purpose."""
    question = {
        "id": qid,
        "question": "What is the Central Arizona Project and what does it deliver?",
        "category": category,
        "gold_answer": "The Central Arizona Project is a 336-mile aqueduct delivering Colorado River water.",
        "gold_source_ids": ["CAP-FactSheet-January2024.pdf"],
        "notes": "baseline institutional knowledge",
        "gold_answer_evidence": [
            {
                "source_id": "CAP-FactSheet-January2024.pdf",
                "quote": "The Central Arizona Project is a 336-mile long system.",
                "locator": "p. 1",
            }
        ],
        "verification": {
            "status": "verified",
            "verified_by": "ab",
            "verified_on": "2026-09-01",
            "method": "read_source",
            "second_reviewer": "cd",
            "disagreement": None,
        },
    }
    if category in ("numeric_extraction", "temporal_realtime"):
        question["gold_passage_keywords"] = ["336-mile", "Colorado River"]
    question.update(overrides)
    return question


def good_negative(qid: str = "q049", **overrides) -> dict:
    question = {
        "id": qid,
        "question": "Who will win the next presidential election?",
        "category": "out_of_scope_negative",
        "gold_answer": "I focus on Arizona water topics.",
        "gold_source_ids": [],
        "notes": "out of domain",
        "refusal_type": "out_of_domain",
        "acceptable_redirect": True,
    }
    question.update(overrides)
    return question


def run(questions, meta=None, strict=False, tmp_path=None):
    payload = {"_meta": meta or {}, "questions": questions}
    path = tmp_path / "bench.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return validate(str(path), strict=strict)


def rules(findings) -> set:
    return set(findings.errors)


# ---------------------------------------------------------------------------
# Good data passes
# ---------------------------------------------------------------------------
def test_a_correct_question_produces_no_errors(tmp_path):
    findings = run([good_question()], tmp_path=tmp_path)
    assert findings.errors == {}


def test_a_correct_negative_produces_no_errors(tmp_path):
    findings = run([good_negative()], tmp_path=tmp_path)
    assert findings.errors == {}


def test_negatives_do_not_need_evidence_or_verification(tmp_path):
    """Refusal questions have nothing to ground against, by construction."""
    findings = run([good_negative()], tmp_path=tmp_path)
    assert "missing gold_answer_evidence" not in findings.errors
    assert "missing verification record" not in findings.errors


def test_every_category_has_a_target(tmp_path):
    from eval.validate_gold_set import CATEGORIES

    assert set(CATEGORY_TARGETS) == set(CATEGORIES)


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bad_id", ["1", "question-1", "Q001", "", None])
def test_malformed_id_is_an_error(tmp_path, bad_id):
    findings = run([good_question(qid=bad_id)], tmp_path=tmp_path)
    assert "malformed id" in rules(findings)


def test_duplicate_id_is_an_error(tmp_path):
    findings = run([good_question("q001"), good_question("q001")], tmp_path=tmp_path)
    assert "duplicate id" in rules(findings)


def test_unknown_category_is_an_error(tmp_path):
    findings = run([good_question(category="water_vibes")], tmp_path=tmp_path)
    assert "unknown category" in rules(findings)


# ---------------------------------------------------------------------------
# Evidence: the rules that make a gold answer "verified"
# ---------------------------------------------------------------------------
def test_missing_evidence_is_an_error(tmp_path):
    q = good_question()
    del q["gold_answer_evidence"]
    assert "missing gold_answer_evidence" in rules(run([q], tmp_path=tmp_path))


def test_empty_evidence_list_is_an_error(tmp_path):
    findings = run([good_question(gold_answer_evidence=[])], tmp_path=tmp_path)
    assert "empty gold_answer_evidence" in rules(findings)


def test_evidence_citing_an_unlisted_source_is_an_error(tmp_path):
    """The quote must come from a document the question claims as a gold source."""
    q = good_question(
        gold_answer_evidence=[
            {"source_id": "SomeOtherDoc.pdf", "quote": "x" * 50, "locator": "p. 2"}
        ]
    )
    findings = run([q], tmp_path=tmp_path)
    assert "evidence cites a source not in gold_source_ids" in rules(findings)


@pytest.mark.parametrize("quote,rule", [("short", "quote too short"), ("x" * 501, "quote too long")])
def test_quote_length_bounds(tmp_path, quote, rule):
    q = good_question(
        gold_answer_evidence=[
            {"source_id": "CAP-FactSheet-January2024.pdf", "quote": quote, "locator": "p. 1"}
        ]
    )
    assert rule in rules(run([q], tmp_path=tmp_path))


def test_evidence_without_a_locator_is_an_error(tmp_path):
    """A reviewer must be able to find the quote in under a minute."""
    q = good_question(
        gold_answer_evidence=[
            {"source_id": "CAP-FactSheet-January2024.pdf", "quote": "x" * 50}
        ]
    )
    assert "evidence missing locator" in rules(run([q], tmp_path=tmp_path))


def test_multi_hop_needs_two_distinct_sources(tmp_path):
    """Otherwise it is a single-passage question wearing a multi_hop label."""
    q = good_question(
        category="multi_hop",
        gold_source_ids=["A.pdf"],
        gold_answer_evidence=[
            {"source_id": "A.pdf", "quote": "x" * 50, "locator": "p. 1"},
            {"source_id": "A.pdf", "quote": "y" * 50, "locator": "p. 9"},
        ],
    )
    assert "multi_hop with fewer than two distinct sources" in rules(run([q], tmp_path=tmp_path))


def test_multi_hop_with_two_sources_passes(tmp_path):
    q = good_question(
        category="multi_hop",
        gold_source_ids=["A.pdf", "B.pdf"],
        gold_answer_evidence=[
            {"source_id": "A.pdf", "quote": "x" * 50, "locator": "p. 1"},
            {"source_id": "B.pdf", "quote": "y" * 50, "locator": "p. 9"},
        ],
    )
    assert run([q], tmp_path=tmp_path).errors == {}


# ---------------------------------------------------------------------------
# Verification: the two-person rule
# ---------------------------------------------------------------------------
def test_verified_without_a_second_reviewer_is_an_error(tmp_path):
    """The whole point of the review protocol."""
    q = good_question()
    q["verification"]["second_reviewer"] = None
    assert "verified without a second_reviewer" in rules(run([q], tmp_path=tmp_path))


def test_verified_without_verified_by_is_an_error(tmp_path):
    q = good_question()
    q["verification"]["verified_by"] = ""
    assert "verified without verified_by" in rules(run([q], tmp_path=tmp_path))


@pytest.mark.parametrize("date", ["01-09-2026", "2026/09/01", "soon", None])
def test_verified_needs_an_iso_date(tmp_path, date):
    q = good_question()
    q["verification"]["verified_on"] = date
    assert "verified without a YYYY-MM-DD verified_on" in rules(run([q], tmp_path=tmp_path))


def test_pending_verification_does_not_require_a_second_reviewer(tmp_path):
    """Work in progress must be representable, or authors will fake the record."""
    q = good_question()
    q["verification"] = {"status": "pending", "method": "read_source"}
    findings = run([q], tmp_path=tmp_path)
    assert "verified without a second_reviewer" not in findings.errors


def test_unknown_verification_status_is_an_error(tmp_path):
    q = good_question()
    q["verification"]["status"] = "probably_fine"
    assert "unknown verification status" in rules(run([q], tmp_path=tmp_path))


# ---------------------------------------------------------------------------
# Negatives
# ---------------------------------------------------------------------------
def test_negative_without_refusal_type_is_an_error(tmp_path):
    q = good_negative()
    del q["refusal_type"]
    assert "negative missing refusal_type" in rules(run([q], tmp_path=tmp_path))


def test_unknown_refusal_type_is_an_error(tmp_path):
    findings = run([good_negative(refusal_type="vibes")], tmp_path=tmp_path)
    assert "unknown refusal_type" in rules(findings)


def test_negative_without_acceptable_redirect_is_an_error(tmp_path):
    q = good_negative()
    del q["acceptable_redirect"]
    assert "negative missing acceptable_redirect" in rules(run([q], tmp_path=tmp_path))


def test_non_negative_with_no_sources_is_an_error(tmp_path):
    findings = run([good_question(gold_source_ids=[])], tmp_path=tmp_path)
    assert "empty gold_source_ids" in rules(findings)


# ---------------------------------------------------------------------------
# Category-specific
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("category", ["numeric_extraction", "temporal_realtime"])
def test_keywords_required_for_retrieval_scored_categories(tmp_path, category):
    q = good_question(category=category)
    del q["gold_passage_keywords"]
    assert "missing gold_passage_keywords" in rules(run([q], tmp_path=tmp_path))


def test_numeric_answer_without_a_digit_warns(tmp_path):
    q = good_question(category="numeric_extraction", gold_answer="Quite a lot of water.")
    findings = run([q], tmp_path=tmp_path)
    assert "numeric question with no digit in gold_answer" in findings.warnings


def test_quarantine_without_a_reason_is_an_error(tmp_path):
    findings = run([good_question(excluded_from_scoring=True)], tmp_path=tmp_path)
    assert "quarantined without reason" in rules(findings)


# ---------------------------------------------------------------------------
# Category counts
# ---------------------------------------------------------------------------
def test_category_shortfall_is_a_warning_by_default(tmp_path):
    findings = run([good_question()], tmp_path=tmp_path)
    assert "category below minimum" in findings.warnings
    assert "category below minimum" not in findings.errors


def test_category_shortfall_is_an_error_under_strict(tmp_path):
    findings = run([good_question()], strict=True, tmp_path=tmp_path)
    assert "category below minimum" in findings.errors


def test_stale_total_in_meta_warns(tmp_path):
    findings = run([good_question()], meta={"total_questions": 999}, tmp_path=tmp_path)
    assert "_meta.total_questions is stale" in findings.warnings


def test_missing_authoring_fingerprint_warns(tmp_path):
    """Records which corpus state the answers were checked against."""
    findings = run([good_question()], tmp_path=tmp_path)
    assert "_meta.corpus_fingerprint_at_authoring missing" in findings.warnings


# ---------------------------------------------------------------------------
# The validator must survive a half-finished file
# ---------------------------------------------------------------------------
def test_reports_all_problems_in_one_pass(tmp_path):
    """Authors need a checklist, not one error at a time."""
    broken = good_question("q001")
    del broken["gold_answer_evidence"]
    del broken["verification"]
    findings = run([broken, good_question("q002", gold_source_ids=[])], tmp_path=tmp_path)
    assert {"missing gold_answer_evidence", "missing verification record", "empty gold_source_ids"} <= rules(findings)


def test_a_non_object_question_does_not_crash_the_run(tmp_path):
    findings = run([good_question(), "not a question"], tmp_path=tmp_path)
    assert "malformed question" in rules(findings)


def test_current_repo_dataset_parses_without_crashing():
    """The real file must always be analysable, however incomplete it is."""
    from eval.validate_gold_set import DEFAULT_DATASET

    findings = validate(DEFAULT_DATASET)
    # It has known gaps today; the contract is that we can enumerate them.
    assert findings.error_count > 0
    assert "missing gold_answer_evidence" in findings.errors
