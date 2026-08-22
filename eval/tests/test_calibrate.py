"""Tests for L4 calibration.

Milestone 10's acceptance check is two things: the leakage test passes, and out-of-fold MAE is
reported with its fold spread. Both are tested directly, along with the failure this layer is
most likely to hide - a map that looks good because near-duplicate evidence sat on both sides of
the split.

Network-free.
"""

from __future__ import annotations

import random

import pytest

from eval.judge.calibrate import (
    USABLE_MAE_THRESHOLD,
    AffineMap,
    CalibrationError,
    LabelledPair,
    build_groups,
    calibrate,
    find_leakage,
    fit_affine,
    fit_isotonic,
    group_concentration,
    grouped_folds,
    identity_map,
    mean_absolute_error,
)


def pairs_from(spec, category="general_policy", pool="acquire"):
    return [
        LabelledPair(item_id=f"q{i:03d}", panel_mean=x, human_score=y,
                     category=category, pool=pool)
        for i, (x, y) in enumerate(spec)
    ]


def linear_pairs(n=60, noise=0.0, seed=0, offset=0.0, pool="acquire"):
    """Panel scores that map onto human scores with a known relationship."""
    rng = random.Random(seed)
    out = []
    for i in range(n):
        panel = 1.0 + 3.0 * (i % 10) / 9.0
        human = panel + offset + (rng.uniform(-noise, noise) if noise else 0.0)
        human = min(4.0, max(1.0, human))
        out.append(
            LabelledPair(
                item_id=f"q{i:03d}",
                panel_mean=panel,
                human_score=human,
                category=["general_policy", "numeric_extraction", "multi_hop"][i % 3],
                pool=pool,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Grouping: the leakage guard
# ---------------------------------------------------------------------------
def test_items_sharing_a_document_land_in_one_group():
    groups = build_groups({"q1": ["docA"], "q2": ["docA"], "q3": ["docB"]})
    assert groups["q1"] == groups["q2"]
    assert groups["q3"] != groups["q1"]


def test_grouping_is_transitive_through_a_chain():
    """q1-q2 share docA, q2-q3 share docB, so all three must travel together."""
    groups = build_groups({"q1": ["docA"], "q2": ["docA", "docB"], "q3": ["docB"]})
    assert groups["q1"] == groups["q2"] == groups["q3"]


def test_grouping_is_not_raw_document_id():
    """Invariant 5. An item retrieving several documents cannot be keyed by one of them."""
    groups = build_groups({"q1": ["docA", "docB"], "q2": ["docB", "docC"], "q3": ["docD"]})
    assert groups["q1"] == groups["q2"]
    assert groups["q3"] != groups["q1"]


def test_group_ids_are_stable_across_input_order():
    forward = build_groups({"q1": ["a"], "q2": ["a"], "q3": ["b"]})
    backward = build_groups({"q3": ["b"], "q2": ["a"], "q1": ["a"]})
    assert forward == backward


def test_an_item_with_no_documents_is_its_own_group():
    groups = build_groups({"q1": [], "q2": []})
    assert groups["q1"] != groups["q2"]


def test_empty_input_gives_no_groups():
    assert build_groups({}) == {}


def test_group_concentration_detects_one_giant_blob():
    """Near 1.0 means no honest grouped split exists, which is a finding to report."""
    blob = build_groups({f"q{i}": ["shared"] for i in range(10)})
    assert group_concentration(blob) == pytest.approx(1.0)


def test_group_concentration_is_low_when_groups_are_many():
    spread = build_groups({f"q{i}": [f"doc{i}"] for i in range(10)})
    assert group_concentration(spread) == pytest.approx(0.1)


# ---------------------------------------------------------------------------
# Folds and leakage
# ---------------------------------------------------------------------------
def test_no_group_spans_a_fold():
    """Milestone 10's acceptance check."""
    pairs = linear_pairs(60)
    groups = build_groups({p.item_id: [f"doc{i // 4}"] for i, p in enumerate(pairs)})
    folds = grouped_folds(pairs, groups, n_splits=5)
    assert find_leakage(pairs, groups, folds) == []


def test_the_leakage_detector_catches_a_deliberately_bad_split():
    """The detector must be able to fail, or it proves nothing."""
    pairs = linear_pairs(20)
    groups = {p.item_id: "one-big-group" for p in pairs}
    bad_folds = [([0, 1, 2, 3], [4, 5, 6, 7])]
    assert find_leakage(pairs, groups, bad_folds) == ["one-big-group"]


def test_folds_cover_every_pair_exactly_once_as_test():
    pairs = linear_pairs(60)
    groups = build_groups({p.item_id: [f"doc{i // 4}"] for i, p in enumerate(pairs)})
    folds = grouped_folds(pairs, groups, n_splits=5)
    seen = [index for _, test in folds for index in test]
    assert sorted(seen) == list(range(len(pairs)))


def test_too_few_groups_for_the_requested_folds_is_refused():
    """A random split would leak; falling back silently is the failure to avoid."""
    pairs = linear_pairs(20)
    groups = {p.item_id: "single" for p in pairs}
    with pytest.raises(CalibrationError, match="grouped cross-validation is impossible"):
        grouped_folds(pairs, groups, n_splits=5)


def test_too_few_pairs_for_the_requested_folds_is_refused():
    with pytest.raises(CalibrationError, match="cannot make"):
        grouped_folds(linear_pairs(3), {}, n_splits=5)


# ---------------------------------------------------------------------------
# The two maps
# ---------------------------------------------------------------------------
def test_affine_recovers_a_known_linear_relationship():
    fitted = fit_affine([1, 2, 3, 4], [2, 3, 4, 5])
    assert fitted.a == pytest.approx(1.0)
    assert fitted.b == pytest.approx(1.0)


def test_affine_predictions_are_clipped_to_the_scale():
    """A line can predict 4.7; a map onto a four-point scale cannot."""
    assert AffineMap(a=2.0, b=0.0).predict([0.1, 3.0]) == [1.0, 4.0]


def test_affine_on_a_constant_predictor_predicts_the_mean():
    """No variation in the input means nothing about the output can be attributed to it."""
    fitted = fit_affine([2.0, 2.0, 2.0], [1.0, 2.0, 3.0])
    assert fitted.a == 0.0
    assert fitted.b == pytest.approx(2.0)


def test_isotonic_is_monotone_increasing():
    fitted = fit_isotonic([1, 2, 3, 4, 5], [1, 3, 2, 4, 4])
    predictions = fitted.predict([1, 2, 3, 4, 5])
    assert predictions == sorted(predictions)


def test_isotonic_is_clipped_out_of_bounds():
    fitted = fit_isotonic([2, 3], [2, 3])
    assert 1.0 <= fitted.predict([-5])[0] <= 4.0
    assert 1.0 <= fitted.predict([99])[0] <= 4.0


def test_isotonic_support_points_expose_the_lookup_table_degeneracy():
    """Spec 0.5: on integer medians the flexible map has almost no resolution."""
    integer_medians = [1, 1, 2, 2, 3, 3, 4, 4]
    fitted = fit_isotonic(integer_medians, [1, 1, 2, 2, 3, 3, 4, 4])
    assert fitted.support_points <= 4


def test_fitting_nothing_is_refused():
    with pytest.raises(CalibrationError, match="no pairs"):
        fit_affine([], [])
    with pytest.raises(CalibrationError, match="no pairs"):
        fit_isotonic([], [])


def test_identity_map_clips_but_does_not_transform():
    assert identity_map([0.5, 2.5, 9.0]) == [1.0, 2.5, 4.0]


def test_mae_rejects_mismatched_lengths():
    with pytest.raises(CalibrationError, match="same length"):
        mean_absolute_error([1, 2], [1])


# ---------------------------------------------------------------------------
# Calibration end to end
# ---------------------------------------------------------------------------
def test_a_clean_offset_is_calibrated_away():
    """Judges scoring a consistent half-level high is exactly what calibration is for."""
    pairs = linear_pairs(60, offset=-0.5)
    groups = build_groups({p.item_id: [f"doc{i // 4}"] for i, p in enumerate(pairs)})
    result = calibrate(pairs, "grounding", groups)
    assert result.usable
    assert result.beats_doing_nothing
    assert result.chosen_mae < result.identity_mae


def test_out_of_fold_error_is_reported_with_its_fold_spread():
    """Milestone 10's second acceptance check."""
    pairs = linear_pairs(60, noise=0.4, seed=1)
    groups = build_groups({p.item_id: [f"doc{i // 4}"] for i, p in enumerate(pairs)})
    result = calibrate(pairs, "grounding", groups)
    assert result.n_folds == 5
    assert result.chosen_mae > 0
    assert result.chosen_mae_sd >= 0
    assert len(result.folds) == 5


def test_both_maps_are_always_fitted_and_compared():
    pairs = linear_pairs(60, noise=0.3, seed=2)
    groups = build_groups({p.item_id: [f"doc{i // 4}"] for i, p in enumerate(pairs)})
    result = calibrate(pairs, "grounding", groups)
    assert result.isotonic_mae > 0 and result.affine_mae > 0
    assert result.kind in ("isotonic", "affine")
    assert result.chosen_mae == min(result.isotonic_mae, result.affine_mae)


def noisy_linear(n, noise, seed=3):
    """A genuinely linear relationship, inside the scale, plus measurement noise."""
    rng = random.Random(seed)
    pairs = []
    for i in range(n):
        panel = 1.0 + 3.0 * rng.random()
        human = min(4.0, max(1.0, 0.8 * panel + 0.6 + rng.gauss(0, noise)))
        pairs.append(
            LabelledPair(
                item_id=f"q{i:03d}",
                panel_mean=panel,
                human_score=human,
                category=["general_policy", "numeric_extraction", "multi_hop"][i % 3],
            )
        )
    return pairs


def test_the_simple_map_wins_at_realistic_label_counts():
    """Spec 0.5's claim, and the reason the baseline is fitted every time.

    On a linear relationship with real noise and the label counts this project will actually
    have, the two-parameter map beats the flexible one, because isotonic spends its freedom
    fitting noise. Noiseless data would not show this - both fit exactly and the comparison is
    decided by floating-point dust.
    """
    pairs = noisy_linear(n=40, noise=0.5)
    groups = build_groups({p.item_id: [f"doc{i // 4}"] for i, p in enumerate(pairs)})
    result = calibrate(pairs, "grounding", groups)
    assert result.simple_map_won
    assert result.affine_mae < result.isotonic_mae
    assert "affine" in result.verdict


def test_the_flexible_map_catches_up_once_there_is_enough_data():
    """The other half of the trade-off, so the selection is not just a thumb on the scale.

    At three times the labels, isotonic's extra freedom is justified by the data and it closes
    the gap. Which map wins is a property of the sample size, not a fixed preference.
    """
    small = calibrate(
        noisy_linear(40, 0.5),
        "grounding",
        build_groups({f"q{i:03d}": [f"doc{i // 4}"] for i in range(40)}),
    )
    large = calibrate(
        noisy_linear(120, 0.5),
        "grounding",
        build_groups({f"q{i:03d}": [f"doc{i // 4}"] for i in range(120)}),
    )
    small_gap = small.isotonic_mae - small.affine_mae
    large_gap = large.isotonic_mae - large.affine_mae
    assert large_gap < small_gap


def test_isotonic_wins_where_the_relationship_bends():
    """The other side of the comparison, so the selection is doing real work.

    A constant offset clipped at the scale floor is exactly such a bend, and it is a realistic
    one: judges compressed toward the middle produce it.
    """
    pairs = linear_pairs(60, offset=-0.5)
    groups = build_groups({p.item_id: [f"doc{i // 4}"] for i, p in enumerate(pairs)})
    result = calibrate(pairs, "grounding", groups)
    assert result.kind == "isotonic"
    assert result.isotonic_mae < result.affine_mae


def test_an_uncalibratable_judge_is_reported_as_such():
    """A finding about the judge, not a configuration to tune until it passes."""
    rng = random.Random(7)
    pairs = [
        LabelledPair(
            item_id=f"q{i:03d}",
            panel_mean=rng.uniform(1, 4),
            human_score=rng.uniform(1, 4),  # no relationship at all
            category=["general_policy", "multi_hop", "numeric_extraction"][i % 3],
        )
        for i in range(60)
    ]
    groups = build_groups({p.item_id: [f"doc{i // 4}"] for i, p in enumerate(pairs)})
    result = calibrate(pairs, "grounding", groups)
    assert result.usable is False
    assert result.chosen_mae > USABLE_MAE_THRESHOLD
    assert "not calibratable at useful resolution" in result.verdict


def test_calibration_that_does_not_beat_the_raw_score_says_so():
    pairs = linear_pairs(60)  # human == panel already
    groups = build_groups({p.item_id: [f"doc{i // 4}"] for i, p in enumerate(pairs)})
    result = calibrate(pairs, "grounding", groups)
    assert result.identity_mae == pytest.approx(0.0, abs=1e-9)
    assert result.beats_doing_nothing is False
    assert "does not improve" in result.verdict


# ---------------------------------------------------------------------------
# The probe / acquire split
# ---------------------------------------------------------------------------
def test_probe_pairs_are_never_trained_on():
    """Spec 0.3: fitting on the probe pool destroys the only unbiased error estimate."""
    acquire = linear_pairs(60, offset=-0.5, pool="acquire")
    probe = [
        LabelledPair(f"p{i:03d}", 2.0, 4.0, "general_policy", pool="probe") for i in range(10)
    ]
    groups = build_groups(
        {p.item_id: [f"doc{i // 4}"] for i, p in enumerate(acquire + probe)}
    )
    result = calibrate(acquire + probe, "grounding", groups)
    assert result.n_pairs == 60  # probe pairs excluded from fitting
    assert result.probe_mae is not None
    # The probe pairs are deliberately mismatched, so their error is large despite a good fit.
    assert result.probe_mae > result.chosen_mae


def test_probe_error_is_reported_separately():
    acquire = linear_pairs(60, offset=-0.5, pool="acquire")
    probe = [
        LabelledPair(f"p{i:03d}", p.panel_mean, p.human_score, p.category, pool="probe")
        for i, p in enumerate(linear_pairs(12, offset=-0.5, seed=9))
    ]
    groups = build_groups(
        {p.item_id: [f"doc{i // 4}"] for i, p in enumerate(acquire + probe)}
    )
    result = calibrate(acquire + probe, "grounding", groups)
    assert result.probe_mae is not None
    assert result.to_dict()["probe_mae"] == result.probe_mae


def test_calibrating_on_probe_only_is_refused():
    probe = linear_pairs(30, pool="probe")
    with pytest.raises(CalibrationError, match="probe pool is for reporting only"):
        calibrate(probe, "grounding")


def test_an_unknown_pool_is_rejected():
    with pytest.raises(CalibrationError, match="pool must be"):
        LabelledPair("q1", 2.0, 3.0, "general_policy", pool="whatever")


def test_calibrating_nothing_is_refused():
    with pytest.raises(CalibrationError, match="no labelled pairs"):
        calibrate([], "grounding")


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------
def test_the_result_becomes_a_schema_object():
    pairs = linear_pairs(60, offset=-0.5)
    groups = build_groups({p.item_id: [f"doc{i // 4}"] for i, p in enumerate(pairs)})
    calibration_map = calibrate(pairs, "grounding", groups).to_map()
    assert calibration_map.dimension == "grounding"
    assert calibration_map.usable is True
    assert calibration_map.calibration_map_id


def test_an_unusable_result_cannot_claim_usability_in_the_schema():
    """The schema guard and the calibration verdict must agree."""
    rng = random.Random(11)
    pairs = [
        LabelledPair(f"q{i:03d}", rng.uniform(1, 4), rng.uniform(1, 4),
                     ["general_policy", "multi_hop", "numeric_extraction"][i % 3])
        for i in range(60)
    ]
    groups = build_groups({p.item_id: [f"doc{i // 4}"] for i, p in enumerate(pairs)})
    result = calibrate(pairs, "grounding", groups)
    assert result.to_map().usable is False


def test_the_result_reports_group_concentration():
    pairs = linear_pairs(60)
    groups = build_groups({p.item_id: [f"doc{i // 4}"] for i, p in enumerate(pairs)})
    assert calibrate(pairs, "grounding", groups).group_concentration < 0.5
