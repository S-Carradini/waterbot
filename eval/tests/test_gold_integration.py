"""M13 acceptance: the real gold set drives the real pipeline.

`test_system.py` proves the layers fit each other. It does so on six synthetic items whose
categories are scoring classes, because that is what `benchmark_dataset.json` looks like. This
file proves the layers fit *the actual input*, whose categories are topics and whose scoring
class lives in its own column.

That difference is not cosmetic. Before this milestone, three modules decided "should this
question have been declined?" by comparing `category` against `"out_of_scope_negative"`. Run the
real gold set through that and all thirty items land in `answerable`: the five refusal items get
scored as though they should have been answered, abstention recall is computed over an empty
denominator, and the report renders without complaint. Nothing raises. The number is just wrong
in the direction that flatters the system.

So the acceptance check here is not "the pipeline runs". It is "the five refusal items are
counted as refusals", and it fails loudly against the old behaviour.

Network-free and database-free. The corpus is synthesised from the gold set's own quotes, which
tests the wiring; whether the *real* corpus contains those quotes is a separate question that
`eval/gold_set.py`'s validator answers.
"""

from __future__ import annotations

import os

import pytest

from eval.gold_set import GoldItem, load_gold_set
from eval.judge.aggregate import aggregate_all
from eval.judge.calibrate import build_groups
from eval.judge.clients.fake import FakeJudgeClient
from eval.judge.evidence import build_canonical_map, snapshot_from_mapping
from eval.judge.freeze import EchoGenerator, freeze_run
from eval.judge.gold import (
    GoldIntegrationError,
    benchmark_items,
    category_of,
    item_documents,
    reference_answers,
    refusal_labels,
    unsupported_items,
)
from eval.judge.panel import Budget
from eval.judge.refusal import refusal_report
from eval.judge.retrieval import Chunk, ExactRetriever, HashingEmbedder
from eval.judge.rubric import load_rubric
from eval.judge.schemas import MeasurementVersion
from eval.judge.store import ResponseStore

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GOLD_PATH = os.path.join(REPO_ROOT, "gold_set.json")

pytestmark = pytest.mark.skipif(
    not os.path.exists(GOLD_PATH), reason="gold_set.json not present in the repo root"
)


@pytest.fixture(scope="module")
def gold():
    return load_gold_set(GOLD_PATH)


@pytest.fixture(scope="module")
def rubric():
    return load_rubric()


@pytest.fixture(scope="module")
def documents(gold):
    """One synthetic document per answerable item, carrying that item's quotes verbatim.

    Deliberately one document per item rather than one shared document: it gives `build_groups`
    something with real structure to find, instead of collapsing every item into one component.
    """
    return {
        f"{item.id}_source.pdf": " ".join(item.source_quote)
        for item in gold
        if item.source_quote
    }


# ---------------------------------------------------------------------------
# The gold set as given
# ---------------------------------------------------------------------------
def test_the_gold_set_loads_and_is_the_shape_the_pipeline_expects(gold):
    assert len(gold) == 30
    assert all(isinstance(item, GoldItem) for item in gold)
    assert {item.id for item in gold} == {f"q{n:03d}" for n in range(1, 31)}
    # Five columns plus id, and nothing else. If this fails the gold set changed shape and the
    # adapter needs revisiting before anything it produces is trusted.
    assert set(gold[0].to_dict()) == {
        "id", "question", "answer", "source_quote", "should_refuse", "category",
    }


def test_the_refusal_split_is_five_and_twenty_five(gold):
    labels = refusal_labels(gold)
    assert sum(labels.values()) == 5
    assert len(labels) - sum(labels.values()) == 25


def test_categories_are_topics_not_scoring_classes(gold):
    """The premise of this whole file. If categories ever become scoring classes, revisit."""
    assert "out_of_scope_negative" not in set(category_of(gold).values())


