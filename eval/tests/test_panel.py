"""Tests for the verdict cache and the panel runner (L2).

The single most important test in this file is that ``sample_index`` changes the cache key.
Omitting it collapses k samples into one cached verdict served k times, which reports perfect
agreement and zero variance from a panel that was asked once - a result that would look exactly
like the finding this project is trying to establish, arrived at by accident.

Network-free: every judge is a FakeJudgeClient (invariant 3).
"""

from __future__ import annotations

import json

import pytest

from eval.judge.cache import CacheError, CacheStats, VerdictCache, cache_key, implausible_hit_rate
from eval.judge.clients.fake import FakeJudgeClient
from eval.judge.panel import (
    Budget,
    BudgetExceeded,
    Completion,
    PanelRunner,
    Pricing,
    VerdictRejected,
    normalise_span,
    parametric_reliance,
    parse_verdict,
    validate_verdict,
    withhold_evidence,
)
from eval.judge.rubric import load_rubric
from eval.judge.schemas import DimensionVerdict, Passage, Response, Verdict

FINGERPRINT = "08527fbdf140f811"


@pytest.fixture(scope="module")
def rubric():
    return load_rubric()


def a_passage(evidence_id=1, doc="cap.pdf", text="The CAP is 336 miles long."):
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
        "answer": "The Central Arizona Project is a 336-mile aqueduct delivering water.",
        "passages": [a_passage(1), a_passage(2, "cap2.pdf", "It serves Phoenix.")],
        "citations": ["cap.pdf"],
        "latency_ms": 100,
        "cost_usd": 0.004,
    }
    payload.update(kw)
    return Response(**payload)


def a_verdict(**kw) -> Verdict:
    payload = {
        "item_id": "q001",
        "response_id": "q001::waterbot::blue",
        "judge_model_id": "fake-judge-v1",
        "sample_index": 0,
        "temperature": 0.3,
        "prompt_hash": "p" * 16,
        "rubric_hash": "r" * 16,
        "corpus_fingerprint": FINGERPRINT,
        "dimensions": {"grounding": DimensionVerdict(rationale="ok", score=3,
                                                     quoted_span="", evidence_ids=[1])},
    }
    payload.update(kw)
    return Verdict(**payload)


def base_key(**overrides):
    args = {
        "judge_model_id": "judge-a",
        "prompt_hash": "p" * 16,
        "rubric_hash": "r" * 16,
        "corpus_fingerprint": FINGERPRINT,
        "item_id": "q001",
        "sample_index": 0,
        "temperature": 0.3,
        "protocol": "pointwise",
        "order": "none",
    }
    args.update(overrides)
    return cache_key(**args)


def a_runner(rubric, clients=None, **kw):
    settings = {
        "clients": [FakeJudgeClient("judge-a", seed=1)] if clients is None else clients,
        "rubric": rubric,
        "rubric_hash": "r" * 16,
        "corpus_fingerprint": FINGERPRINT,
        "samples": 3,
        "allow_unpiloted_rubric": True,
    }
    settings.update(kw)
    return PanelRunner(**settings)


# ---------------------------------------------------------------------------
# The cache key
# ---------------------------------------------------------------------------
def test_sample_index_changes_the_key():
    """Invariant 4, and the single easiest way to fake a great result by accident.

    Without this, k=5 becomes one cached verdict served five times: perfect agreement, zero
    variance, from a panel that was only ever asked once.
    """
    assert base_key(sample_index=0) != base_key(sample_index=1)


@pytest.mark.parametrize(
    "field,value",
    [
        ("judge_model_id", "judge-b"),
        ("prompt_hash", "x" * 16),
        ("rubric_hash", "y" * 16),
        ("corpus_fingerprint", "deadbeefdeadbeef"),
        ("item_id", "q002"),
        ("sample_index", 4),
        ("temperature", 0.0),
        ("protocol", "pairwise"),
        ("order", "swapped"),
    ],
)
def test_every_key_component_changes_the_key(field, value):
    assert base_key() != base_key(**{field: value})


