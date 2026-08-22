"""End-to-end test of the whole judge system.

Drives L0 through L5 in one pass, on fake clients, with no network and no database:

    corpus -> fingerprint + gate (L0)
           -> frozen responses (L1)
           -> panel verdicts (L2)
           -> aggregates with intervals (L3)
           -> label pools, human labels, agreement, calibration (L4)
           -> a report that refuses bad comparisons (L5)
           -> an ablation cell run through the same path

WHAT THIS CATCHES THAT UNIT TESTS CANNOT
-----------------------------------------
Every layer is tested in isolation elsewhere. What is only visible here is whether the layers
actually FIT: whether the fingerprint L0 computes is the one that ends up guarding the report,
whether verdicts L2 writes are readable by L3, whether the aggregates L3 produces can seed L4's
pools, and whether a corpus change at the bottom correctly invalidates a comparison at the top.

Those are the joins, and a join is where a system quietly stops meaning what it claims.
"""

from __future__ import annotations

import pytest

from eval.judge.aggregate import aggregate_all, build_reliability_matrix, summarise_aggregates
from eval.judge.agreement import agreement_report, compare_to_ceiling
from eval.judge.ablation import Cell, CostModel, Factor, Grid, GridLedger, run_grid
from eval.judge.annotate.pools import build_pools, candidates_from_aggregates
from eval.judge.annotate.store import LabelStore, adjudicated_scores, find_disagreements
from eval.judge.calibrate import LabelledPair, build_groups, calibrate
from eval.judge.clients.fake import FakeJudgeClient
from eval.judge.evidence import (
    DocumentSnapshot,
    EvidenceGateFailure,
    build_corpus_identity,
    run_evidence_gate,
    snapshot_from_mapping,
)
from eval.judge.freeze import BenchmarkItem, EchoGenerator, freeze_run
from eval.judge.panel import PanelRunner, Pricing, Budget
from eval.judge.report import (
    Report,
    TestFamily as Family,
    compare_paired,
    gate,
    reported,
)
from eval.judge.retrieval import Chunk, ExactRetriever, HashingEmbedder
from eval.judge.rubric import load_rubric
from eval.judge.schemas import HumanLabel, IncompatibleMeasurement, MeasurementVersion
from eval.judge.store import ResponseStore

DOCUMENTS = {
    "cap_factsheet.pdf": [
        "The Central Arizona Project delivers Colorado River water across 336 miles to "
        "Phoenix, Tucson and tribal communities."
    ],
    "groundwater_act.pdf": [
        "The 1980 Groundwater Management Act created Active Management Areas regulating "
        "withdrawal in Phoenix, Tucson, Pinal, Prescott and Santa Cruz."
    ],
    "shortage_plan.pdf": [
        "Lake Mead shortage tiers are defined by the Drought Contingency Plan and trigger "
        "reductions in Colorado River deliveries."
    ],
    "settlements.pdf": [
        "Tribal water settlements allocate Central Arizona Project water to communities "
        "across the state under federal settlement acts."
    ],
}

ITEMS = [
    BenchmarkItem("q001", "What is the Central Arizona Project?", "general_policy"),
    BenchmarkItem("q002", "How is groundwater regulated in Arizona?", "general_policy"),
    BenchmarkItem("q003", "What defines Lake Mead shortage tiers?", "temporal_realtime"),
    BenchmarkItem("q004", "How is water allocated to tribes?", "entity_grounding"),
    BenchmarkItem("q005", "Who will win the next election?", "out_of_scope_negative"),
    BenchmarkItem("q006", "What is the CAP aqueduct length?", "numeric_extraction"),
]

GOLD_SOURCES = {"cap_factsheet.pdf": ["q001"], "groundwater_act.pdf": ["q002"]}


@pytest.fixture(scope="module")
def rubric():
    return load_rubric()


@pytest.fixture
def corpus():
    return snapshot_from_mapping(DOCUMENTS)


@pytest.fixture
def retriever():
    embedder = HashingEmbedder(dimension=48)
    chunks = [
        Chunk(f"chunk_{i:02d}", name, text, tuple(embedder.embed(text)))
        for i, (name, texts) in enumerate(sorted(DOCUMENTS.items()))
        for text in texts
    ]
    return ExactRetriever(chunks, embedder)


