"""Tests for L4 annotation: pools, label storage, adjudication, and blinding.

Two properties carry the most weight here. Probe and acquire must never share an item, or the
only unbiased error estimate is also the training data. And pre-adjudication labels must survive
adjudication, or the human ceiling - the number that makes every judge result interpretable -
cannot be recovered.

The blinding check is a real test rather than a screenshot: ``scrub`` is the only thing the app
renders, so asserting on it asserts on what an annotator can see.

Network-free, and no UI is launched.
"""

from __future__ import annotations

import pytest

from eval.judge.annotate.app import scrub
from eval.judge.annotate.pools import (
    Candidate,
    LabelPools,
    PoolError,
    assign_to_annotators,
    boundary_distance,
    build_acquire_pool,
    build_pools,
    build_probe_pool,
    candidates_from_aggregates,
    human_ceiling_capacity,
    informativeness,
)
from eval.judge.annotate.store import (
    LabelStore,
    LabelStoreError,
    adjudicate,
    adjudicated_scores,
    ceiling_matrix,
    find_disagreements,
)
from eval.judge.schemas import DimensionAggregate, HumanLabel, Passage, Response

CATEGORIES = [
    "general_policy", "numeric_extraction", "multi_hop",
    "temporal_realtime", "entity_grounding", "out_of_scope_negative",
]


def a_candidate(i, category=None, iqr=0.5, mean=3.0):
    return Candidate(
        response_id=f"q{i:03d}::waterbot::blue",
        dimension="grounding",
        category=category or CATEGORIES[i % len(CATEGORIES)],
        panel_mean=mean,
        panel_iqr=iqr,
    )


def many_candidates(n=60):
    return [a_candidate(i) for i in range(n)]


def a_label(response="q001::waterbot::blue", dimension="grounding", annotator="ab",
            score=3, pool="probe", adjudicated=False):
    return HumanLabel(
        response_id=response, dimension=dimension, annotator_id=annotator,
        score=score, insufficient_evidence=score is None, pool=pool,
        adjudicated=adjudicated,
    )


# ---------------------------------------------------------------------------
# Blinding
# ---------------------------------------------------------------------------
def a_response(**kw) -> Response:
    payload = {
        "item_id": "q001",
        "system": "waterbot",
        "persona": "river",
        "question": "What is the Central Arizona Project?",
        "category": "general_policy",
        "answer": "It is a 336-mile aqueduct.",
        "passages": [
            Passage(evidence_id=1, canonical_doc_id="cap.pdf", chunk_id="c1",
                    text="The CAP is 336 miles long.", retrieval_rank=0, retrieval_score=0.9)
        ],
        "citations": ["cap.pdf"],
        "latency_ms": 100,
        "cost_usd": 0.004,
    }
    payload.update(kw)
    return Response(**payload)


def test_the_annotator_never_sees_the_system_or_persona():
    """Knowing the answer came from WaterBot would stop the label being independent evidence."""
    view = scrub(a_response())
    flattened = repr(view)
    assert "system" not in view and "persona" not in view
    assert "waterbot" not in flattened and "river" not in flattened


def test_the_annotator_never_sees_cost_or_latency():
    """Both correlate with the system, so both would partially unblind it."""
    view = scrub(a_response())
    assert "cost_usd" not in view and "latency_ms" not in view


def test_the_annotator_sees_everything_needed_to_judge():
    view = scrub(a_response())
    assert view["question"] and view["answer"]
    assert view["passages"][0]["text"]
    assert view["passages"][0]["evidence_id"] == 1
    assert view["citations"] == ["cap.pdf"]


def test_passages_are_shown_in_citation_order():
    response = a_response(passages=[
        Passage(evidence_id=2, canonical_doc_id="b.pdf", chunk_id="c2", text="second",
                retrieval_rank=1, retrieval_score=0.5),
        Passage(evidence_id=1, canonical_doc_id="a.pdf", chunk_id="c1", text="first",
                retrieval_rank=0, retrieval_score=0.9),
    ])
    assert [p["evidence_id"] for p in scrub(response)["passages"]] == [1, 2]


# ---------------------------------------------------------------------------
# The probe pool
# ---------------------------------------------------------------------------
def test_the_probe_pool_covers_every_category():
    """At 7 to 15 per category a simple random draw can miss one entirely."""
    probe = build_probe_pool(many_candidates(60), size=12, seed=0)
    assert set(c.category for c in probe) == set(CATEGORIES)