# ---------------------------------------------------------------------------
# L1: freezing
# ---------------------------------------------------------------------------
def test_benchmark_items_carry_should_refuse_through_to_responses(gold, tmp_path, documents):
    items = benchmark_items(gold)
    assert len(items) == 30
    assert sum(1 for i in items if i.should_refuse) == 5

    responses = _freeze(gold, tmp_path, documents)
    assert len(responses) == 30
    # The flag survived the freeze, the pydantic round-trip and the read back off disk.
    assert sum(1 for r in responses if r.should_refuse) == 5
    assert sum(1 for r in responses if r.is_negative) == 5


def test_an_empty_gold_set_is_refused_rather_than_frozen():
    with pytest.raises(GoldIntegrationError):
        benchmark_items([])


def test_duplicate_ids_are_refused(gold):
    with pytest.raises(GoldIntegrationError, match="duplicate gold id"):
        benchmark_items([gold[0], gold[0]])


# ---------------------------------------------------------------------------
# THE ACCEPTANCE CHECK
# ---------------------------------------------------------------------------
def test_the_five_refusal_items_are_scored_as_refusals_not_as_answers(
    gold, tmp_path, documents, rubric
):
    """M13's acceptance check, and the regression guard for the bug it fixed.

    Splitting on `category` alone puts all thirty items in `answerable`, so `n_negatives` is 0
    and abstention recall has no denominator. The assertion below is exactly what distinguishes
    the two behaviours.
    """
    responses = _freeze(gold, tmp_path, documents)
    verdicts = _judge(responses, rubric, tmp_path)

    report = refusal_report(verdicts, responses)

    assert report.n_negatives == 5, (
        "the five should_refuse items were not recognised as negatives - refusal scoring is "
        "running in the wrong direction"
    )
    assert report.n_answerable == 25
    # Both denominators are non-empty, so both halves of the paired report mean something.
    assert report.n_negatives_scored > 0
    assert report.n_answerable_scored > 0


def test_the_rubric_applies_refusal_dimensions_by_the_flag_not_the_topic(gold, rubric):
    """A refusal item must not be scored on answerable-only dimensions, and vice versa."""
    negative = next(i for i in gold if i.should_refuse)
    answerable = next(i for i in gold if not i.should_refuse)

    on_negative = set(rubric.applicable_names(negative.category, is_negative=True))
    on_answerable = set(rubric.applicable_names(answerable.category, is_negative=False))

    # Same topic-shaped category strings, different dimension sets - which is only possible
    # because the flag is what decides.
    assert on_negative != on_answerable
    # Answerable items are scored on strictly more dimensions: grounding and citation validity
    # have nothing to bite on when the right answer is to decline.
    assert on_negative < on_answerable


# ---------------------------------------------------------------------------
# L4: grouping (invariant 5)
# ---------------------------------------------------------------------------
def test_item_documents_resolves_quotes_to_documents(gold, documents):
    resolved = item_documents(gold, documents)
    assert set(resolved) == {item.id for item in gold}
    answerable_with_quotes = [i for i in gold if i.source_quote]
    assert any(resolved[i.id] for i in answerable_with_quotes)


def test_refusal_items_are_partial_refusals_and_do_carry_evidence(gold, documents):
    """All five refusal items cite a quote, and that is correct, not a defect.

    A blank refusal would cite nothing. These decline the unanswerable half and then ground a
    correct general fact - q009 refuses the address lookup, then states that Holbrook is outside
    any AMA so the applicable program is "adequate" rather than "assured", and quotes the source
    for it.

    The consequence for L4: refusal items must be allowed to share a fold group with answerable
    items, because they can genuinely share a document. Grouping them off on their own would
    split evidence that is actually shared and quietly defeat invariant 5.
    """
    resolved = item_documents(gold, documents)
    for item in gold:
        if item.should_refuse:
            assert item.source_quote, f"{item.id} is a refusal item with no quote"
            assert resolved[item.id], f"{item.id} cites a quote that resolved nowhere"

    groups = build_groups(resolved)
    assert groups, "grouping produced nothing"
    assert set(groups) == {item.id for item in gold}
    # A refusal item lands in a real group like anything else.
    assert all(groups[i.id] for i in gold if i.should_refuse)