def build_frozen_run(tmp_path, retriever, fingerprint, run_id="run-001", persona="blue"):
    """L0 fingerprint -> L1 frozen responses."""
    version = MeasurementVersion(
        corpus_fingerprint=fingerprint,
        rubric_hash="r" * 16,
        prompt_hash="p" * 16,
        judge_set=("judge-a", "judge-b"),
        aggregation_version="1.0.0",
        k=3,
        temperature=0.3,
    )
    store = ResponseStore(fingerprint, run_id, runs_dir=str(tmp_path))
    freeze_run(
        store, ITEMS, retriever, EchoGenerator(persona), "waterbot", persona,
        dataset_version="1.0.0", measurement_version=version, k=3,
    )
    return store, version


# ---------------------------------------------------------------------------
# The full chain
# ---------------------------------------------------------------------------
def test_the_whole_pipeline_runs_end_to_end(tmp_path, retriever, rubric):
    """One pass from documents to a rendered report."""
    # -- L0 ---------------------------------------------------------------
    corpus = snapshot_from_mapping(DOCUMENTS)
    gate_report = run_evidence_gate(corpus, GOLD_SOURCES)
    assert gate_report.is_clean
    fingerprint = gate_report.fingerprint

    # -- L1 ---------------------------------------------------------------
    store, version = build_frozen_run(tmp_path, retriever, fingerprint)
    responses = store.load_responses(expected_fingerprint=fingerprint)
    assert len(responses) == len(ITEMS)
    assert all(r.passages for r in responses)

    # -- L2 ---------------------------------------------------------------
    runner = PanelRunner(
        clients=[FakeJudgeClient("judge-a", seed=1), FakeJudgeClient("judge-b", seed=2)],
        rubric=rubric, rubric_hash=version.rubric_hash, corpus_fingerprint=fingerprint,
        pricing={"judge-a": Pricing(0.002, 0.008), "judge-b": Pricing(0.002, 0.008)},
        budget=Budget(cap_usd=10.0), samples=version.k, allow_unpiloted_rubric=True,
    )
    verdicts = runner.judge_all(responses)
    assert verdicts
    store.append_verdicts(verdicts)
    assert store.check_integrity()["ok"] is True

    # -- L3 ---------------------------------------------------------------
    aggregates = aggregate_all(verdicts, expected_votes=2 * version.k, n_boot=200)
    assert aggregates
    summary = summarise_aggregates(aggregates)
    assert summary.n_aggregates == len(aggregates)

    matrix = build_reliability_matrix(verdicts, "grounding")
    assert matrix.shape[0] == 2  # two judges

    # -- L4 ---------------------------------------------------------------
    categories = {r.response_id: r.category for r in responses}
    scored = [a for a in aggregates if a.mean is not None]
    candidates = candidates_from_aggregates(scored, categories)
    # The probe pool is stratified, so the budget must leave room for every category.
    pools = build_pools(candidates, budget=min(len(candidates), 20), seed=0)
    assert pools.budget > 0

    labels = LabelStore(str(tmp_path / "labels.jsonl"))
    labels.append(
        [
            HumanLabel(
                response_id=candidate.response_id, dimension=candidate.dimension,
                annotator_id=annotator,
                score=max(1, min(4, round(candidate.panel_mean or 3))),
                pool=pool_name,
            )
            for pool_name, pool in (("probe", pools.probe), ("acquire", pools.acquire))
            for candidate in pool
            for annotator in ("ab", "cd")
        ]
    )

    from eval.judge.annotate.store import ceiling_matrix

    _, shared_items, rows = ceiling_matrix(labels.load_pre_adjudication(), "grounding")
    if shared_items:
        human = agreement_report(rows, label="grounding (humans)")
        assert human.n_units == len(shared_items)

    # -- L5 ---------------------------------------------------------------
    per_item = [a.mean for a in aggregates if a.mean is not None]
    report = Report(run_id=store.run_id, measurement_version=version)
    report.add(reported("panel mean", per_item, version, n_boot=200))
    markdown = report.to_markdown()
    assert fingerprint in markdown
    assert "95% interval" in markdown


