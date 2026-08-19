"""Tests for the milestone-1 judge replication experiment.

No network, no key, no database (invariant 3). The Wilson implementation is
golden-tested against statsmodels, which is an independent published
implementation, as well as against hand-checked literature values - the
convention in CLAUDE.md is that new metric code needs a golden test against a
published worked example before it is used.
"""

from __future__ import annotations

import asyncio
import math

import pytest

from eval.experiments.load_judge import load_refusal_judge
from eval.judge.clients.base import CallLedger, CallRecorder, FakeClient
from eval.judge.replication import (
    Z_95,
    Verdict,
    clustered_bootstrap_interval,
    summarise,
    wilson_interval,
)


# ---------------------------------------------------------------------------
# Wilson: golden tests
# ---------------------------------------------------------------------------
def test_z_constant_matches_scipy():
    scipy_stats = pytest.importorskip("scipy.stats")
    assert Z_95 == pytest.approx(scipy_stats.norm.ppf(0.975), abs=1e-12)


@pytest.mark.parametrize(
    "successes,trials",
    [(0, 12), (1, 12), (5, 12), (7, 12), (12, 12), (2, 20), (150, 300), (183, 300), (1, 1)],
)
def test_wilson_matches_statsmodels(successes, trials):
    """Independent implementation check against statsmodels."""
    proportion = pytest.importorskip("statsmodels.stats.proportion")
    expected_lo, expected_hi = proportion.proportion_confint(
        successes, trials, alpha=0.05, method="wilson"
    )
    lo, hi = wilson_interval(successes, trials)
    assert lo == pytest.approx(expected_lo, abs=1e-10)
    assert hi == pytest.approx(expected_hi, abs=1e-10)


def test_wilson_published_worked_example():
    """Brown, Cai & DasGupta (2001), n=20, X=2: Wilson 95% is about (0.028, 0.301).

    Hard-coded from the literature rather than recomputed, so this test still
    fails if both this module and statsmodels were somehow wrong together.
    """
    lo, hi = wilson_interval(2, 20)
    assert lo == pytest.approx(0.0278, abs=5e-4)
    assert hi == pytest.approx(0.3010, abs=5e-4)


def test_wilson_does_not_collapse_at_the_boundary():
    """The reason Wilson is used instead of Wald.

    At 12/12 the Wald interval has zero width and claims certainty. Wilson
    keeps a lower bound strictly inside the unit interval, which matters
    because a perfectly stable judge on 12 items is exactly the outcome this
    experiment might produce.
    """
    lo, hi = wilson_interval(12, 12)
    assert hi == pytest.approx(1.0)
    assert 0.0 < lo < 1.0
    assert lo == pytest.approx(0.7573, abs=5e-4)


def test_wilson_is_symmetric_under_complement():
    lo, hi = wilson_interval(5, 12)
    lo_complement, hi_complement = wilson_interval(7, 12)
    assert lo == pytest.approx(1.0 - hi_complement, abs=1e-12)
    assert hi == pytest.approx(1.0 - lo_complement, abs=1e-12)


def test_wilson_zero_trials_is_uninformative():
    assert wilson_interval(0, 0) == (0.0, 1.0)


@pytest.mark.parametrize("successes,trials", [(-1, 10), (11, 10), (0, -1)])
def test_wilson_rejects_impossible_counts(successes, trials):
    with pytest.raises(ValueError):
        wilson_interval(successes, trials)


def test_wilson_narrows_as_trials_grow():
    widths = [
        wilson_interval(round(0.5 * n), n)[1] - wilson_interval(round(0.5 * n), n)[0]
        for n in (12, 60, 300, 3000)
    ]
    assert widths == sorted(widths, reverse=True)


# ---------------------------------------------------------------------------
# Clustered bootstrap
# ---------------------------------------------------------------------------
def test_bootstrap_is_deterministic_given_a_seed():
    counts = [25, 25, 0, 0, 12, 25, 0, 3, 25, 0, 25, 11]
    first = clustered_bootstrap_interval(counts, replicates=25, n_boot=500, seed=7)
    second = clustered_bootstrap_interval(counts, replicates=25, n_boot=500, seed=7)
    assert first == second