def test_the_same_inputs_give_the_same_key():
    assert base_key() == base_key()


def test_temperature_is_normalised_so_equal_values_share_an_entry():
    """0.3 and 0.30 are the same configuration and must not become two cache entries."""
    assert base_key(temperature=0.3) == base_key(temperature=0.30)


def test_a_negative_sample_index_is_rejected():
    with pytest.raises(CacheError, match="non-negative"):
        base_key(sample_index=-1)


def test_an_empty_judge_id_is_rejected():
    """An empty id would pool verdicts from different judges under one key."""
    with pytest.raises(CacheError, match="judge_model_id"):
        base_key(judge_model_id="")


# ---------------------------------------------------------------------------
# The cache
# ---------------------------------------------------------------------------
def test_a_stored_verdict_comes_back():
    cache = VerdictCache()
    cache.put("k1", a_verdict())
    assert cache.get("k1") == a_verdict()


def test_a_miss_returns_none_and_is_counted():
    cache = VerdictCache()
    assert cache.get("absent") is None
    assert cache.stats.misses == 1 and cache.stats.hits == 0


def test_hit_rate_is_reported():
    cache = VerdictCache()
    cache.put("k1", a_verdict())
    cache.get("k1")
    cache.get("absent")
    assert cache.stats.hit_rate == pytest.approx(0.5)


def test_storing_a_different_verdict_under_an_existing_key_is_refused():
    """Two verdicts sharing a key means the key omits something that changed the result."""
    cache = VerdictCache()
    cache.put("k1", a_verdict(sample_index=0))
    with pytest.raises(CacheError, match="already holds a different verdict"):
        cache.put("k1", a_verdict(sample_index=0, overall_confidence="low"))


def test_storing_a_semantically_identical_verdict_again_is_fine():
    """Two separately built verdicts differ only in created_at, which is provenance not content.

    This is the resume case: a run re-judging an item it already judged must hit the cache, not
    raise a key collision because the clock moved.
    """
    cache = VerdictCache()
    cache.put("k1", a_verdict())
    cache.put("k1", a_verdict())
    assert len(cache) == 1


def test_the_cache_persists_and_reloads(tmp_path):
    path = str(tmp_path / "verdicts.jsonl")
    # One instance, reused: Verdict stamps created_at at construction, so two separately built
    # verdicts are never equal even with identical content.
    verdict = a_verdict()
    VerdictCache(path).put("k1", verdict)
    assert VerdictCache(path).get("k1") == verdict


def test_a_corrupt_cache_file_names_the_line(tmp_path):
    path = tmp_path / "verdicts.jsonl"
    path.write_text('{"cache_key": "k", "verdict": {}}\nnot json\n', encoding="utf-8")
    with pytest.raises(CacheError, match="line"):
        VerdictCache(str(path))


def test_an_implausible_hit_rate_on_a_fresh_configuration_is_flagged():
    """High hits on something never run before means the key is not separating configurations."""
    stats = CacheStats(hits=9, misses=1)
    assert implausible_hit_rate(stats, fresh_configuration=True) is True
    assert implausible_hit_rate(stats, fresh_configuration=False) is False


def test_a_low_hit_rate_on_a_fresh_configuration_is_normal():
    assert implausible_hit_rate(CacheStats(hits=0, misses=20), fresh_configuration=True) is False


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def test_a_clean_verdict_has_no_problems():
    response = a_response()
    verdict = a_verdict(dimensions={
        "grounding": DimensionVerdict(
            rationale="supported", quoted_span="The Central Arizona Project",
            evidence_ids=[1], score=4,
        )
    })
    assert validate_verdict(verdict, response) == []


def test_citing_evidence_that_was_never_shown_is_caught():
    """A judge citing passage 9 when shown 2 is hallucinating its own grounding."""
    verdict = a_verdict(dimensions={
        "grounding": DimensionVerdict(rationale="x", evidence_ids=[9], score=3)
    })
    problems = validate_verdict(verdict, a_response())
    assert any("cites evidence [9]" in p for p in problems)