# ---------------------------------------------------------------------------
# The joins
# ---------------------------------------------------------------------------
def test_the_corpus_fingerprint_reaches_the_report(tmp_path, retriever, rubric):
    """The identity computed at the bottom must be the one guarding the top."""
    corpus = snapshot_from_mapping(DOCUMENTS)
    fingerprint = run_evidence_gate(corpus, GOLD_SOURCES).fingerprint
    store, version = build_frozen_run(tmp_path, retriever, fingerprint)

    assert store.load_manifest().corpus_fingerprint == fingerprint
    report = Report(run_id=store.run_id, measurement_version=version)
    assert fingerprint in report.to_markdown()


def test_a_corpus_change_invalidates_a_comparison(tmp_path, retriever, rubric):
    """The whole point of L0 feeding L5: repairing the corpus must break comparability.

    This is the failure the architecture is built to prevent - comparing a number measured
    against the corrupted corpus with one measured against the repaired corpus, as though the
    difference were about the system.
    """
    original = snapshot_from_mapping(DOCUMENTS)
    repaired_documents = dict(DOCUMENTS)
    repaired_documents["settlements.pdf"] = [
        "A genuinely different settlements chapter, correctly acquired this time."
    ]
    repaired = snapshot_from_mapping(repaired_documents)

    before = run_evidence_gate(original, GOLD_SOURCES).fingerprint
    after = run_evidence_gate(repaired, GOLD_SOURCES).fingerprint
    assert before != after

    _, version_before = build_frozen_run(tmp_path, retriever, before, run_id="before")
    _, version_after = build_frozen_run(tmp_path, retriever, after, run_id="after")

    number_before = reported("grounding", [3.0, 3.5, 2.5, 3.0], version_before, n_boot=100)
    number_after = reported("grounding", [2.0, 2.5, 1.5, 2.0], version_after, n_boot=100)

    with pytest.raises(IncompatibleMeasurement, match="corpus_fingerprint"):
        gate(number_after, number_before)


def test_a_corrupted_corpus_stops_the_pipeline_at_the_gate():
    """Nothing downstream should get the chance to produce a number."""
    corrupted = dict(DOCUMENTS)
    corrupted["settlements_copy.pdf"] = DOCUMENTS["settlements.pdf"]
    with pytest.raises(EvidenceGateFailure, match="byte-identical"):
        run_evidence_gate(snapshot_from_mapping(corrupted), GOLD_SOURCES)


def test_verdicts_written_by_the_panel_are_readable_by_aggregation(tmp_path, retriever, rubric):
    corpus = snapshot_from_mapping(DOCUMENTS)
    fingerprint = run_evidence_gate(corpus, GOLD_SOURCES).fingerprint
    store, version = build_frozen_run(tmp_path, retriever, fingerprint)
    responses = store.load_responses()

    runner = PanelRunner(
        clients=[FakeJudgeClient("judge-a", seed=1), FakeJudgeClient("judge-b", seed=2)],
        rubric=rubric, rubric_hash=version.rubric_hash, corpus_fingerprint=fingerprint,
        samples=3, allow_unpiloted_rubric=True,
    )
    store.append_verdicts(runner.judge_all(responses))

    # Round-trip through disk, not just through memory.
    reloaded = store.load_verdicts()
    aggregates = aggregate_all(reloaded, expected_votes=6, n_boot=100)
    assert aggregates
    assert any(a.mean is not None for a in aggregates)


def test_aggregates_seed_the_label_pools(tmp_path, retriever, rubric):
    corpus = snapshot_from_mapping(DOCUMENTS)
    fingerprint = run_evidence_gate(corpus, GOLD_SOURCES).fingerprint
    store, version = build_frozen_run(tmp_path, retriever, fingerprint)
    responses = store.load_responses()

    runner = PanelRunner(
        clients=[FakeJudgeClient("judge-a", seed=1), FakeJudgeClient("judge-b", seed=2)],
        rubric=rubric, rubric_hash=version.rubric_hash, corpus_fingerprint=fingerprint,
        samples=3, allow_unpiloted_rubric=True,
    )
    aggregates = aggregate_all(runner.judge_all(responses), expected_votes=6, n_boot=100)
    scored = [a for a in aggregates if a.mean is not None]

    categories = {r.response_id: r.category for r in responses}
    pools = build_pools(candidates_from_aggregates(scored, categories),
                        budget=min(len(scored), 20), seed=0)
    assert not ({c.key for c in pools.probe} & {c.key for c in pools.acquire})


