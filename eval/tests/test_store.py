"""Tests for the frozen response store and the freeze path (L1).

Milestone 4's acceptance check is one property: two freezes of the same corpus produce
byte-identical response files. It is tested directly, and so are the guarantees that make the
store safe to build on - write-once responses, append-only verdicts, and a corpus fingerprint
that is checked rather than assumed.

Network-free and database-free.
"""

from __future__ import annotations

import hashlib
import json
import os

import pytest

from eval.judge.freeze import (
    BenchmarkItem,
    EchoGenerator,
    Generation,
    build_manifest,
    freeze_responses,
    freeze_run,
    items_from_dataset,
    make_run_id,
)
from eval.judge.retrieval import Chunk, ExactRetriever, HashingEmbedder
from eval.judge.schemas import (
    DimensionVerdict,
    MeasurementVersion,
    Response,
    RunManifest,
    Verdict,
)
from eval.judge.store import (
    CorpusMismatch,
    ResponseStore,
    StoreError,
    list_fingerprints,
    list_runs,
)

FINGERPRINT = "08527fbdf140f811"
OTHER_FINGERPRINT = "deadbeefdeadbeef"

TEXTS = [
    "The Central Arizona Project delivers Colorado River water across 336 miles.",
    "Active Management Areas regulate groundwater withdrawal in Phoenix and Tucson.",
    "Lake Mead shortage tiers are defined by the Drought Contingency Plan.",
    "Tribal water settlements allocate Central Arizona Project water to communities.",
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def embedder():
    return HashingEmbedder(dimension=48)


@pytest.fixture
def retriever(embedder):
    chunks = [
        Chunk(f"chunk_{i:02d}", f"doc_{i // 2}", text, tuple(embedder.embed(text)))
        for i, text in enumerate(TEXTS)
    ]
    return ExactRetriever(chunks, embedder)


@pytest.fixture
def items():
    return [
        BenchmarkItem("q001", "What is the Central Arizona Project?", "general_policy"),
        BenchmarkItem("q002", "How is groundwater regulated in Arizona?", "general_policy"),
        BenchmarkItem("q003", "Who will win the next election?", "out_of_scope_negative"),
    ]


@pytest.fixture
def measurement_version():
    return MeasurementVersion(
        corpus_fingerprint=FINGERPRINT,
        rubric_hash="r" * 16,
        prompt_hash="p" * 16,
        judge_set=("gpt-4.1-2025-04-14",),
        aggregation_version="1.0.0",
        k=5,
        temperature=0.3,
    )


@pytest.fixture
def store(tmp_path):
    return ResponseStore(FINGERPRINT, "run-001", runs_dir=str(tmp_path))


def a_response(item_id="q001", system="waterbot", persona="blue", **kw) -> Response:
    payload = {
        "item_id": item_id,
        "system": system,
        "persona": persona,
        "question": "What is CAP?",
        "category": "general_policy",
        "answer": "CAP is a 336-mile aqueduct.",
        "passages": [],
        "citations": [],
        "latency_ms": 100,
        "cost_usd": 0.004,
    }
    payload.update(kw)
    return Response(**payload)


def a_manifest(measurement_version, run_id="run-001", fingerprint=FINGERPRINT) -> RunManifest:
    return RunManifest(
        run_id=run_id,
        corpus_fingerprint=fingerprint,
        dataset_version="1.0.0",
        measurement_version=measurement_version,
    )


def a_verdict(response_id="q001::waterbot::blue", sample_index=0, **kw) -> Verdict:
    payload = {
        "item_id": response_id.split("::")[0],
        "response_id": response_id,
        "judge_model_id": "gpt-4.1-2025-04-14",
        "sample_index": sample_index,
        "temperature": 0.3,
        "prompt_hash": "p" * 16,
        "rubric_hash": "r" * 16,
        "corpus_fingerprint": FINGERPRINT,
        "dimensions": {"grounding": DimensionVerdict(rationale="ok", score=3)},
    }
    payload.update(kw)
    return Verdict(**payload)


def sha(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


# ---------------------------------------------------------------------------
# The acceptance check
# ---------------------------------------------------------------------------
def test_two_freezes_produce_byte_identical_response_files(
    tmp_path, retriever, items, measurement_version
):
    """Milestone 4's acceptance check, stated exactly.

    Not 'equivalent', not 'same after parsing'. Byte-identical, which is the only version of
    the claim that cannot hide a reordering or a float formatting difference.
    """
    paths = []
    for run_id in ("run-a", "run-b"):
        store = ResponseStore(FINGERPRINT, run_id, runs_dir=str(tmp_path))
        freeze_run(
            store, items, retriever, EchoGenerator(), "waterbot", "blue",
            "1.0.0", measurement_version,
        )
        paths.append(store.responses_path("waterbot", "blue"))

    assert sha(paths[0]) == sha(paths[1])


def test_freeze_is_byte_stable_against_item_ordering(
    tmp_path, retriever, items, measurement_version
):
    """Records are sorted by item id, so input order cannot change the file."""
    paths = []
    for run_id, ordered in (("run-a", items), ("run-b", list(reversed(items)))):
        store = ResponseStore(FINGERPRINT, run_id, runs_dir=str(tmp_path))
        freeze_run(
            store, ordered, retriever, EchoGenerator(), "waterbot", "blue",
            "1.0.0", measurement_version,
        )
        paths.append(store.responses_path("waterbot", "blue"))

    assert sha(paths[0]) == sha(paths[1])


def test_response_files_use_lf_newlines(tmp_path, retriever, items, measurement_version):
    """A CRLF translation on Windows would break byte-identity across platforms."""
    store = ResponseStore(FINGERPRINT, "run-a", runs_dir=str(tmp_path))
    freeze_run(
        store, items, retriever, EchoGenerator(), "waterbot", "blue", "1.0.0", measurement_version
    )
    with open(store.responses_path("waterbot", "blue"), "rb") as handle:
        raw = handle.read()
    assert b"\r\n" not in raw
    assert raw.endswith(b"\n")


def test_changing_retrieval_changes_the_frozen_file(
    tmp_path, retriever, items, measurement_version, embedder
):
    """The determinism test must have something to catch: different evidence, different file."""
    store_a = ResponseStore(FINGERPRINT, "run-a", runs_dir=str(tmp_path))
    freeze_run(store_a, items, retriever, EchoGenerator(), "waterbot", "blue",
               "1.0.0", measurement_version, k=4)

    store_b = ResponseStore(FINGERPRINT, "run-b", runs_dir=str(tmp_path))
    freeze_run(store_b, items, retriever, EchoGenerator(), "waterbot", "blue",
               "1.0.0", measurement_version, k=1)

    assert sha(store_a.responses_path("waterbot", "blue")) != sha(
        store_b.responses_path("waterbot", "blue")
    )


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------
def test_runs_are_scoped_by_corpus_fingerprint(tmp_path):
    """Two corpora cannot land in the same directory, even with the same run id."""
    a = ResponseStore(FINGERPRINT, "run-001", runs_dir=str(tmp_path))
    b = ResponseStore(OTHER_FINGERPRINT, "run-001", runs_dir=str(tmp_path))
    assert a.path != b.path
    assert FINGERPRINT in a.path and OTHER_FINGERPRINT in b.path


def test_a_store_requires_a_fingerprint(tmp_path):
    with pytest.raises(StoreError, match="corpus fingerprint"):
        ResponseStore("", "run-001", runs_dir=str(tmp_path))


def test_responses_are_split_by_system_and_persona(
    tmp_path, retriever, items, measurement_version
):
    store = ResponseStore(FINGERPRINT, "run-001", runs_dir=str(tmp_path))
    blue = freeze_responses(items, retriever, EchoGenerator("blue"), "waterbot", "blue")
    river = freeze_responses(items, retriever, EchoGenerator("river"), "waterbot", "river")
    store.freeze(a_manifest(measurement_version), blue + river)

    assert store.pairs() == [("waterbot", "blue"), ("waterbot", "river")]
    assert os.path.exists(store.responses_path("waterbot", "river"))
    assert len(store.load_responses(persona="blue")) == len(items)


def test_unsafe_name_components_are_made_filename_safe(tmp_path, measurement_version):
    store = ResponseStore(FINGERPRINT, "run-001", runs_dir=str(tmp_path))
    store.freeze(
        a_manifest(measurement_version), [a_response(system="water/bot", persona="blue:1")]
    )
    assert store.load_responses()[0].system == "water/bot"


# ---------------------------------------------------------------------------
# Write-once
# ---------------------------------------------------------------------------
def test_refreezing_raises(store, measurement_version):
    store.freeze(a_manifest(measurement_version), [a_response()])
    with pytest.raises(StoreError, match="immutable"):
        store.freeze(a_manifest(measurement_version), [a_response()])


def test_overwrite_discards_the_whole_run(store, measurement_version):
    """Keeping verdicts that point at replaced text would be worse than losing them."""
    store.freeze(a_manifest(measurement_version), [a_response()])
    store.append_verdicts([a_verdict()])
    assert len(store.load_verdicts()) == 1

    store.freeze(a_manifest(measurement_version), [a_response()], overwrite=True)
    assert store.load_verdicts() == []


def test_freezing_nothing_is_refused(store, measurement_version):
    with pytest.raises(StoreError, match="no responses"):
        store.freeze(a_manifest(measurement_version), [])


def test_duplicate_response_ids_are_refused(store, measurement_version):
    with pytest.raises(StoreError, match="duplicate response ids"):
        store.freeze(a_manifest(measurement_version), [a_response(), a_response()])


def test_manifest_fingerprint_must_match_the_store(store, measurement_version):
    other = MeasurementVersion(
        corpus_fingerprint=OTHER_FINGERPRINT, rubric_hash="r" * 16, prompt_hash="p" * 16,
        judge_set=("gpt-x",), aggregation_version="1.0.0", k=5, temperature=0.3,
    )
    with pytest.raises(CorpusMismatch):
        store.freeze(a_manifest(other, fingerprint=OTHER_FINGERPRINT), [a_response()])


def test_manifest_run_id_must_match_the_store(store, measurement_version):
    with pytest.raises(StoreError, match="run_id"):
        store.freeze(a_manifest(measurement_version, run_id="different"), [a_response()])


# ---------------------------------------------------------------------------
# Loading and the corpus check
# ---------------------------------------------------------------------------
def test_round_trip_preserves_everything(store, measurement_version, retriever, items):
    frozen = freeze_responses(items, retriever, EchoGenerator(), "waterbot", "blue")
    store.freeze(a_manifest(measurement_version), frozen)
    loaded = store.load_responses()
    assert loaded == sorted(frozen, key=lambda r: r.response_id)


def test_passages_survive_the_round_trip(store, measurement_version, retriever, items):
    """Passage text is pinned; a pointer would change meaning when the corpus is repaired."""
    frozen = freeze_responses(items, retriever, EchoGenerator(), "waterbot", "blue")
    store.freeze(a_manifest(measurement_version), frozen)
    loaded = store.load_responses()[0]
    assert loaded.passages
    assert loaded.passages[0].text == frozen[0].passages[0].text


def test_loading_with_a_mismatched_expectation_raises(store, measurement_version):
    store.freeze(a_manifest(measurement_version), [a_response()])
    with pytest.raises(CorpusMismatch, match="expected corpus"):
        store.load_responses(expected_fingerprint=OTHER_FINGERPRINT)


def test_loading_with_the_right_expectation_succeeds(store, measurement_version):
    store.freeze(a_manifest(measurement_version), [a_response()])
    assert len(store.load_responses(expected_fingerprint=FINGERPRINT)) == 1


def test_a_manifest_stored_under_the_wrong_fingerprint_is_caught(store, measurement_version):
    """Guards against a directory being moved or hand-edited."""
    store.freeze(a_manifest(measurement_version), [a_response()])
    with open(store.manifest_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    payload["corpus_fingerprint"] = OTHER_FINGERPRINT
    payload["measurement_version"]["corpus_fingerprint"] = OTHER_FINGERPRINT
    with open(store.manifest_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)

    with pytest.raises(CorpusMismatch, match="declares fingerprint"):
        store.load_manifest()


def test_loading_a_run_that_does_not_exist_raises(store):
    with pytest.raises(StoreError, match="no manifest"):
        store.load_manifest()


def test_corrupt_jsonl_names_the_line(store, measurement_version):
    store.freeze(a_manifest(measurement_version), [a_response()])
    with open(store.responses_path("waterbot", "blue"), "a", encoding="utf-8") as handle:
        handle.write("{not json\n")
    with pytest.raises(StoreError, match="line 2"):
        store.load_responses()


# ---------------------------------------------------------------------------
# Verdicts: append-only
# ---------------------------------------------------------------------------
def test_verdicts_append_rather_than_replace(store, measurement_version):
    store.freeze(a_manifest(measurement_version), [a_response()])
    store.append_verdicts([a_verdict(sample_index=0)])
    store.append_verdicts([a_verdict(sample_index=1)])
    assert sorted(v.sample_index for v in store.load_verdicts()) == [0, 1]


def test_verdicts_are_split_by_judge(store, measurement_version):
    store.freeze(a_manifest(measurement_version), [a_response()])
    store.append_verdicts([
        a_verdict(judge_model_id="gpt-4.1-2025-04-14"),
        a_verdict(judge_model_id="claude-sonnet-4-5-20250929"),
    ])
    assert len(store.load_verdicts(judge_model_id="gpt-4.1-2025-04-14")) == 1
    assert len(store.load_verdicts()) == 2


def test_a_verdict_pointing_at_no_response_is_refused(store, measurement_version):
    """Otherwise it surfaces much later as a mysteriously small sample."""
    store.freeze(a_manifest(measurement_version), [a_response()])
    with pytest.raises(StoreError, match="reference responses not in this run"):
        store.append_verdicts([a_verdict(response_id="q999::waterbot::blue")])


def test_a_verdict_from_another_corpus_is_refused(store, measurement_version):
    store.freeze(a_manifest(measurement_version), [a_response()])
    with pytest.raises(CorpusMismatch):
        store.append_verdicts([a_verdict(corpus_fingerprint=OTHER_FINGERPRINT)])


def test_a_repeated_vote_is_refused(store, measurement_version):
    """A double-counted vote narrows the interval on evidence gathered once."""
    store.freeze(a_manifest(measurement_version), [a_response()])
    store.append_verdicts([a_verdict(sample_index=0)])
    with pytest.raises(StoreError, match="double-count"):
        store.append_verdicts([a_verdict(sample_index=0)])


def test_a_repeated_vote_within_one_batch_is_refused(store, measurement_version):
    store.freeze(a_manifest(measurement_version), [a_response()])
    with pytest.raises(StoreError, match="double-count"):
        store.append_verdicts([a_verdict(sample_index=0), a_verdict(sample_index=0)])


def test_the_same_sample_index_from_a_different_judge_is_fine(store, measurement_version):
    """Sample 0 from judge A and sample 0 from judge B are two independent votes."""
    store.freeze(a_manifest(measurement_version), [a_response()])
    store.append_verdicts([
        a_verdict(judge_model_id="judge-a", sample_index=0),
        a_verdict(judge_model_id="judge-b", sample_index=0),
    ])
    assert len(store.load_verdicts()) == 2


def test_validation_can_be_skipped_for_bulk_loads(store, measurement_version):
    store.freeze(a_manifest(measurement_version), [a_response()])
    store.append_verdicts([a_verdict(response_id="q999::waterbot::blue")], validate=False)
    assert len(store.load_verdicts()) == 1


def test_appending_to_an_unfrozen_run_is_refused(store):
    with pytest.raises(StoreError, match="has not been frozen"):
        store.append_verdicts([a_verdict()])


def test_appending_nothing_is_a_no_op(store, measurement_version):
    store.freeze(a_manifest(measurement_version), [a_response()])
    assert store.append_verdicts([]) == 0


def test_verdicts_group_by_response(store, measurement_version):
    store.freeze(a_manifest(measurement_version), [a_response("q001"), a_response("q002")])
    store.append_verdicts([
        a_verdict("q001::waterbot::blue", 0),
        a_verdict("q001::waterbot::blue", 1),
        a_verdict("q002::waterbot::blue", 0),
    ])
    grouped = store.verdicts_by_response()
    assert len(grouped["q001::waterbot::blue"]) == 2
    assert len(grouped["q002::waterbot::blue"]) == 1


# ---------------------------------------------------------------------------
# Integrity
# ---------------------------------------------------------------------------
def test_integrity_passes_on_a_healthy_run(store, measurement_version):
    store.freeze(a_manifest(measurement_version), [a_response()])
    store.append_verdicts([a_verdict(sample_index=0), a_verdict(sample_index=1)])
    report = store.check_integrity()
    assert report["ok"] is True
    assert report["n_responses"] == 1 and report["n_verdicts"] == 2


def test_integrity_detects_collapsed_sample_indices(store, measurement_version):
    """The cache-key bug: k samples sharing an index report zero variance from k opinions.

    The validated write path now refuses this outright, so the only way it can reach disk is a
    direct file write that bypassed validation. The integrity check has to catch it anyway -
    that is what makes it an audit rather than a restatement of the write path.
    """
    store.freeze(a_manifest(measurement_version), [a_response()])
    store.append_verdicts([a_verdict(sample_index=0)])
    store.append_verdicts([a_verdict(sample_index=0)], validate=False)

    report = store.check_integrity()
    assert report["ok"] is False
    assert report["duplicate_sample_indices"]


def test_integrity_counts_unjudged_responses(store, measurement_version):
    """A run mid-judging must not be mistakable for a finished one at analysis time."""
    store.freeze(a_manifest(measurement_version), [a_response("q001"), a_response("q002")])
    store.append_verdicts([a_verdict("q001::waterbot::blue")])
    report = store.check_integrity()
    assert report["responses_with_no_verdict"] == 1
    assert report["unjudged_examples"] == ["q002::waterbot::blue"]
    assert report["ok"] is True  # incomplete is not corrupt


def test_integrity_lists_the_judges_that_voted(store, measurement_version):
    store.freeze(a_manifest(measurement_version), [a_response()])
    store.append_verdicts([
        a_verdict(judge_model_id="judge-b"),
        a_verdict(judge_model_id="judge-a"),
    ])
    assert store.check_integrity()["judges"] == ["judge-a", "judge-b"]


def test_integrity_records_the_abstention_count(store, measurement_version):
    """Abstentions are recorded before anything downstream can drop them."""
    store.freeze(a_manifest(measurement_version), [a_response()])
    store.append_verdicts([
        a_verdict(dimensions={
            "grounding": DimensionVerdict(rationale="clear", score=3),
            "correctness": DimensionVerdict(
                rationale="no evidence", insufficient_evidence=True, score=None
            ),
        })
    ])
    assert store.check_integrity()["n_abstained_dimensions"] == 1


def test_integrity_counts_repaired_verdicts(store, measurement_version):
    """Repair rate is a reported metric; silent retries hide a bias on hard items."""
    store.freeze(a_manifest(measurement_version), [a_response()])
    store.append_verdicts([a_verdict(sample_index=0, repaired=True),
                           a_verdict(sample_index=1)])
    assert store.check_integrity()["repaired_verdicts"] == 1


def test_integrity_detects_orphan_verdicts(store, measurement_version):
    store.freeze(a_manifest(measurement_version), [a_response()])
    store.append_verdicts([a_verdict(response_id="q999::waterbot::blue")], validate=False)
    report = store.check_integrity()
    assert report["ok"] is False
    assert report["orphan_verdicts"] == ["q999::waterbot::blue"]


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------
def test_runs_can_be_listed_by_fingerprint(tmp_path, measurement_version):
    for run_id in ("run-a", "run-b"):
        store = ResponseStore(FINGERPRINT, run_id, runs_dir=str(tmp_path))
        store.freeze(a_manifest(measurement_version, run_id=run_id), [a_response()])

    assert list_fingerprints(str(tmp_path)) == [FINGERPRINT]
    assert list_runs(FINGERPRINT, str(tmp_path)) == ["run-a", "run-b"]


def test_listing_an_unknown_fingerprint_is_empty(tmp_path):
    assert list_runs("nothing-here", str(tmp_path)) == []
    assert list_fingerprints(str(tmp_path / "missing")) == []


# ---------------------------------------------------------------------------
# The freeze path
# ---------------------------------------------------------------------------
def test_passages_are_numbered_from_one_in_retrieval_order(retriever, items):
    frozen = freeze_responses(items, retriever, EchoGenerator(), "waterbot", "blue", k=3)
    passages = frozen[0].passages
    assert [p.evidence_id for p in passages] == [1, 2, 3]
    assert [p.retrieval_rank for p in passages] == [0, 1, 2]


def test_the_generator_sees_the_passages_the_judge_will_see(retriever, items):
    """If these diverged, the judge would grade an answer written from different evidence."""
    seen = {}

    class RecordingGenerator:
        def generate(self, question, passages):
            seen[question] = [p.chunk_id for p in passages]
            return Generation(answer="ok")

    frozen = freeze_responses(items, retriever, RecordingGenerator(), "waterbot", "blue", k=2)
    for response in frozen:
        assert seen[response.question] == [p.chunk_id for p in response.passages]


def test_freezing_no_items_is_refused(retriever):
    with pytest.raises(ValueError, match="empty item set"):
        freeze_responses([], retriever, EchoGenerator(), "waterbot", "blue")


def test_manifest_records_provenance_and_cost(retriever, items, measurement_version):
    frozen = freeze_responses(items, retriever, EchoGenerator(cost_per_call=0.01),
                              "waterbot", "blue")
    manifest = build_manifest(
        "run-001", FINGERPRINT, "1.0.0", measurement_version, frozen,
        retrieval_params={"mode": "exact_knn", "k": 4},
    )
    assert manifest.systems == ["waterbot"]
    assert manifest.spent_usd == pytest.approx(0.01 * len(items))
    assert "exact_knn" in manifest.notes and "freezer=" in manifest.notes


def test_excluded_questions_are_skipped_by_default():
    questions = [
        {"id": "q001", "question": "a?", "category": "general_policy"},
        {"id": "q002", "question": "b?", "category": "general_policy",
         "excluded_from_scoring": True},
    ]
    assert [i.item_id for i in items_from_dataset(questions)] == ["q001"]
    assert len(items_from_dataset(questions, include_excluded=True)) == 2


def test_run_ids_are_timestamped_and_prefixed():
    run_id = make_run_id("freeze")
    assert run_id.startswith("freeze-") and run_id.endswith("Z")


def test_an_item_with_no_retrieval_still_freezes(store, measurement_version, embedder):
    """Out-of-scope negatives legitimately retrieve nothing useful; k=0 is not allowed, but a
    response with no passages must remain representable."""
    store.freeze(a_manifest(measurement_version), [a_response(passages=[])])
    assert store.load_responses()[0].passages == []
