"""Tests for the judge data contracts.

These models are load-bearing for every layer, so the tests are deliberately paranoid. Three
things are checked for each model: that valid data round-trips through JSON unchanged, that the
guards fire on the specific mistakes they exist to prevent, and that extra fields are rejected
rather than silently dropped.

Network-free, per invariant 3.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from eval.judge.schemas import (
    SCHEMA_VERSION,
    CalibrationMap,
    CorpusIdentity,
    DimensionAggregate,
    DimensionVerdict,
    DuplicateProof,
    HumanLabel,
    IncompatibleMeasurement,
    MeasurementVersion,
    Passage,
    PairwiseVerdict,
    Response,
    RunManifest,
    Verdict,
    stable_hash,
)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------
def a_passage(evidence_id: int = 1, **kw) -> Passage:
    return Passage(
        **{
            "evidence_id": evidence_id,
            "canonical_doc_id": "cap_factsheet",
            "chunk_id": f"chunk_{evidence_id}",
            "text": "The Central Arizona Project is 336 miles long.",
            "retrieval_rank": evidence_id - 1,
            "retrieval_score": 0.8,
            **kw,
        }
    )


def a_response(**kw) -> Response:
    return Response(
        **{
            "item_id": "q001",
            "system": "waterbot",
            "persona": "blue",
            "question": "What is CAP?",
            "category": "general_policy",
            "answer": "CAP is a 336-mile aqueduct.",
            "passages": [a_passage(1), a_passage(2)],
            "citations": ["cap_factsheet"],
            "latency_ms": 1200,
            "cost_usd": 0.004,
            **kw,
        }
    )


def a_dimension(**kw) -> DimensionVerdict:
    return DimensionVerdict(
        **{
            "rationale": "Every claim traces to passage 1.",
            "quoted_span": "336-mile aqueduct",
            "evidence_ids": [1],
            "insufficient_evidence": False,
            "score": 4,
            **kw,
        }
    )


def a_verdict(**kw) -> Verdict:
    return Verdict(
        **{
            "item_id": "q001",
            "response_id": "q001::waterbot::blue",
            "judge_model_id": "gpt-4.1-2025-04-14",
            "sample_index": 0,
            "temperature": 0.3,
            "prompt_hash": "p" * 16,
            "rubric_hash": "r" * 16,
            "corpus_fingerprint": "08527fbdf140f811",
            "dimensions": {"grounding": a_dimension()},
            **kw,
        }
    )


def a_measurement_version(**kw) -> MeasurementVersion:
    return MeasurementVersion(
        **{
            "corpus_fingerprint": "08527fbdf140f811",
            "rubric_hash": "r" * 16,
            "prompt_hash": "p" * 16,
            "judge_set": ("claude-x", "gemini-y", "gpt-z"),
            "aggregation_version": "1.0.0",
            "k": 5,
            "temperature": 0.3,
            **kw,
        }
    )


ALL_BUILDERS = [a_passage, a_response, a_dimension, a_verdict, a_measurement_version]


# ---------------------------------------------------------------------------
# Universal properties
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("builder", ALL_BUILDERS)
def test_every_model_forbids_extra_fields(builder):
    """A typo'd field must fail at write time, not vanish silently."""
    payload = builder().model_dump()
    payload["totally_new_field"] = 1
    with pytest.raises(ValidationError):
        type(builder())(**payload)


@pytest.mark.parametrize("builder", ALL_BUILDERS)
def test_every_model_is_frozen(builder):
    """Artifacts are immutable by invariant; enforce it in memory too."""
    instance = builder()
    field = next(iter(type(instance).model_fields))
    with pytest.raises(ValidationError):
        setattr(instance, field, getattr(instance, field))


@pytest.mark.parametrize("builder", ALL_BUILDERS)
def test_every_model_round_trips_through_json(builder):
    instance = builder()
    restored = type(instance).model_validate(json.loads(instance.model_dump_json()))
    assert restored == instance


@pytest.mark.parametrize(
    "model", [Response, Verdict, PairwiseVerdict, DimensionAggregate, HumanLabel, CalibrationMap,
              CorpusIdentity, RunManifest]
)
def test_persisted_models_carry_a_schema_version(model):
    assert "schema_version" in model.model_fields


