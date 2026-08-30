"""L1: freezing a response set.

Runs retrieval once per benchmark item, calls the system under test once, and pins the result -
answer, retrieved passage TEXT, citations, cost - into an immutable record.

WHAT GETS PINNED, AND WHY TEXT RATHER THAN POINTERS
---------------------------------------------------
A response stores the passage text itself, not a reference into the corpus. A pointer would
silently change meaning when the corpus is repaired, which would make old verdicts unreadable at
exactly the moment RQ5 wants to compare judgements against the corrupted corpus with judgements
against the repaired one. Pinning costs disk and buys the ability to answer "what did the judge
actually read?" a year later.

EVERYTHING IS INJECTED
----------------------
The generator and the retriever are parameters, not imports. The real freeze passes the
production pipeline; tests pass deterministic fakes. That is what lets the whole layer be tested
with no network, no database and no key (invariant 3), and it is why milestone 4's acceptance
check can run in CI.
"""

from __future__ import annotations

import datetime
import subprocess
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Protocol, Sequence

from eval.judge.retrieval import ExactRetriever, Hit
from eval.judge.schemas import MeasurementVersion, Passage, Response, RunManifest
from eval.judge.store import ResponseStore

# Bumped when the freezing procedure itself changes in a way that alters what is captured.
FREEZER_VERSION = "1.0.0"


class Generator(Protocol):
    """The system under test.

    Takes a question and the passages retrieved for it, returns the answer and what it cost.
    Deliberately narrow: the freezer does not care how the answer was produced, only that the
    same passages the judge will see are the passages the generator saw.
    """

    def generate(self, question: str, passages: Sequence[Passage]) -> "Generation": ...


@dataclass(frozen=True)
class Generation:
    """One system answer, with the accounting the manifest needs."""

    answer: str
    citations: Sequence[str] = ()
    latency_ms: int = 0
    cost_usd: float = 0.0


@dataclass(frozen=True)
class BenchmarkItem:
    """The slice of a benchmark question the freezer needs."""

    item_id: str
    question: str
    category: str
    # None means "this source did not say"; the scoring class is then read off `category`.
    should_refuse: Optional[bool] = None


def items_from_dataset(questions: Sequence[dict], include_excluded: bool = False) -> List[BenchmarkItem]:
    """Adapt ``benchmark_dataset.json`` question dicts into freezer items."""
    items = []
    for question in questions:
        if not include_excluded and question.get("excluded_from_scoring"):
            continue
        items.append(
            BenchmarkItem(
                item_id=question["id"],
                question=question["question"],
                category=question["category"],
            )
        )
    return sorted(items, key=lambda i: i.item_id)


def _passages_from_hits(hits: Sequence[Hit]) -> List[Passage]:
    """Number passages 1..n in retrieval order.

    The judge is told to cite passages by number, so the numbering must be dense and must match
    what the judge is shown. ``Response`` enforces that independently; doing it here means the
    enforcement never has to fire.
    """
    return [
        Passage(
            evidence_id=index,
            canonical_doc_id=hit.chunk.canonical_doc_id,
            chunk_id=hit.chunk.chunk_id,
            text=hit.chunk.text,
            retrieval_rank=hit.rank,
            retrieval_score=hit.score,
        )
        for index, hit in enumerate(hits, start=1)
    ]


def git_sha() -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip() or None
    except Exception:  # noqa: BLE001 - provenance is best effort
        return None