def test_the_probe_pool_is_the_requested_size():
    assert len(build_probe_pool(many_candidates(60), size=18, seed=0)) == 18


def test_the_probe_pool_is_reproducible_by_seed():
    first = build_probe_pool(many_candidates(60), 12, seed=5)
    second = build_probe_pool(many_candidates(60), 12, seed=5)
    assert [c.key for c in first] == [c.key for c in second]


def test_a_different_seed_draws_a_different_probe_pool():
    first = build_probe_pool(many_candidates(60), 12, seed=1)
    second = build_probe_pool(many_candidates(60), 12, seed=2)
    assert [c.key for c in first] != [c.key for c in second]


def test_a_probe_pool_smaller_than_the_category_count_is_refused():
    with pytest.raises(PoolError, match="cannot be represented"):
        build_probe_pool(many_candidates(60), size=3, seed=0)


def test_a_probe_pool_larger_than_the_candidate_set_is_refused():
    with pytest.raises(PoolError, match="cannot draw"):
        build_probe_pool(many_candidates(10), size=50)


# ---------------------------------------------------------------------------
# Acquisition
# ---------------------------------------------------------------------------
def test_acquisition_prefers_contested_items():
    """The whole point: concentrate expert time where it changes the map most."""
    candidates = [a_candidate(i, iqr=0.0) for i in range(30)]
    candidates += [a_candidate(i + 100, iqr=3.0) for i in range(10)]
    acquired = build_acquire_pool(candidates, size=10)
    assert sum(1 for c in acquired if c.panel_iqr == 3.0) >= 8


def test_acquisition_does_not_collapse_onto_one_category():
    """Without the representation term the map gets fitted on a corner of the benchmark."""
    candidates = [a_candidate(i, category="numeric_extraction", iqr=3.0) for i in range(30)]
    candidates += [a_candidate(i + 100, category=CATEGORIES[i % 6], iqr=2.0) for i in range(30)]
    acquired = build_acquire_pool(candidates, size=24, batch_size=6)
    assert len(set(c.category for c in acquired)) >= 3


def test_acquisition_excludes_the_probe_pool():
    """An item cannot be both the unbiased estimate and the training data."""
    candidates = many_candidates(60)
    probe = build_probe_pool(candidates, 12, seed=0)
    acquired = build_acquire_pool(candidates, size=20, exclude=probe)
    assert not ({c.key for c in probe} & {c.key for c in acquired})


def test_acquisition_is_reproducible():
    candidates = many_candidates(60)
    assert [c.key for c in build_acquire_pool(candidates, 20)] == [
        c.key for c in build_acquire_pool(candidates, 20)
    ]


def test_acquiring_more_than_remains_is_refused():
    with pytest.raises(PoolError, match="only"):
        build_acquire_pool(many_candidates(10), size=50)


def test_boundary_distance_peaks_between_levels():
    """An item at 2.5 could round either way; one at 3.0 is settled."""
    assert boundary_distance(2.5) == pytest.approx(1.0)
    assert boundary_distance(3.0) == pytest.approx(0.0)
    assert boundary_distance(2.6) > boundary_distance(2.9)


def test_a_missing_panel_score_is_maximally_uncertain():
    assert boundary_distance(None) == 1.0


def test_informativeness_rises_with_disagreement():
    from collections import Counter

    settled = a_candidate(1, iqr=0.0, mean=3.0)
    contested = a_candidate(2, iqr=3.0, mean=3.0)
    assert informativeness(contested, Counter()) > informativeness(settled, Counter())


# ---------------------------------------------------------------------------
# Both pools together
# ---------------------------------------------------------------------------
def test_the_pools_never_share_an_item():
    pools = build_pools(many_candidates(60), budget=40, seed=0)
    assert not ({c.key for c in pools.probe} & {c.key for c in pools.acquire})


def test_the_pools_spend_the_whole_budget():
    pools = build_pools(many_candidates(60), budget=40, seed=0)
    assert pools.budget == 40


def test_the_probe_fraction_is_respected():
    pools = build_pools(many_candidates(100), budget=60, probe_fraction=0.35, seed=0)
    assert len(pools.probe) == round(60 * 0.35)


def test_pool_membership_can_be_looked_up():
    pools = build_pools(many_candidates(60), budget=40, seed=0)
    probe_item = pools.probe[0]
    assert pools.pool_of(*probe_item.key) == "probe"
    assert pools.pool_of("nonexistent", "grounding") is None