def test_a_quoted_span_absent_from_the_answer_is_caught():
    """The check that makes span quoting worth requiring at all."""
    verdict = a_verdict(dimensions={
        "grounding": DimensionVerdict(
            rationale="x", quoted_span="a sentence never written", evidence_ids=[1], score=3
        )
    })
    problems = validate_verdict(verdict, a_response())
    assert any("does not appear in the response" in p for p in problems)


def test_span_matching_tolerates_whitespace_and_case():
    verdict = a_verdict(dimensions={
        "grounding": DimensionVerdict(
            rationale="x", quoted_span="the   CENTRAL arizona\nproject", evidence_ids=[1], score=3
        )
    })
    assert validate_verdict(verdict, a_response()) == []


def test_span_matching_does_not_tolerate_different_words():
    """Normalisation must not be so aggressive that it hides a fabricated quote."""
    verdict = a_verdict(dimensions={
        "grounding": DimensionVerdict(
            rationale="x", quoted_span="the Central Arizona Venture", evidence_ids=[1], score=3
        )
    })
    assert validate_verdict(verdict, a_response()) != []


def test_an_empty_span_is_allowed():
    """Legitimate when abstaining, or when the dimension is about the answer as a whole."""
    verdict = a_verdict(dimensions={
        "grounding": DimensionVerdict(rationale="x", quoted_span="", evidence_ids=[1], score=3)
    })
    assert validate_verdict(verdict, a_response()) == []


def test_abstaining_while_citing_evidence_is_incoherent():
    verdict = a_verdict(dimensions={
        "grounding": DimensionVerdict(
            rationale="unclear", evidence_ids=[1], insufficient_evidence=True, score=None
        )
    })
    problems = validate_verdict(verdict, a_response())
    assert any("abstained" in p for p in problems)


def test_all_problems_are_reported_at_once():
    verdict = a_verdict(dimensions={
        "grounding": DimensionVerdict(
            rationale="x", quoted_span="never said this", evidence_ids=[9], score=3
        )
    })
    assert len(validate_verdict(verdict, a_response())) == 2


def test_normalise_span_collapses_whitespace():
    assert normalise_span("  The   CAP\n\tis long ") == "the cap is long"


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
def _parse(raw):
    return parse_verdict(raw, a_response(), "judge-a", 0, 0.3, "p" * 16, "r" * 16)


def test_malformed_json_is_rejected():
    with pytest.raises(VerdictRejected, match="not valid JSON"):
        _parse("{not json")


def test_a_json_array_is_rejected():
    with pytest.raises(VerdictRejected, match="expected an object"):
        _parse("[1, 2, 3]")


def test_output_with_no_dimensions_is_rejected():
    with pytest.raises(VerdictRejected, match="no dimensions"):
        _parse(json.dumps({"dimensions": {}, "overall_confidence": "high"}))


def test_a_dimension_breaking_the_abstention_rule_is_rejected():
    """score must be null if and only if insufficient_evidence."""
    payload = {"dimensions": {"grounding": {
        "rationale": "x", "quoted_span": "", "evidence_ids": [],
        "insufficient_evidence": True, "score": 3,
    }}, "failure_modes": [], "overall_confidence": "high"}
    with pytest.raises(VerdictRejected, match="malformed"):
        _parse(json.dumps(payload))


def test_a_well_formed_verdict_parses():
    payload = {"dimensions": {"grounding": {
        "rationale": "supported", "quoted_span": "The Central Arizona Project",
        "evidence_ids": [1], "insufficient_evidence": False, "score": 4,
    }}, "failure_modes": ["overrefusal"], "overall_confidence": "high"}
    verdict = _parse(json.dumps(payload))
    assert verdict.dimensions["grounding"].score == 4
    assert verdict.failure_modes == ["overrefusal"]


# ---------------------------------------------------------------------------
# The fan-out
# ---------------------------------------------------------------------------
def test_m_judges_times_k_samples(rubric):
    runner = a_runner(rubric, clients=[
        FakeJudgeClient("judge-a", seed=1),
        FakeJudgeClient("judge-b", seed=2),
        FakeJudgeClient("judge-c", seed=3),
    ], samples=5)
    verdicts = runner.judge_response(a_response())
    assert len(verdicts) == 15