def test_human_labels_flow_into_calibration_and_the_ceiling(tmp_path):
    """L4 end to end: labels -> disagreements -> adjudication -> ceiling and a fitted map."""
    store = LabelStore(str(tmp_path / "labels.jsonl"))

    # Two annotators, mostly agreeing, on enough items to fit and to split into groups.
    records = []
    for i in range(40):
        truth = 1 + (i % 4)
        records.append(HumanLabel(
            response_id=f"q{i:03d}::waterbot::blue", dimension="grounding",
            annotator_id="ab", score=truth, pool="acquire",
        ))
        drift = truth if i % 5 else max(1, min(4, truth + 1))
        records.append(HumanLabel(
            response_id=f"q{i:03d}::waterbot::blue", dimension="grounding",
            annotator_id="cd", score=drift, pool="acquire",
        ))
    store.append(records)

    from eval.judge.annotate.store import ceiling_matrix

    annotators, items, rows = ceiling_matrix(store.load_pre_adjudication(), "grounding")
    assert annotators == ["ab", "cd"]
    assert len(items) == 40

    human = agreement_report(rows, label="grounding (humans)")
    assert human.alpha_ordinal is not None

    # A judge that tracks the humans imperfectly.
    judge_rows = [
        [score if index % 3 else max(1, min(4, (score or 3) + 1)) for index, score in enumerate(row)]
        for row in rows
    ]
    comparison = compare_to_ceiling(rows, judge_rows, "grounding")
    assert comparison.ceiling is not None
    assert comparison.verdict

    # And the same labels calibrate.
    final = adjudicated_scores(store.load_all())
    pairs = [
        LabelledPair(
            item_id=response_id.split("::")[0],
            panel_mean=float(score) + 0.3,
            human_score=float(score),
            category=["general_policy", "multi_hop", "numeric_extraction"][index % 3],
        )
        for index, ((response_id, _dimension), score) in enumerate(sorted(final.items()))
        if score is not None
    ]
    groups = build_groups({p.item_id: [f"doc{i // 4}"] for i, p in enumerate(pairs)})
    result = calibrate(pairs, "grounding", groups)
    assert result.n_folds == 5
    assert result.chosen_mae >= 0


def test_disagreements_are_found_and_adjudicated_without_losing_the_originals(tmp_path):
    store = LabelStore(str(tmp_path / "labels.jsonl"))
    store.append([
        HumanLabel(response_id="q001::waterbot::blue", dimension="grounding",
                   annotator_id="ab", score=1, pool="probe"),
        HumanLabel(response_id="q001::waterbot::blue", dimension="grounding",
                   annotator_id="cd", score=4, pool="probe"),
    ])
    disagreements = find_disagreements(store.load_latest())
    assert len(disagreements) == 1

    from eval.judge.annotate.store import adjudicate

    store.append([adjudicate(disagreements[0], score=2, adjudicator_id="zz")])
    assert adjudicated_scores(store.load_all())[("q001::waterbot::blue", "grounding")] == 2
    assert sorted(l.score for l in store.load_pre_adjudication()) == [1, 4]


# ---------------------------------------------------------------------------
# Reproducibility of the whole chain
# ---------------------------------------------------------------------------
def test_the_whole_chain_is_reproducible(tmp_path, retriever, rubric):
    """Same inputs, same fingerprint, same frozen bytes, same verdicts, same aggregates."""
    corpus = snapshot_from_mapping(DOCUMENTS)
    fingerprint_a = run_evidence_gate(corpus, GOLD_SOURCES).fingerprint
    fingerprint_b = run_evidence_gate(corpus, GOLD_SOURCES).fingerprint
    assert fingerprint_a == fingerprint_b

    def one_pass(run_id):
        store, version = build_frozen_run(tmp_path, retriever, fingerprint_a, run_id=run_id)
        responses = store.load_responses()
        runner = PanelRunner(
            clients=[FakeJudgeClient("judge-a", seed=1)],
            rubric=rubric, rubric_hash=version.rubric_hash,
            corpus_fingerprint=fingerprint_a, samples=3, allow_unpiloted_rubric=True,
        )
        verdicts = runner.judge_all(responses)
        aggregates = aggregate_all(verdicts, expected_votes=3, n_boot=100)
        with open(store.responses_path("waterbot", "blue"), "rb") as handle:
            frozen_bytes = handle.read()
        return frozen_bytes, [(a.response_id, a.dimension, a.mean) for a in aggregates]

    bytes_a, aggregates_a = one_pass("pass-a")
    bytes_b, aggregates_b = one_pass("pass-b")
    assert bytes_a == bytes_b
    assert aggregates_a == aggregates_b