# ---------------------------------------------------------------------------
# stable_hash
# ---------------------------------------------------------------------------
def test_stable_hash_ignores_key_order():
    """Two logically identical configs must not get different cache entries."""
    assert stable_hash({"a": 1, "b": 2}) == stable_hash({"b": 2, "a": 1})


def test_stable_hash_distinguishes_different_content():
    assert stable_hash({"a": 1}) != stable_hash({"a": 2})


def test_stable_hash_accepts_raw_strings():
    assert stable_hash("prompt text") == stable_hash("prompt text")
    assert stable_hash("prompt text") != stable_hash("other text")


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------
def test_response_id_identifies_item_system_and_persona():
    """Persona is part of identity: the same question under Blue and River is two responses."""
    blue = a_response(persona="blue")
    river = a_response(persona="river")
    assert blue.response_id != river.response_id


def test_duplicate_evidence_ids_are_rejected():
    with pytest.raises(ValidationError, match="duplicate evidence_id"):
        a_response(passages=[a_passage(1), a_passage(1)])


def test_evidence_ids_must_be_dense():
    """The judge cites passages by number; a gap makes a citation ambiguous."""
    with pytest.raises(ValidationError, match=r"must be 1\.\.n"):
        a_response(passages=[a_passage(1), a_passage(3)])


def test_evidence_ids_are_one_based_at_the_field_level():
    """Caught on Passage itself, before a Response is ever assembled."""
    with pytest.raises(ValidationError, match="greater than or equal to 1"):
        a_passage(0, retrieval_rank=0)


def test_a_response_with_no_passages_is_allowed():
    """Out-of-scope negatives legitimately retrieve nothing."""
    assert a_response(passages=[]).passages == []


def test_passage_text_is_pinned_not_empty():
    with pytest.raises(ValidationError):
        a_passage(text="")


def test_negative_cost_is_rejected():
    with pytest.raises(ValidationError):
        a_response(cost_usd=-0.01)


# ---------------------------------------------------------------------------
# DimensionVerdict: the abstention channel
# ---------------------------------------------------------------------------
def test_abstention_requires_a_null_score():
    with pytest.raises(ValidationError, match="if and only if"):
        a_dimension(insufficient_evidence=True, score=3)


def test_a_null_score_requires_abstention():
    """Otherwise a missing score silently becomes an unscored dimension."""
    with pytest.raises(ValidationError, match="if and only if"):
        a_dimension(insufficient_evidence=False, score=None)


def test_a_consistent_abstention_is_accepted():
    verdict = a_dimension(insufficient_evidence=True, score=None)
    assert verdict.score is None


def test_rationale_may_not_be_empty():
    """Rationale-first is the whole point; an empty one is an unaudited score."""
    with pytest.raises(ValidationError):
        a_dimension(rationale="")


@pytest.mark.parametrize("score", [0, 5, 2.5, -1])
def test_scores_outside_the_four_point_scale_are_rejected(score):
    with pytest.raises(ValidationError):
        a_dimension(score=score)


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------
def test_verdict_must_score_at_least_one_dimension():
    with pytest.raises(ValidationError, match="scored no dimensions"):
        a_verdict(dimensions={})


def test_sample_index_is_recorded():
    """Invariant 4: omitting it collapses k samples into one and reports zero variance."""
    assert "sample_index" in Verdict.model_fields
    assert a_verdict(sample_index=4).sample_index == 4


def test_negative_sample_index_is_rejected():
    with pytest.raises(ValidationError):
        a_verdict(sample_index=-1)


def test_abstained_dimensions_are_listed():
    verdict = a_verdict(
        dimensions={
            "grounding": a_dimension(),
            "correctness": a_dimension(insufficient_evidence=True, score=None),
        }
    )
    assert verdict.abstained_dimensions == ["correctness"]


def test_repaired_defaults_false_and_is_recorded():
    """Repair rate is a reported metric; silent retries hide a bias on hard items."""
    assert a_verdict().repaired is False
    assert a_verdict(repaired=True).repaired is True


def test_unknown_failure_mode_is_rejected():
    """A closed set, so a typo cannot read as zero occurrences of a real mode."""
    with pytest.raises(ValidationError):
        a_verdict(failure_modes=["vibes_mismatch"])