def test_grouping_follows_canonical_identity_not_filenames(gold):
    """Two names holding the same text are one piece of evidence, so their items must group.

    This is invariant 5's real failure mode. 127 corpus names share content with another name;
    grouping on raw filenames calls those items independent and lets evidence leak across
    calibration folds, which returns an optimistic number rather than an error.
    """
    quoted = [i for i in gold if i.source_quote][:2]
    shared_text = " ".join(quoted[0].source_quote)
    # Same bytes under two names, one cited by each item.
    docs = {"original.pdf": shared_text, "duplicate_upload.pdf": shared_text}
    corpus = snapshot_from_mapping({name: [text] for name, text in docs.items()})
    canonical_map = build_canonical_map(corpus)

    raw = item_documents(quoted, docs)
    canonical = item_documents(quoted, docs, canonical_map)

    assert raw[quoted[0].id] == ["duplicate_upload.pdf", "original.pdf"]
    # Through the canonical map the two names collapse to one id.
    assert len(canonical[quoted[0].id]) == 1


def test_unsupported_items_reports_rather_than_raises(gold):
    """A quote the corpus cannot find is a finding, not a crash."""
    missing = unsupported_items(gold, {"unrelated.pdf": "nothing relevant here"})
    quoted = [i.id for i in gold if i.source_quote]
    assert missing == sorted(quoted)
    # And nothing is reported once the real sources are present.
    documents = {f"{i.id}.pdf": " ".join(i.source_quote) for i in gold if i.source_quote}
    assert unsupported_items(gold, documents) == []


# ---------------------------------------------------------------------------
# L2/L5 inputs
# ---------------------------------------------------------------------------
def test_reference_answers_cover_every_item(gold):
    references = reference_answers(gold)
    assert set(references) == {item.id for item in gold}
    assert all(text.strip() for text in references.values())


# ---------------------------------------------------------------------------
# Full chain on the real input
# ---------------------------------------------------------------------------
def test_the_real_gold_set_runs_the_whole_pipeline(gold, tmp_path, documents, rubric):
    responses = _freeze(gold, tmp_path, documents)
    verdicts = _judge(responses, rubric, tmp_path)
    aggregates = aggregate_all(verdicts, expected_votes=2 * 2, n_boot=100)

    assert aggregates
    scored = [a for a in aggregates if a.mean is not None]
    assert scored, "no aggregate carried a score"

    # Every judged response traces back to a gold id.
    judged = {v.response_id.split("::")[0] for v in verdicts}
    assert judged <= {item.id for item in gold}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _version(fingerprint="f" * 16):
    return MeasurementVersion(
        corpus_fingerprint=fingerprint,
        rubric_hash="r" * 16,
        prompt_hash="p" * 16,
        judge_set=("judge-a", "judge-b"),
        aggregation_version="1.0.0",
        k=2,
        temperature=0.3,
    )


def _freeze(gold, tmp_path, documents):
    embedder = HashingEmbedder(dimension=48)
    chunks = [
        Chunk(f"chunk_{i:03d}", name, text, tuple(embedder.embed(text)))
        for i, (name, text) in enumerate(sorted(documents.items()))
    ]
    retriever = ExactRetriever(chunks, embedder)

    version = _version()
    store = ResponseStore(version.corpus_fingerprint, "gold-run", runs_dir=str(tmp_path))
    freeze_run(
        store, benchmark_items(gold), retriever, EchoGenerator("blue"), "waterbot", "blue",
        dataset_version="gold-1.0.0", measurement_version=version, k=3,
    )
    return store.load_responses(expected_fingerprint=version.corpus_fingerprint)


def _judge(responses, rubric, tmp_path):
    from eval.judge.panel import PanelRunner, Pricing

    runner = PanelRunner(
        clients=[FakeJudgeClient("judge-a", seed=1), FakeJudgeClient("judge-b", seed=2)],
        rubric=rubric,
        rubric_hash="r" * 16,
        corpus_fingerprint="f" * 16,
        pricing={"judge-a": Pricing(0.002, 0.008), "judge-b": Pricing(0.002, 0.008)},
        budget=Budget(cap_usd=50.0),
        samples=2,
        allow_unpiloted_rubric=True,
    )
    return runner.judge_all(responses)