def test_bootstrap_differs_with_a_different_seed():
    counts = [25, 25, 0, 0, 12, 25, 0, 3, 25, 0, 25, 11]
    assert clustered_bootstrap_interval(counts, 25, n_boot=500, seed=1) != (
        clustered_bootstrap_interval(counts, 25, n_boot=500, seed=2)
    )


def test_bootstrap_is_degenerate_when_all_items_agree():
    """Every item at the same rate leaves nothing to resample."""
    lo, hi = clustered_bootstrap_interval([25] * 12, replicates=25, n_boot=500, seed=0)
    assert lo == pytest.approx(1.0)
    assert hi == pytest.approx(1.0)


def test_bootstrap_is_wider_than_wilson_under_clustering():
    """The whole reason both intervals are reported.

    Five items always refused, seven never: an enormous between-item spread
    with zero within-item variance. Wilson sees 125 successes in 300 iid trials
    and reports a tight interval. The clustered interval sees twelve items and
    is honest about how little is known about the next question.
    """
    per_item = [25] * 5 + [0] * 7
    wilson_lo, wilson_hi = wilson_interval(sum(per_item), 25 * 12)
    boot_lo, boot_hi = clustered_bootstrap_interval(per_item, 25, n_boot=2000, seed=0)
    assert (boot_hi - boot_lo) > 3 * (wilson_hi - wilson_lo)


def test_bootstrap_rejects_zero_replicates():
    with pytest.raises(ValueError):
        clustered_bootstrap_interval([1, 2], replicates=0)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
def _verdicts(pattern):
    """pattern[run][item] -> bool refused."""
    return [
        Verdict(run_index=r, question_id=f"q{i:03d}", refused=refused)
        for r, row in enumerate(pattern)
        for i, refused in enumerate(row)
    ]


def test_summary_counts_and_spread():
    pattern = [[True, True, False], [True, False, False], [True, True, False]]
    summary = summarise(_verdicts(pattern), ["q000", "q001", "q002"], n_boot=200)
    assert summary.n_replicates == 3
    assert summary.run_counts == [2, 1, 2]
    assert summary.count_min == 1 and summary.count_max == 2
    assert summary.pooled_refusals == 5 and summary.pooled_trials == 9
    assert summary.swing_points == pytest.approx(100.0 / 3)


def test_summary_identifies_the_single_unstable_item():
    """Spec 0.7's actual question, in code."""
    pattern = [[True] * 5 + [False] * 6 + [True]] + [[True] * 5 + [False] * 6 + [False]] * 24
    ids = [f"q{i:03d}" for i in range(12)]
    summary = summarise(_verdicts(pattern), ids, n_boot=200)
    assert summary.unstable_items == ["q011"]
    assert summary.is_single_item_swing is True
    assert summary.per_item_rates["q000"] == 1.0
    assert summary.per_item_rates["q005"] == 0.0
    assert summary.per_item_rates["q011"] == pytest.approx(1 / 25)


def test_summary_reports_diffuse_instability_as_not_single_item():
    pattern = [[r % 2 == 0, r % 3 == 0, True] for r in range(6)]
    summary = summarise(_verdicts(pattern), ["q000", "q001", "q002"], n_boot=200)
    assert len(summary.unstable_items) == 2
    assert summary.is_single_item_swing is False


def test_summary_reports_no_swing_when_perfectly_stable():
    pattern = [[True, False, True]] * 10
    summary = summarise(_verdicts(pattern), ["q000", "q001", "q002"], n_boot=200)
    assert summary.unstable_items == []
    assert summary.count_sd == 0.0
    assert summary.swing_points == 0.0


def test_excluded_runs_are_dropped_whole():
    """A contaminated replicate must not contribute any verdicts.

    Half a replicate judged by the model and half by the keyword fallback is a
    mixture of two instruments, not a sample of one.
    """
    pattern = [[True, True], [False, False], [True, False]]
    summary = summarise(_verdicts(pattern), ["q000", "q001"], excluded_runs=[1], n_boot=200)
    assert summary.n_replicates == 2
    assert summary.pooled_trials == 4
    assert summary.run_counts == [2, 1]
    assert summary.excluded_runs == [1]