def test_known_failure_modes_are_accepted():
    verdict = a_verdict(failure_modes=["entity_substitution", "unit_or_magnitude_drift"])
    assert len(verdict.failure_modes) == 2


# ---------------------------------------------------------------------------
# PairwiseVerdict: order-instability becomes a tie, never a discard
# ---------------------------------------------------------------------------
def a_pairwise(**kw) -> PairwiseVerdict:
    return PairwiseVerdict(
        **{
            "item_id": "q001",
            "system_a": "waterbot",
            "system_b": "realwater",
            "judge_model_id": "gpt-4.1-2025-04-14",
            "sample_index": 0,
            "preference": "a",
            "order_stable": True,
            "verdict_first": "a",
            "verdict_second": "a",
            "corpus_fingerprint": "08527fbdf140f811",
            **kw,
        }
    )


def test_a_stable_pair_keeps_its_preference():
    assert a_pairwise().preference == "a"


def test_a_flipped_pair_must_be_marked_unstable():
    with pytest.raises(ValidationError, match="order_stable must be false"):
        a_pairwise(verdict_first="a", verdict_second="b", order_stable=True, preference="a")


def test_an_unstable_pair_must_be_recorded_as_a_tie():
    """Discarding it would condition the BT fit on a post-treatment variable."""
    with pytest.raises(ValidationError, match="must be recorded as a tie"):
        a_pairwise(verdict_first="a", verdict_second="b", order_stable=False, preference="a")


def test_a_correctly_recorded_flip_is_accepted():
    flipped = a_pairwise(
        verdict_first="a", verdict_second="b", order_stable=False, preference="tie"
    )
    assert flipped.preference == "tie"


# ---------------------------------------------------------------------------
# DimensionAggregate
# ---------------------------------------------------------------------------
def an_aggregate(**kw) -> DimensionAggregate:
    return DimensionAggregate(
        **{
            "response_id": "q001::waterbot::blue",
            "dimension": "grounding",
            "n_votes": 15,
            "n_abstained": 0,
            "median": 3.0,
            "mean": 3.2,
            "iqr": 1.0,
            "entropy": 0.4,
            "ci_low": 2.8,
            "ci_high": 3.6,
            **kw,
        }
    )


def test_escalation_requires_a_reason():
    with pytest.raises(ValidationError, match="requires an escalation_reason"):
        an_aggregate(escalate=True)


def test_a_reason_without_escalation_is_rejected():
    with pytest.raises(ValidationError, match="non-escalated"):
        an_aggregate(escalate=False, escalation_reason="panel_disagreement")


def test_a_valid_escalation_is_accepted():
    aggregate = an_aggregate(escalate=True, escalation_reason="mostly_abstained")
    assert aggregate.escalation_reason == "mostly_abstained"


def test_an_inverted_interval_is_rejected():
    with pytest.raises(ValidationError, match="exceeds ci_high"):
        an_aggregate(ci_low=3.9, ci_high=2.1)


def test_an_all_abstained_aggregate_may_have_null_statistics():
    aggregate = an_aggregate(
        n_votes=0, n_abstained=15, median=None, mean=None, iqr=None,
        entropy=None, ci_low=None, ci_high=None,
        escalate=True, escalation_reason="mostly_abstained",
    )
    assert aggregate.median is None


# ---------------------------------------------------------------------------
# HumanLabel: the pool distinction
# ---------------------------------------------------------------------------
def a_label(**kw) -> HumanLabel:
    return HumanLabel(
        **{
            "response_id": "q001::waterbot::blue",
            "dimension": "grounding",
            "annotator_id": "ab",
            "score": 3,
            "pool": "probe",
            **kw,
        }
    )


def test_label_pool_is_required():
    """Fitting on probe or reporting on acquire is the double bias in Algorithm 4."""
    payload = a_label().model_dump()
    del payload["pool"]
    with pytest.raises(ValidationError):
        HumanLabel(**payload)


def test_unknown_pool_is_rejected():
    with pytest.raises(ValidationError):
        a_label(pool="whatever")


def test_human_abstention_follows_the_same_rule_as_judges():
    with pytest.raises(ValidationError, match="if and only if"):
        a_label(insufficient_evidence=True, score=2)