def test_k_samples_produce_distinct_sample_indices(rubric):
    """Milestone 6's acceptance check: k=5 produces five verdicts, not one repeated."""
    runner = a_runner(rubric, samples=5)
    verdicts = runner.judge_response(a_response())
    assert sorted(v.sample_index for v in verdicts) == [0, 1, 2, 3, 4]


def test_k_samples_actually_differ(rubric):
    """If the fake returned a constant, variance would be an artifact of the test."""
    runner = a_runner(rubric, samples=8)
    scores = [v.dimensions["grounding"].score for v in runner.judge_response(a_response())]
    assert len(set(scores)) > 1


def test_duplicate_judge_ids_are_refused(rubric):
    with pytest.raises(ValueError, match="distinct"):
        a_runner(rubric, clients=[FakeJudgeClient("same"), FakeJudgeClient("same")])


def test_a_panel_needs_a_judge(rubric):
    with pytest.raises(ValueError, match="at least one judge"):
        a_runner(rubric, clients=[])


def test_k_must_be_at_least_one(rubric):
    with pytest.raises(ValueError, match="at least 1"):
        a_runner(rubric, samples=0)


def test_verdicts_carry_the_run_fingerprint(rubric):
    verdicts = a_runner(rubric).judge_response(a_response())
    assert all(v.corpus_fingerprint == FINGERPRINT for v in verdicts)


def test_judging_a_set_covers_every_response(rubric):
    runner = a_runner(rubric, samples=2)
    responses = [a_response(item_id="q001"), a_response(item_id="q002")]
    verdicts = runner.judge_all(responses)
    assert {v.item_id for v in verdicts} == {"q001", "q002"}


# ---------------------------------------------------------------------------
# The unpiloted rubric guard
# ---------------------------------------------------------------------------
def test_an_unpiloted_rubric_blocks_a_panel_run(rubric):
    """If two humans cannot agree using these anchors, no model will."""
    assert rubric.is_piloted is False
    with pytest.raises(ValueError, match="not been piloted"):
        PanelRunner(
            clients=[FakeJudgeClient("judge-a")], rubric=rubric, rubric_hash="r" * 16,
            corpus_fingerprint=FINGERPRINT,
        )


def test_an_unpiloted_rubric_can_be_used_deliberately(rubric):
    runner = a_runner(rubric)
    assert runner.judge_response(a_response())


# ---------------------------------------------------------------------------
# Caching in the runner
# ---------------------------------------------------------------------------
def test_a_second_identical_run_is_served_from_cache(rubric):
    cache = VerdictCache()
    runner = a_runner(rubric, cache=cache, samples=3)
    runner.judge_response(a_response())
    calls_after_first = runner.stats.called

    runner.judge_response(a_response())
    assert runner.stats.called == calls_after_first  # no new provider calls
    assert runner.stats.from_cache == 3


def test_caching_can_be_bypassed(rubric):
    runner = a_runner(rubric)
    response = a_response()
    runner.judge_once(response, runner.clients[0], 0, use_cache=False)
    runner.judge_once(response, runner.clients[0], 0, use_cache=False)
    assert runner.stats.called == 2


# ---------------------------------------------------------------------------
# Repair
# ---------------------------------------------------------------------------
def test_a_malformed_verdict_triggers_one_repair(rubric):
    client = FakeJudgeClient("judge-a", malformed_on_call=lambda n: n == 1)
    runner = a_runner(rubric, clients=[client], samples=1)
    verdicts = runner.judge_response(a_response())
    assert len(verdicts) == 1
    assert verdicts[0].repaired is True
    assert runner.stats.repaired == 1