@pytest.mark.parametrize("fraction", [0.0, 1.0, 1.5, -0.2])
def test_an_impossible_probe_fraction_is_refused(fraction):
    with pytest.raises(PoolError):
        build_pools(many_candidates(60), budget=40, probe_fraction=fraction)


def test_a_budget_larger_than_the_candidate_set_is_refused():
    with pytest.raises(PoolError, match="exceeds"):
        build_pools(many_candidates(10), budget=50)


def test_candidates_require_a_known_category():
    aggregate = DimensionAggregate(
        response_id="q001::waterbot::blue", dimension="grounding",
        n_votes=15, n_abstained=0, median=3.0, mean=3.0, iqr=0.5, entropy=0.2,
    )
    with pytest.raises(PoolError, match="no category recorded"):
        candidates_from_aggregates([aggregate], {})


# ---------------------------------------------------------------------------
# Assignment and the ceiling capacity
# ---------------------------------------------------------------------------
def test_every_annotator_shares_the_overlap_items():
    pools = build_pools(many_candidates(60), budget=40, seed=0)
    assignments = assign_to_annotators(pools, ["ab", "cd", "ef"], overlap=8, seed=0)
    assert human_ceiling_capacity(assignments) == 8


def test_the_overlap_is_drawn_from_the_probe_pool():
    """Agreement on uncertainty-sampled items would describe agreement on hard cases only."""
    pools = build_pools(many_candidates(60), budget=40, seed=0)
    assignments = assign_to_annotators(pools, ["ab", "cd"], overlap=6, seed=0)
    shared = set.intersection(*({c.key for c in v} for v in assignments.values()))
    assert shared <= {c.key for c in pools.probe}


def test_every_item_is_assigned_to_someone():
    pools = build_pools(many_candidates(60), budget=40, seed=0)
    assignments = assign_to_annotators(pools, ["ab", "cd"], overlap=5, seed=0)
    assigned = {c.key for items in assignments.values() for c in items}
    assert assigned == {c.key for c in pools.probe + pools.acquire}


def test_an_overlap_larger_than_the_probe_pool_is_refused():
    pools = build_pools(many_candidates(60), budget=40, seed=0)
    with pytest.raises(PoolError, match="human ceiling can only be measured"):
        assign_to_annotators(pools, ["ab", "cd"], overlap=999)


def test_duplicate_annotator_ids_are_refused():
    pools = build_pools(many_candidates(60), budget=40, seed=0)
    with pytest.raises(PoolError, match="distinct"):
        assign_to_annotators(pools, ["ab", "ab"], overlap=2)


# ---------------------------------------------------------------------------
# The label store
# ---------------------------------------------------------------------------
def test_labels_round_trip(tmp_path):
    store = LabelStore(str(tmp_path / "labels.jsonl"))
    store.append([a_label()])
    assert store.load_all()[0].score == 3


def test_appending_never_rewrites(tmp_path):
    store = LabelStore(str(tmp_path / "labels.jsonl"))
    store.append([a_label(annotator="ab")])
    store.append([a_label(annotator="cd")])
    assert len(store.load_all()) == 2


def test_a_revised_score_is_kept_in_history_and_the_latest_wins(tmp_path):
    """Autosave means an annotator revising within a session must not be an error."""
    store = LabelStore(str(tmp_path / "labels.jsonl"))
    store.append([a_label(score=2)])
    store.append([a_label(score=4)])
    assert len(store.load_all()) == 2
    latest = store.load_latest()
    assert len(latest) == 1 and latest[0].score == 4


def test_a_corrupt_label_file_names_its_line(tmp_path):
    path = tmp_path / "labels.jsonl"
    path.write_text('{"nope": 1}\n', encoding="utf-8")
    with pytest.raises(LabelStoreError, match="line 1"):
        LabelStore(str(path)).load_all()


def test_progress_reports_what_is_left(tmp_path):
    store = LabelStore(str(tmp_path / "labels.jsonl"))
    store.append([a_label(response=f"q{i:03d}::waterbot::blue") for i in range(4)])
    progress = store.progress(assigned=10)
    assert progress["completed"] == 4 and progress["remaining"] == 6


# ---------------------------------------------------------------------------
# The human ceiling survives adjudication
# ---------------------------------------------------------------------------
def test_the_ceiling_matrix_uses_only_shared_items():
    labels = [
        a_label(response="q1", annotator="ab", score=3),
        a_label(response="q1", annotator="cd", score=4),
        a_label(response="q2", annotator="ab", score=2),  # only ab saw q2
    ]
    annotators, items, rows = ceiling_matrix(labels, "grounding")
    assert annotators == ["ab", "cd"]
    assert items == ["q1"]
    assert rows == [[3], [4]]