# ---------------------------------------------------------------------------
# CalibrationMap: the honest-failure guard
# ---------------------------------------------------------------------------
def a_map(**kw) -> CalibrationMap:
    return CalibrationMap(
        **{
            "calibration_map_id": "cal_001",
            "dimension": "grounding",
            "kind": "isotonic",
            "params": {"x": [1, 2], "y": [1.2, 2.4]},
            "n_pairs": 200,
            "n_folds": 5,
            "out_of_fold_mae": 0.31,
            "out_of_fold_mae_sd": 0.05,
            "usable": True,
            **kw,
        }
    )


def test_a_map_worse_than_half_a_level_cannot_be_marked_usable():
    """Algorithm 3: above 0.5 levels the honest output is 'not calibratable'."""
    with pytest.raises(ValidationError, match="not usable at useful resolution"):
        a_map(out_of_fold_mae=0.72, usable=True)


def test_a_bad_map_may_be_recorded_as_unusable():
    unusable = a_map(out_of_fold_mae=0.72, usable=False)
    assert unusable.usable is False


def test_affine_baseline_is_a_valid_kind():
    assert a_map(kind="affine", params={"a": 0.9, "b": 0.2}).kind == "affine"


# ---------------------------------------------------------------------------
# MeasurementVersion: the comparison guard
# ---------------------------------------------------------------------------
def test_identical_versions_are_comparable():
    a_measurement_version().assert_comparable(a_measurement_version())


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
def test_any_difference_blocks_comparison(field, value):
    with pytest.raises(IncompatibleMeasurement) as excinfo:
        a_measurement_version().assert_comparable(a_measurement_version(**{field: value}))
    assert field in str(excinfo.value)


def test_judge_set_must_be_sorted_so_equal_panels_compare_equal():
    with pytest.raises(ValidationError, match="must be sorted"):
        a_measurement_version(judge_set=("gpt-z", "claude-x"))


def test_duplicate_judges_are_rejected():
    with pytest.raises(ValidationError, match="duplicates"):
        a_measurement_version(judge_set=("claude-x", "claude-x"))


def test_version_id_is_stable_and_content_dependent():
    assert a_measurement_version().version_id == a_measurement_version().version_id
    assert a_measurement_version().version_id != a_measurement_version(k=1).version_id


def test_k_must_be_at_least_one():
    with pytest.raises(ValidationError):
        a_measurement_version(k=0)


# ---------------------------------------------------------------------------
# CorpusIdentity and proofs
# ---------------------------------------------------------------------------
def test_exact_hash_proof_must_score_one():
    with pytest.raises(ValidationError, match="score 1.0"):
        DuplicateProof(alias="a.pdf", canonical="b.pdf", method="exact_hash", score=0.9)


def test_minhash_proof_may_score_below_one():
    proof = DuplicateProof(alias="a.pdf", canonical="b.pdf", method="minhash", score=0.94)
    assert proof.score == 0.94


def an_identity(**kw) -> CorpusIdentity:
    return CorpusIdentity(
        **{
            "fingerprint": "08527fbdf140f811",
            "document_count": 360,
            "canonical_count": 288,
            "chunk_count": 5000,
            "chunker_version": "1.0.0",
            "chunk_size": 1000,
            "chunk_overlap": 200,
            "embedding_model": "text-embedding-3-small",
            **kw,
        }
    )


def test_deduplication_cannot_create_documents():
    with pytest.raises(ValidationError, match="cannot create documents"):
        an_identity(document_count=288, canonical_count=360)


def test_identity_records_the_real_corpus_shape():
    """The numbers from the L0 audit in the architecture doc."""
    identity = an_identity()
    assert identity.document_count - identity.canonical_count == 72


# ---------------------------------------------------------------------------
# RunManifest
# ---------------------------------------------------------------------------
def test_manifest_fingerprint_must_match_its_measurement_version():
    with pytest.raises(ValidationError, match="disagrees with its own measurement version"):
        RunManifest(
            run_id="r1",
            corpus_fingerprint="aaaaaaaaaaaaaaaa",
            dataset_version="1.0.0",
            measurement_version=a_measurement_version(),
        )


def test_a_consistent_manifest_is_accepted():
    version = a_measurement_version()
    manifest = RunManifest(
        run_id="r1",
        corpus_fingerprint=version.corpus_fingerprint,
        dataset_version="1.0.0",
        measurement_version=version,
    )
    assert manifest.schema_version == SCHEMA_VERSION