def test_the_repair_rate_is_reported(rubric):
    """Silent retries hide a bias: failures concentrate on hard items."""
    client = FakeJudgeClient("judge-a", malformed_on_call=lambda n: n % 2 == 1)
    runner = a_runner(rubric, clients=[client], samples=2)
    runner.judge_response(a_response())
    assert runner.report()["stats"]["repair_rate"] > 0


def test_a_hallucinated_evidence_id_triggers_repair(rubric):
    client = FakeJudgeClient("judge-a", invent_evidence_id=99)
    runner = a_runner(rubric, clients=[client], samples=1)
    with pytest.raises(VerdictRejected, match="cites evidence"):
        runner.judge_response(a_response(), skip_rejected=False)
    assert runner.stats.repaired == 1


def test_a_fabricated_span_triggers_repair(rubric):
    client = FakeJudgeClient("judge-a", bogus_span="a sentence never written")
    runner = a_runner(rubric, clients=[client], samples=1)
    with pytest.raises(VerdictRejected, match="does not appear"):
        runner.judge_response(a_response(), skip_rejected=False)


def test_repair_is_attempted_once_not_repeatedly(rubric):
    """Retrying blind turns a systematic failure into a cost."""
    client = FakeJudgeClient("judge-a", invent_evidence_id=99)
    runner = a_runner(rubric, clients=[client], samples=1)
    runner.judge_response(a_response())
    assert client.calls and len(client.calls) == 2  # original plus exactly one repair


def test_a_twice_failing_verdict_is_skipped_not_fatal(rubric):
    """One judge failing on one item should not discard the other m*k-1 opinions."""
    good = FakeJudgeClient("judge-good", seed=1)
    bad = FakeJudgeClient("judge-bad", invent_evidence_id=99)
    runner = a_runner(rubric, clients=[good, bad], samples=2)
    verdicts = runner.judge_response(a_response())
    assert len(verdicts) == 2  # only the good judge's samples survive
    assert runner.stats.rejected == 2
    assert runner.report()["stats"]["rejection_rate"] > 0


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------
def test_the_budget_aborts_a_run_that_would_cross_the_cap(rubric):
    runner = a_runner(
        rubric,
        pricing={"judge-a": Pricing(prompt=1.0, completion=1.0)},
        budget=Budget(cap_usd=0.001),
        samples=5,
    )
    with pytest.raises(BudgetExceeded, match="budget cap"):
        runner.judge_response(a_response())


def test_spend_accumulates_from_reported_usage(rubric):
    runner = a_runner(
        rubric,
        clients=[FakeJudgeClient("judge-a", prompt_tokens=1000, completion_tokens=500)],
        pricing={"judge-a": Pricing(prompt=0.002, completion=0.008)},
        samples=2,
    )
    runner.judge_response(a_response())
    assert runner.budget.spent_usd == pytest.approx(2 * (0.002 + 4 * 0.001), abs=1e-9)


def test_cached_prompt_tokens_bill_lower(rubric):
    """The point of marking the rubric block cacheable."""
    plain = FakeJudgeClient("judge-a", prompt_tokens=1000, cached_tokens=0, completion_tokens=0)
    cached = FakeJudgeClient("judge-b", prompt_tokens=1000, cached_tokens=900, completion_tokens=0)
    pricing = {"judge-a": Pricing(0.002, 0.008, 0.0002),
               "judge-b": Pricing(0.002, 0.008, 0.0002)}

    a = a_runner(rubric, clients=[plain], pricing=pricing, samples=1)
    a.judge_response(a_response())
    b = a_runner(rubric, clients=[cached], pricing=pricing, samples=1)
    b.judge_response(a_response())
    assert b.budget.spent_usd < a.budget.spent_usd


def test_no_cap_means_no_limit(rubric):
    runner = a_runner(rubric, budget=Budget(cap_usd=None), samples=2)
    runner.judge_response(a_response())
    assert runner.budget.remaining is None


def test_the_budget_reports_what_is_left(rubric):
    runner = a_runner(
        rubric, pricing={"judge-a": Pricing(0.002, 0.008)},
        budget=Budget(cap_usd=10.0), samples=1,
    )
    runner.judge_response(a_response())
    assert 0 < runner.budget.remaining < 10.0


