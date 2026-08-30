"""Tests for M5's three-arm rubric pilot.

Two halves are testable without annotators: which items get chosen, and what happens to the
labels once they come back. The half that is not testable here is the one that needs two
people, and `test_the_check_is_open_until_humans_have_annotated` pins down that the code says so
rather than defaulting to a pass.
"""

from __future__ import annotations

import json
import os

import pytest

from eval.gold_set import load_gold_set
from eval.judge.pilot import (
    ARMS,
    PILOT_ITEM_IDS,
    USABLE_AGREEMENT,
    PilotError,
    PilotLabel,
    arm_results,
    build_packet,
    estimated_minutes_per_annotator,
    fixed_pilot_items,
    pilot_composition,
    pilot_status,
    select_pilot_items,
    write_packet,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GOLD_PATH = os.path.join(REPO_ROOT, "gold_set.json")

pytestmark = pytest.mark.skipif(
    not os.path.exists(GOLD_PATH), reason="gold_set.json not present in the repo root"
)


@pytest.fixture(scope="module")
def gold():
    return load_gold_set(GOLD_PATH)


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------
def test_the_fixed_twelve_are_exactly_what_was_asked_for(gold):
    chosen = fixed_pilot_items(gold)
    assert [i.id for i in chosen] == sorted(PILOT_ITEM_IDS)
    assert len(chosen) == 12


def test_the_fixed_pilot_keeps_four_refusal_items(gold):
    """Four of the gold set's five. q030 is dropped as a near-duplicate of q009."""
    chosen = fixed_pilot_items(gold)
    refusal = sorted(i.id for i in chosen if i.should_refuse)
    assert refusal == ["q008", "q009", "q012", "q023"]
    assert "q030" not in {i.id for i in chosen}


def test_the_fixed_pilot_keeps_the_well_items_including_the_exempt_pair(gold):
    """The exempt/non-exempt pair is a distinction that is real and easy to blur."""
    ids = {i.id for i in fixed_pilot_items(gold)}
    assert {"q017", "q018"} <= ids, "the exempt / non-exempt well pair must travel together"
    assert {"q020", "q027"} <= ids


def test_the_fixed_pilot_still_covers_every_category(gold):
    chosen = fixed_pilot_items(gold)
    assert {i.category for i in chosen} == {i.category for i in gold}


def test_an_unknown_item_id_is_refused_rather_than_silently_dropped(gold):
    """A pilot that quietly ran on eleven items would still produce a kappa nobody could trust."""
    with pytest.raises(PilotError, match="no item"):
        fixed_pilot_items(gold, ("q004", "q999"))


def test_a_repeated_item_id_is_refused(gold):
    with pytest.raises(PilotError, match="repeated"):
        fixed_pilot_items(gold, ("q004", "q004"))


def test_an_empty_id_list_is_refused(gold):
    with pytest.raises(PilotError):
        fixed_pilot_items(gold, ())


def test_the_fixed_packet_is_thirty_six_tasks(gold):
    assert len(build_packet(fixed_pilot_items(gold))) == 36


def test_the_time_estimate_reproduces_the_original_twenty_item_figure():
    """Calibration check: the 20-item plan was about four hours, and it still says so."""
    assert estimated_minutes_per_annotator(20) == 240
    twelve = estimated_minutes_per_annotator(12)
    assert 140 <= twelve <= 170
    # Onboarding is charged once, so halving the items does not halve the time.
    assert twelve > estimated_minutes_per_annotator(20) / 2


def test_selection_is_twenty_items_and_deterministic(gold):
    first = [i.id for i in select_pilot_items(gold)]
    second = [i.id for i in select_pilot_items(gold)]
    assert len(first) == 20
    assert first == second, "the pilot must not change between runs, or its kappa is unrepeatable"


def test_selection_covers_every_category_including_the_singleton(gold):
    chosen = select_pilot_items(gold)
    covered = {i.category for i in chosen}
    assert covered == {i.category for i in gold}, (
        "a proportional sample would drop the one-member category; the round-robin must not"
    )


def test_selection_carries_both_sides_of_the_refusal_split(gold):
    composition = pilot_composition(select_pilot_items(gold))
    assert composition["n_refusal"] >= 3
    assert composition["n_answerable"] >= 10


def test_a_different_salt_gives_a_different_pilot(gold):
    a = [i.id for i in select_pilot_items(gold, salt="pilot-v1")]
    b = [i.id for i in select_pilot_items(gold, salt="pilot-v2")]
    assert a != b


def test_asking_for_more_than_exists_returns_everything(gold):
    assert len(select_pilot_items(gold, n=500)) == len(gold)


def test_empty_or_nonsense_requests_are_refused(gold):
    with pytest.raises(PilotError):
        select_pilot_items([])
    with pytest.raises(PilotError):
        select_pilot_items(gold, n=0)


# ---------------------------------------------------------------------------
# The packet
# ---------------------------------------------------------------------------
def test_packet_is_every_item_under_every_arm(gold):
    chosen = select_pilot_items(gold)
    tasks = build_packet(chosen)
    assert len(tasks) == len(chosen) * len(ARMS)
    assert {t.arm for t in tasks} == set(ARMS)


def test_packet_finishes_one_arm_before_starting_the_next(gold):
    """Interleaving arms would measure memory rather than the rubric."""
    arms_in_order = [t.arm for t in build_packet(select_pilot_items(gold))]
    # Each arm appears as one unbroken run.
    runs = [arm for i, arm in enumerate(arms_in_order) if i == 0 or arms_in_order[i - 1] != arm]
    assert len(runs) == len(set(runs)) == len(ARMS)


def test_packet_uses_the_system_answer_when_one_is_supplied(gold):
    chosen = select_pilot_items(gold)[:2]
    supplied = {chosen[0].id: "a frozen system response"}
    tasks = {(t.item_id, t.arm): t for t in build_packet(chosen, answers=supplied)}
    assert tasks[(chosen[0].id, "anchored")].answer == "a frozen system response"
    # Without one, the gold answer stands in so the rubric still has real text to bite on.
    assert tasks[(chosen[1].id, "anchored")].answer == chosen[1].answer


def test_unknown_arms_are_refused(gold):
    with pytest.raises(PilotError, match="unknown pilot arm"):
        build_packet(select_pilot_items(gold)[:1], arms=("anchored", "vibes"))


def test_packet_round_trips_to_disk(gold, tmp_path):
    tasks = build_packet(select_pilot_items(gold)[:3])
    path = write_packet(tasks, str(tmp_path / "packet.json"))
    with open(path, encoding="utf-8") as handle:
        loaded = json.load(handle)
    assert len(loaded) == len(tasks)
    assert set(loaded[0]) == {
        "item_id", "arm", "question", "answer", "category", "should_refuse",
    }


# ---------------------------------------------------------------------------
# Scoring what comes back
# ---------------------------------------------------------------------------
def labels(arm, pairs, annotators=("ann_a", "ann_b"), seconds=None):
    """`pairs` is [(item_id, score_a, score_b), ...]."""
    out = []
    for item_id, score_a, score_b in pairs:
        for annotator, score in zip(annotators, (score_a, score_b)):
            out.append(PilotLabel(item_id, arm, annotator, score, seconds))
    return out


def test_perfect_agreement_scores_one():
    pairs = [(f"q{i:03d}", s, s) for i, s in enumerate([1, 2, 3, 4, 1, 2, 3, 4], start=1)]
    result = next(r for r in arm_results(labels("anchored", pairs)) if r.arm == "anchored")
    assert result.agreement == pytest.approx(1.0)
    assert result.n_items == 8


def test_disagreement_lowers_kappa():
    agree = [(f"q{i:03d}", s, s) for i, s in enumerate([1, 2, 3, 4] * 2, start=1)]
    differ = [(f"q{i:03d}", a, b) for i, (a, b) in enumerate(
        [(1, 4), (4, 1), (2, 3), (3, 2), (1, 3), (4, 2), (2, 4), (3, 1)], start=1
    )]
    high = next(r for r in arm_results(labels("anchored", agree)) if r.arm == "anchored")
    low = next(r for r in arm_results(labels("anchored", differ)) if r.arm == "anchored")
    assert low.agreement < high.agreement


def test_unscored_items_are_dropped_pairwise_and_counted_not_imputed():
    pairs = [("q001", 3, 3), ("q002", 4, None), ("q003", 2, 2), ("q004", None, None)]
    result = next(r for r in arm_results(labels("anchored", pairs)) if r.arm == "anchored")
    assert result.n_items == 2
    assert "2 item(s) not scored by both" in result.notes


def test_an_arm_needs_exactly_two_annotators_for_cohens_kappa():
    three = [
        PilotLabel("q001", "anchored", annotator, 3)
        for annotator in ("ann_a", "ann_b", "ann_c")
    ]
    result = next(r for r in arm_results(three) if r.arm == "anchored")
    assert result.agreement is None
    assert "exactly 2 annotators" in result.notes


def test_the_binary_arm_is_scored_unweighted():
    """Quadratic weights on two categories are meaningless; asking for them invites confusion."""
    pairs = [("q001", 1, 1), ("q002", 0, 0), ("q003", 1, 0), ("q004", 0, 1), ("q005", 1, 1)]
    result = next(r for r in arm_results(labels("checklist", pairs)) if r.arm == "checklist")
    assert result.agreement is not None


def test_time_per_item_is_carried_through():
    pairs = [("q001", 3, 3), ("q002", 2, 2)]
    result = next(
        r for r in arm_results(labels("anchored", pairs, seconds=45.0)) if r.arm == "anchored"
    )
    assert result.mean_seconds_per_item == pytest.approx(45.0)


# ---------------------------------------------------------------------------
# The acceptance check
# ---------------------------------------------------------------------------
def test_the_check_is_open_until_humans_have_annotated():
    """The pilot needing people is the expected state, not an error - and never a silent pass."""
    status = pilot_status([])
    assert status.passed is False
    assert status.winner is None
    assert "needs two people" in status.reason
    assert "OPEN" in status.summary()


def test_usable_agreement_passes_and_names_a_winner():
    pairs = [(f"q{i:03d}", s, s) for i, s in enumerate([1, 2, 3, 4] * 3, start=1)]
    status = pilot_status(labels("anchored", pairs))
    assert status.passed is True
    assert status.winner == "anchored"
    assert status.agreement >= USABLE_AGREEMENT
    assert "PASS" in status.summary()


def test_agreement_below_the_threshold_fails_and_says_rewrite_the_rubric():
    """Half the point of the pilot is being allowed to come back negative."""
    pairs = [
        ("q001", 1, 4), ("q002", 4, 1), ("q003", 2, 3), ("q004", 3, 2),
        ("q005", 1, 3), ("q006", 4, 2), ("q007", 2, 4), ("q008", 3, 1),
    ]
    status = pilot_status(labels("anchored", pairs))
    assert status.passed is False
    assert status.winner is None
    assert "rewrite the rubric" in status.reason


def test_all_three_arms_are_reported_not_just_the_winner():
    """The losing arms are a methods result worth publishing, not waste."""
    good = [(f"q{i:03d}", s, s) for i, s in enumerate([1, 2, 3, 4] * 3, start=1)]
    mixed = [(f"q{i:03d}", a, b) for i, (a, b) in enumerate(
        [(1, 1), (2, 2), (3, 4), (4, 3), (1, 2), (2, 1), (3, 3), (4, 4),
         (1, 1), (2, 2), (3, 3), (4, 4)], start=1
    )]
    status = pilot_status(labels("anchored", good) + labels("rollup", mixed))
    assert {arm["arm"] for arm in status.arms} == {"anchored", "rollup"}