def test_summary_sd_is_the_sample_sd():
    pattern = [[True, True], [False, False], [True, False], [True, False]]
    summary = summarise(_verdicts(pattern), ["q000", "q001"], n_boot=200)
    counts = summary.run_counts
    mean = sum(counts) / len(counts)
    expected = math.sqrt(sum((c - mean) ** 2 for c in counts) / (len(counts) - 1))
    assert summary.count_sd == pytest.approx(expected)


def test_all_replicates_excluded_raises_rather_than_returning_zeros():
    pattern = [[True, False], [False, True]]
    with pytest.raises(ValueError, match="No usable replicates"):
        summarise(_verdicts(pattern), ["q000", "q001"], excluded_runs=[0, 1], n_boot=200)


def test_exclusion_fraction_is_reported():
    pattern = [[True, True], [False, False], [True, False], [True, True]]
    summary = summarise(_verdicts(pattern), ["q000", "q001"], excluded_runs=[1], n_boot=200)
    assert summary.attempted_replicates == 4
    assert summary.excluded_fraction == pytest.approx(0.25)


def test_every_per_item_rate_carries_an_interval():
    """Invariant 7: no bare point estimates."""
    pattern = [[True, False, True]] * 5
    summary = summarise(_verdicts(pattern), ["q000", "q001", "q002"], n_boot=200)
    intervals = summary.per_item_intervals
    assert set(intervals) == set(summary.per_item_rates)
    for qid, rate in summary.per_item_rates.items():
        lo, hi = intervals[qid]
        assert lo <= rate <= hi
        assert hi > lo  # never a zero-width claim of certainty


def test_mean_count_carries_an_interval_on_the_count_scale():
    pattern = [[True, False, True]] * 5
    summary = summarise(_verdicts(pattern), ["q000", "q001", "q002"], n_boot=200)
    lo, hi = summary.count_mean_interval
    assert lo == pytest.approx(summary.boot_lo * 3)
    assert hi == pytest.approx(summary.boot_hi * 3)


def test_noncanonical_rate_is_tracked():
    pattern = [[True, False]] * 5
    summary = summarise(
        _verdicts(pattern), ["q000", "q001"], n_boot=200, noncanonical_replies=2
    )
    assert summary.pooled_trials == 10
    assert summary.noncanonical_rate == pytest.approx(0.2)


def test_summary_serialises_with_both_intervals():
    pattern = [[True, False]] * 4
    payload = summarise(_verdicts(pattern), ["q000", "q001"], n_boot=200).to_dict()
    assert "wilson_95" in payload and "clustered_bootstrap_95" in payload
    assert payload["wilson_assumes_iid_trials"] is True
    assert payload["bootstrap_seed"] == 0


# ---------------------------------------------------------------------------
# Client boundary
# ---------------------------------------------------------------------------
def test_fake_client_fixed_verdict():
    client = FakeClient(fixed="ANSWERED")
    response = client.client.chat.completions.create(
        model="x", messages=[{"role": "user", "content": "anything"}]
    )
    assert response.choices[0].message.content == "ANSWERED"


def test_fake_client_rejects_an_invalid_fixed_verdict():
    with pytest.raises(ValueError):
        FakeClient(fixed="MAYBE")


def test_fake_client_is_reproducible_by_seed():
    def draw(seed):
        client = FakeClient(item_refusal_prob={"Q": 0.5}, seed=seed)
        return [
            client.client.chat.completions.create(
                model="x", messages=[{"role": "user", "content": "Q"}]
            ).choices[0].message.content
            for _ in range(30)
        ]

    assert draw(3) == draw(3)
    assert draw(3) != draw(4)


def test_fake_client_matches_probability_by_item():
    client = FakeClient(item_refusal_prob={"alpha": 1.0, "beta": 0.0}, seed=0)

    def verdict(text):
        return client.client.chat.completions.create(
            model="x", messages=[{"role": "user", "content": text}]
        ).choices[0].message.content

    assert {verdict("about alpha here") for _ in range(20)} == {"REFUSED"}
    assert {verdict("about beta here") for _ in range(20)} == {"ANSWERED"}