# ---------------------------------------------------------------------------
# Abstention accounting
# ---------------------------------------------------------------------------
def test_abstentions_are_counted_separately_from_scores(rubric):
    client = FakeJudgeClient("judge-a", abstain_dimensions=["grounding"])
    runner = a_runner(rubric, clients=[client], samples=2)
    runner.judge_response(a_response(), dimensions=["grounding", "correctness"])
    assert runner.stats.abstained_dimensions == 2
    assert runner.stats.scored_dimensions == 2
    assert runner.report()["stats"]["abstention_rate"] == pytest.approx(0.5)


def test_an_abstention_is_never_a_zero(rubric):
    client = FakeJudgeClient("judge-a", abstain_dimensions=["grounding"])
    runner = a_runner(rubric, clients=[client], samples=1)
    verdict = runner.judge_response(a_response(), dimensions=["grounding"])[0]
    assert verdict.dimensions["grounding"].score is None


# ---------------------------------------------------------------------------
# The withheld-evidence probe
# ---------------------------------------------------------------------------
def test_withholding_swaps_the_evidence_but_keeps_the_answer():
    original = a_response(item_id="q001")
    donor = a_response(item_id="q050", passages=[a_passage(1, "unrelated.pdf", "Mumbai water.")])
    probed = withhold_evidence(original, donor)

    assert probed.answer == original.answer
    assert probed.question == original.question
    assert [p.canonical_doc_id for p in probed.passages] == ["unrelated.pdf"]


def test_withheld_evidence_is_renumbered_densely():
    """The response contract requires 1..n; a donor's ids may start anywhere."""
    donor = a_response(item_id="q050", passages=[a_passage(1), a_passage(2), a_passage(3)])
    probed = withhold_evidence(a_response(item_id="q001"), donor)
    assert [p.evidence_id for p in probed.passages] == [1, 2, 3]


def test_an_item_cannot_donate_to_itself():
    with pytest.raises(ValueError, match="different item"):
        withhold_evidence(a_response(item_id="q001"), a_response(item_id="q001"))


def test_parametric_reliance_is_zero_when_the_judge_abstains(rubric):
    """A well-behaved judge shown irrelevant evidence should decline to score."""
    client = FakeJudgeClient("judge-a", abstain_dimensions=["grounding"])
    runner = a_runner(rubric, clients=[client], samples=2)
    verdicts = runner.judge_response(a_response(), dimensions=["grounding"])
    assert parametric_reliance(verdicts)["scored_rate"] == 0.0


def test_parametric_reliance_flags_confident_scoring_without_evidence(rubric):
    """Every dimension scored anyway is one answered from memory."""
    client = FakeJudgeClient("judge-a", confidence="high")
    runner = a_runner(rubric, clients=[client], samples=2)
    verdicts = runner.judge_response(a_response(), dimensions=["grounding"])
    reliance = parametric_reliance(verdicts)
    assert reliance["scored_rate"] == 1.0
    assert reliance["confident_rate"] == 1.0


def test_parametric_reliance_on_nothing_is_zero():
    assert parametric_reliance([])["n_verdicts"] == 0


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def test_the_report_names_the_judges_and_the_design(rubric):
    runner = a_runner(rubric, clients=[
        FakeJudgeClient("judge-a"), FakeJudgeClient("judge-b")
    ], samples=4)
    runner.judge_response(a_response())
    report = runner.report()
    assert report["judges"] == ["judge-a", "judge-b"]
    assert report["samples_per_judge"] == 4
    assert report["stats"]["requested"] == 8
    assert "cache" in report and "budget" in report


def test_a_provider_error_propagates_rather_than_being_swallowed(rubric):
    """The legacy judge's silent keyword fallback is exactly what this must not repeat."""
    client = FakeJudgeClient("judge-a", raise_on_call=lambda n: True)
    runner = a_runner(rubric, clients=[client], samples=1)
    with pytest.raises(RuntimeError, match="injected provider failure"):
        runner.judge_response(a_response())