def freeze_responses(
    items: Sequence[BenchmarkItem],
    retriever: ExactRetriever,
    generator: Generator,
    system: str,
    persona: str,
    k: int = 4,
) -> List[Response]:
    """Retrieve once and generate once per item. Pure: builds records, writes nothing.

    Separated from the store write so the expensive half can be tested, inspected and retried
    without touching the filesystem, and so a caller can freeze several (system, persona) pairs
    and write them as one run.
    """
    if not items:
        raise ValueError("refusing to freeze an empty item set")

    responses: List[Response] = []
    for item in sorted(items, key=lambda i: i.item_id):
        hits = retriever.search(item.question, k=k)
        passages = _passages_from_hits(hits)
        generation = generator.generate(item.question, passages)
        responses.append(
            Response(
                item_id=item.item_id,
                system=system,
                persona=persona,
                question=item.question,
                category=item.category,
                should_refuse=item.should_refuse,
                answer=generation.answer,
                passages=passages,
                citations=list(generation.citations),
                latency_ms=generation.latency_ms,
                cost_usd=generation.cost_usd,
            )
        )
    return responses


def build_manifest(
    run_id: str,
    corpus_fingerprint: str,
    dataset_version: str,
    measurement_version: MeasurementVersion,
    responses: Sequence[Response],
    retrieval_params: Optional[Dict[str, object]] = None,
    seed: int = 0,
    notes: str = "",
) -> RunManifest:
    """Provenance for a freeze. Invariant 1: no result is written without one."""
    systems = sorted({r.system for r in responses})
    total_cost = sum(r.cost_usd for r in responses)
    retrieval_note = ""
    if retrieval_params:
        retrieval_note = "; ".join(f"{k}={v}" for k, v in sorted(retrieval_params.items()))

    return RunManifest(
        run_id=run_id,
        corpus_fingerprint=corpus_fingerprint,
        dataset_version=dataset_version,
        measurement_version=measurement_version,
        git_sha=git_sha(),
        systems=systems,
        seed=seed,
        spent_usd=round(total_cost, 6),
        notes="; ".join(filter(None, [f"freezer={FREEZER_VERSION}", retrieval_note, notes])),
    )


def freeze_run(
    store: ResponseStore,
    items: Sequence[BenchmarkItem],
    retriever: ExactRetriever,
    generator: Generator,
    system: str,
    persona: str,
    dataset_version: str,
    measurement_version: MeasurementVersion,
    k: int = 4,
    seed: int = 0,
    notes: str = "",
    overwrite: bool = False,
) -> List[Response]:
    """Retrieve, generate, and write one frozen run. The whole L1 path in one call."""
    responses = freeze_responses(items, retriever, generator, system, persona, k=k)
    manifest = build_manifest(
        run_id=store.run_id,
        corpus_fingerprint=store.corpus_fingerprint,
        dataset_version=dataset_version,
        measurement_version=measurement_version,
        responses=responses,
        retrieval_params={"mode": "exact_knn", "k": k, "index": "none (brute force)"},
        seed=seed,
        notes=notes,
    )
    store.freeze(manifest, responses, overwrite=overwrite)
    return responses


def make_run_id(prefix: str = "freeze") -> str:
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{stamp}"


# ---------------------------------------------------------------------------
# A deterministic generator for tests and rehearsals
# ---------------------------------------------------------------------------
class EchoGenerator:
    """Network-free stand-in for the system under test.

    Composes an answer from the retrieved passages, so its output depends on retrieval exactly
    the way a real RAG system's does. That is what makes it useful for testing the freeze path:
    if retrieval changes, the answer changes, and a determinism test that would otherwise pass
    trivially actually has something to catch.
    """

    def __init__(self, persona: str = "blue", cost_per_call: float = 0.004) -> None:
        self.persona = persona
        self.cost_per_call = cost_per_call

    def generate(self, question: str, passages: Sequence[Passage]) -> Generation:
        if not passages:
            return Generation(
                answer="I can only provide information about water in Arizona.",
                citations=[],
                latency_ms=120,
                cost_usd=self.cost_per_call,
            )
        opener = "As the river tells it" if self.persona == "river" else "Based on the sources"
        body = " ".join(p.text.split(".")[0].strip() + "." for p in passages[:2])
        return Generation(
            answer=f"{opener}: {body}",
            citations=sorted({p.canonical_doc_id for p in passages}),
            latency_ms=100 + 10 * len(passages),
            cost_usd=self.cost_per_call,
        )