def test_the_ceiling_matrix_preserves_abstentions():
    labels = [
        a_label(response="q1", annotator="ab", score=3),
        a_label(response="q1", annotator="cd", score=None),
    ]
    _, _, rows = ceiling_matrix(labels, "grounding")
    assert rows == [[3], [None]]


def test_adjudication_never_overwrites_the_originals(tmp_path):
    """The pre-adjudication labels ARE the human ceiling; losing them loses the ceiling."""
    store = LabelStore(str(tmp_path / "labels.jsonl"))
    store.append([
        a_label(response="q1", annotator="ab", score=2),
        a_label(response="q1", annotator="cd", score=4),
    ])
    disagreement = find_disagreements(store.load_latest())[0]
    store.append([adjudicate(disagreement, score=3, adjudicator_id="zz")])

    pre = store.load_pre_adjudication()
    assert sorted(label.score for label in pre) == [2, 4]
    assert all(not label.adjudicated for label in pre)


def test_the_ceiling_is_computed_before_adjudication(tmp_path):
    """Agreement on adjudicated labels is agreement with the adjudicator, not between raters."""
    store = LabelStore(str(tmp_path / "labels.jsonl"))
    store.append([
        a_label(response="q1", annotator="ab", score=2),
        a_label(response="q1", annotator="cd", score=4),
    ])
    disagreement = find_disagreements(store.load_latest())[0]
    store.append([adjudicate(disagreement, score=3, adjudicator_id="zz")])

    _, _, rows = ceiling_matrix(store.load_pre_adjudication(), "grounding")
    assert rows == [[2], [4]]  # the disagreement is still visible


def test_agreement_is_not_a_disagreement():
    labels = [
        a_label(response="q1", annotator="ab", score=3),
        a_label(response="q1", annotator="cd", score=3),
    ]
    assert find_disagreements(labels) == []


def test_adjacent_scores_are_within_tolerance_by_default():
    labels = [
        a_label(response="q1", annotator="ab", score=3),
        a_label(response="q1", annotator="cd", score=4),
    ]
    assert find_disagreements(labels, threshold=1) == []
    assert len(find_disagreements(labels, threshold=0)) == 1


def test_one_person_abstaining_is_a_disagreement_worth_adjudicating():
    """One found the evidence sufficient and one did not; the rubric should settle that."""
    labels = [
        a_label(response="q1", annotator="ab", score=3),
        a_label(response="q1", annotator="cd", score=None),
    ]
    assert len(find_disagreements(labels)) == 1


def test_an_item_only_one_person_saw_is_not_a_disagreement():
    assert find_disagreements([a_label(response="q1", annotator="ab")]) == []


def test_final_scores_use_consensus_where_it_exists():
    labels = [
        a_label(response="q1", annotator="ab", score=3),
        a_label(response="q1", annotator="cd", score=3),
    ]
    assert adjudicated_scores(labels)[("q1", "grounding")] == 3


def test_final_scores_prefer_the_adjudication():
    labels = [
        a_label(response="q1", annotator="ab", score=2),
        a_label(response="q1", annotator="cd", score=4),
        a_label(response="q1", annotator="zz", score=3, adjudicated=True),
    ]
    assert adjudicated_scores(labels)[("q1", "grounding")] == 3


def test_an_unresolved_disagreement_is_omitted_rather_than_averaged():
    """An unresolved disagreement is not a score, and averaging would invent one."""
    labels = [
        a_label(response="q1", annotator="ab", score=1),
        a_label(response="q1", annotator="cd", score=4),
    ]
    assert ("q1", "grounding") not in adjudicated_scores(labels)


def test_the_adjudicator_is_recorded():
    disagreement = find_disagreements([
        a_label(response="q1", annotator="ab", score=1),
        a_label(response="q1", annotator="cd", score=4),
    ])[0]
    label = adjudicate(disagreement, score=2, adjudicator_id="zz")
    assert label.annotator_id == "zz" and label.adjudicated is True


def test_an_adjudicator_may_also_abstain():
    disagreement = find_disagreements([
        a_label(response="q1", annotator="ab", score=1),
        a_label(response="q1", annotator="cd", score=4),
    ])[0]
    label = adjudicate(disagreement, score=None, adjudicator_id="zz")
    assert label.score is None and label.insufficient_evidence is True