def test_call_recorder_counts_attempts_and_tokens():
    recorder = CallRecorder(FakeClient(fixed="REFUSED", prompt_tokens=100, completion_tokens=2))
    for _ in range(3):
        recorder.client.chat.completions.create(
            model="x", messages=[{"role": "user", "content": "q"}]
        )
    assert recorder.ledger.attempts == 3
    assert recorder.ledger.prompt_tokens == 300
    assert recorder.ledger.completion_tokens == 6
    assert recorder.ledger.contaminated is False


def test_call_recorder_records_and_reraises():
    """Errors must propagate unchanged, or the judge takes a different path."""
    recorder = CallRecorder(FakeClient(fixed="REFUSED", fail_on_call=lambda n: True))
    with pytest.raises(RuntimeError):
        recorder.client.chat.completions.create(
            model="x", messages=[{"role": "user", "content": "q"}]
        )
    assert recorder.ledger.errors == 1
    assert recorder.ledger.contaminated is True


def test_ledger_captures_raw_reply_text():
    recorder = CallRecorder(FakeClient(fixed="REFUSED"))
    recorder.client.chat.completions.create(
        model="x", messages=[{"role": "user", "content": "q"}]
    )
    assert recorder.ledger.contents == ["REFUSED"]
    assert recorder.ledger.noncanonical == []


def test_ledger_flags_a_reply_the_judge_would_silently_treat_as_a_refusal():
    """A hedged reply contains neither canonical token.

    ``judge_hallucination`` tests ``"ANSWERED" in verdict``, so this is scored
    as REFUSED. That is a parsing artefact, not a judgement, and it has to be
    visible in the artifact.
    """
    recorder = CallRecorder(FakeClient(fixed="REFUSED"))
    recorder.ledger.contents.append("I cannot determine")
    assert recorder.ledger.noncanonical == ["I cannot determine"]
    assert recorder.ledger.to_dict()["noncanonical_replies"] == 1


def test_ledger_treats_case_and_whitespace_as_canonical():
    ledger = CallLedger(contents=["  refused\n", "ANSWERED"])
    assert ledger.noncanonical == []


def test_ledger_snapshot_is_independent():
    ledger = CallLedger(attempts=2, errors=1)
    snapshot = ledger.snapshot()
    ledger.reset()
    assert snapshot.attempts == 2 and snapshot.errors == 1
    assert ledger.attempts == 0


# ---------------------------------------------------------------------------
# The judge itself, unmodified
# ---------------------------------------------------------------------------
def test_loader_returns_the_real_judge():
    judge, digest = load_refusal_judge()
    assert judge.__name__ == "judge_hallucination"
    assert judge.__module__ == "eval.generation_metrics"
    assert len(digest) == 16
    again, digest_again = load_refusal_judge()
    assert digest == digest_again


def test_judge_reports_refusal_through_an_injected_client():
    judge, _ = load_refusal_judge()
    recorder = CallRecorder(FakeClient(fixed="REFUSED"))
    hallucinated, usage = asyncio.run(judge("Who wins the election?", "I only cover water.", recorder))
    assert hallucinated is False
    assert usage["prompt_tokens"] > 0
    assert recorder.ledger.attempts == 1


def test_judge_reports_answering_through_an_injected_client():
    judge, _ = load_refusal_judge()
    recorder = CallRecorder(FakeClient(fixed="ANSWERED"))
    hallucinated, _ = asyncio.run(judge("Who wins the election?", "Candidate X will win.", recorder))
    assert hallucinated is True


def test_provider_failure_is_invisible_in_the_verdict_but_visible_in_the_ledger():
    """The reason CallRecorder exists.

    On an API error the judge silently falls back to a deterministic keyword
    check and still returns a verdict. Nothing in the return value says so. If
    a quota failure went unnoticed, the experiment would report a perfectly
    stable judge and reach exactly the wrong conclusion.
    """
    judge, _ = load_refusal_judge()
    recorder = CallRecorder(FakeClient(fixed="REFUSED", fail_on_call=lambda n: True))
    refusal_text = "I focus on water-related information in Arizona."

    hallucinated, usage = asyncio.run(judge("Who wins?", refusal_text, recorder))

    # The verdict looks completely normal...
    assert hallucinated is False
    assert usage == {}
    # ...and only the ledger reveals no model was consulted.
    assert recorder.ledger.errors == 1
    assert recorder.ledger.contaminated is True