# ---------------------------------------------------------------------------
# An ablation cell through the same path
# ---------------------------------------------------------------------------
def test_an_ablation_cell_drives_the_real_pipeline(tmp_path, retriever, rubric):
    """The grid is only useful if a cell actually runs the stack it claims to configure."""
    corpus = snapshot_from_mapping(DOCUMENTS)
    fingerprint = run_evidence_gate(corpus, GOLD_SOURCES).fingerprint
    store, base_version = build_frozen_run(tmp_path, retriever, fingerprint)
    responses = store.load_responses()

    grid = Grid((
        Factor("panel", ("1x1", "1x3"), True),
        Factor("persona", ("blue",), False),
    ))

    observed = {}

    def runner(cell, version):
        judges, samples = cell.level_of("panel").split("x")
        panel = PanelRunner(
            clients=[FakeJudgeClient(f"judge-{i}", seed=i) for i in range(int(judges))],
            rubric=rubric, rubric_hash=version.rubric_hash,
            corpus_fingerprint=fingerprint, samples=int(samples),
            allow_unpiloted_rubric=True,
        )
        verdicts = panel.judge_all(responses)
        observed[cell.cell_id] = len(verdicts)
        return {"spent_usd": 0.0, "n_verdicts": len(verdicts)}

    run = run_grid(grid, base_version, runner=runner,
                   ledger=GridLedger(str(tmp_path / "grid.jsonl")),
                   cost_model=CostModel(n_items=len(ITEMS)))

    assert len(run.completed) == 2
    assert len(run.failed) == 0
    # k=3 must produce three times the verdicts of k=1, which is the check that the cell's
    # configuration actually reached the panel rather than being recorded and ignored.
    counts = sorted(observed.values())
    assert counts[1] == 3 * counts[0]


def test_a_full_report_assembles_from_a_real_run(tmp_path, retriever, rubric):
    """L3 output, an FDR-corrected family, and a gate, in one rendered document."""
    corpus = snapshot_from_mapping(DOCUMENTS)
    fingerprint = run_evidence_gate(corpus, GOLD_SOURCES).fingerprint
    store, version = build_frozen_run(tmp_path, retriever, fingerprint)
    responses = store.load_responses()

    runner = PanelRunner(
        clients=[FakeJudgeClient("judge-a", seed=1), FakeJudgeClient("judge-b", seed=2)],
        rubric=rubric, rubric_hash=version.rubric_hash, corpus_fingerprint=fingerprint,
        samples=3, allow_unpiloted_rubric=True,
    )
    aggregates = aggregate_all(runner.judge_all(responses), expected_votes=6, n_boot=100)
    means = [a.mean for a in aggregates if a.mean is not None]

    report = Report(run_id=store.run_id, measurement_version=version)
    report.add(reported("panel mean", means, version, n_boot=200))

    family = Family(name="dimensions", declared=("grounding", "refusal_appropriateness"))
    family.record(compare_paired("grounding", means, means, n_permutations=200))
    family.record(compare_paired("refusal_appropriateness", means, means, n_permutations=200))
    family.adjust()
    report.add_family(family)

    baseline = reported("panel mean", means, version, n_boot=200)
    report.gates.append(gate(report.numbers[0], baseline))

    markdown = report.to_markdown()
    assert "## Results" in markdown
    assert "p (adjusted)" in markdown
    assert "2 tests declared in advance" in markdown
    assert "PASS" in markdown
