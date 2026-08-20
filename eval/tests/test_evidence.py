"""Tests for L0, the evidence layer.

The acceptance check for this layer (spec section 9, milestone 3) is two properties: the
fingerprint changes when chunk size changes, and a proof-carrying map is emitted for names that
share content. Both are tested directly, along with the failure modes that make a dedup pass
dangerous - merging things that only look similar, and depending on iteration order.

Network-free and database-free: everything runs against injected snapshots.
"""

from __future__ import annotations

import pytest

from eval.judge.evidence import (
    DEFAULT_MINHASH_PERMUTATIONS,
    CanonicalMap,
    DocumentSnapshot,
    EvidenceGateFailure,
    build_canonical_map,
    build_corpus_identity,
    content_hash,
    corpus_fingerprint,
    estimate_jaccard,
    exact_jaccard,
    minhash_signature,
    normalize_text,
    run_evidence_gate,
    snapshot_from_mapping,
)

TRIBAL_REPORT = (
    "The Arizona water settlements report describes allocations to tribal communities "
    "across the Colorado River basin, including Central Arizona Project deliveries and "
    "groundwater rights confirmed under the settlement acts."
)
GROUNDWATER_DOC = (
    "Active Management Areas regulate groundwater withdrawal in Phoenix, Tucson, Pinal, "
    "Prescott and Santa Cruz, under the 1980 Groundwater Management Act."
)


def docs(mapping):
    return snapshot_from_mapping(mapping)


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------
def test_normalization_collapses_whitespace_and_case():
    assert normalize_text("  The   CAP\nDelivers\twater ") == "the cap delivers water"


def test_normalization_applies_nfkc():
    """Unicode presentation variants are not content differences."""
    assert normalize_text("ﬁle") == normalize_text("file")
    assert normalize_text("Ａrizona") == normalize_text("arizona")


def test_normalization_does_not_merge_genuinely_different_text():
    """Conservative on purpose: L0 must be trusted when it says two things are the same."""
    assert normalize_text("acre-feet") != normalize_text("acre feet per year")
    assert normalize_text("Upper Basin") != normalize_text("Lower Basin")


def test_content_hash_is_stable_and_content_dependent():
    assert content_hash("The CAP delivers water.") == content_hash("the   cap delivers water.")
    assert content_hash("Upper Basin") != content_hash("Lower Basin")


# ---------------------------------------------------------------------------
# MinHash
# ---------------------------------------------------------------------------
def test_minhash_of_identical_text_is_identical():
    assert minhash_signature(TRIBAL_REPORT) == minhash_signature(TRIBAL_REPORT)


def test_minhash_estimates_exact_jaccard_closely():
    """The estimator must actually estimate the thing it claims to."""
    variant = TRIBAL_REPORT.replace("groundwater rights", "surface water rights")
    exact = exact_jaccard(TRIBAL_REPORT, variant)
    estimated = estimate_jaccard(
        minhash_signature(TRIBAL_REPORT, 256), minhash_signature(variant, 256)
    )
    assert estimated == pytest.approx(exact, abs=0.08)


def test_minhash_separates_unrelated_documents():
    score = estimate_jaccard(
        minhash_signature(TRIBAL_REPORT), minhash_signature(GROUNDWATER_DOC)
    )
    assert score < 0.1


def test_minhash_of_identical_text_estimates_one():
    assert estimate_jaccard(
        minhash_signature(TRIBAL_REPORT), minhash_signature(TRIBAL_REPORT)
    ) == 1.0


def test_estimate_rejects_mismatched_signature_lengths():
    with pytest.raises(ValueError, match="same length"):
        estimate_jaccard((1, 2, 3), (1, 2))


def test_short_documents_do_not_crash_the_shingler():
    """A one-word document is legitimate and must not raise."""
    assert len(minhash_signature("water")) == DEFAULT_MINHASH_PERMUTATIONS
    assert exact_jaccard("water", "water") == 1.0


def test_empty_text_is_handled():
    assert len(minhash_signature("")) == DEFAULT_MINHASH_PERMUTATIONS


# ---------------------------------------------------------------------------
# Canonical map: exact duplicates
# ---------------------------------------------------------------------------
def test_byte_identical_documents_are_merged_with_an_exact_proof():
    """The real corpus failure: the source site served the full report for each chapter."""
    corpus = docs(
        {
            "tribal_chapter_01.pdf": [TRIBAL_REPORT],
            "tribal_chapter_02.pdf": [TRIBAL_REPORT],
            "tribal_chapter_03.pdf": [TRIBAL_REPORT],
            "groundwater.pdf": [GROUNDWATER_DOC],
        }
    )
    canonical_map = build_canonical_map(corpus)

    assert canonical_map.document_count == 4
    assert canonical_map.canonical_count == 2
    assert len(canonical_map.shared_names) == 3

    exact_proofs = [p for p in canonical_map.proofs if p.method == "exact_hash"]
    assert len(exact_proofs) == 2  # three names, two merges into the anchor
    assert all(p.score == 1.0 for p in exact_proofs)
    assert all("byte-identical" in p.note for p in exact_proofs)


def test_every_merge_carries_a_proof():
    """The map is a set of claims with evidence, not a lookup table."""
    corpus = docs({"a.pdf": [TRIBAL_REPORT], "b.pdf": [TRIBAL_REPORT]})
    canonical_map = build_canonical_map(corpus)
    merged = [n for n in canonical_map.canonical_of if canonical_map.resolve(n) != n]
    assert len(merged) == len(canonical_map.proofs) == 1
    proof = canonical_map.proofs[0]
    assert proof.alias in merged and proof.method == "exact_hash" and proof.detected_at


def test_distinct_documents_are_not_merged():
    corpus = docs({"a.pdf": [TRIBAL_REPORT], "b.pdf": [GROUNDWATER_DOC]})
    canonical_map = build_canonical_map(corpus)
    assert canonical_map.canonical_count == 2
    assert canonical_map.proofs == []
    assert canonical_map.shared_names == []


def test_the_architecture_scenario_reproduces():
    """Eight chapters plus two unrelated titles serving one report, two chapters correct."""
    corpus = docs(
        {**{f"tribal_chapter_{i:02d}.pdf": [TRIBAL_REPORT] for i in range(1, 9)},
         "unrelated_title_a.pdf": [TRIBAL_REPORT],
         "unrelated_title_b.pdf": [TRIBAL_REPORT],
         "tribal_chapter_09.pdf": ["Chapter nine has its own distinct content about Yuma."],
         "tribal_chapter_10.pdf": ["Chapter ten covers the Gila River settlement separately."]}
    )
    canonical_map = build_canonical_map(corpus)
    assert len(canonical_map.shared_names) == 10
    assert canonical_map.canonical_count == 3  # one merged blob, plus two correct chapters
    assert len(canonical_map.exact_duplicate_groups) == 1
    assert len(canonical_map.exact_duplicate_groups[0]) == 10


# ---------------------------------------------------------------------------
# Canonical map: near duplicates
# ---------------------------------------------------------------------------
def test_near_duplicates_are_merged_with_a_scored_proof():
    revision = TRIBAL_REPORT + " Revised January 2024."
    corpus = docs({"report_v1.pdf": [TRIBAL_REPORT], "report_v2.pdf": [revision]})
    canonical_map = build_canonical_map(corpus, near_duplicate_threshold=0.8)

    assert canonical_map.canonical_count == 1
    proof = next(p for p in canonical_map.proofs if p.method == "minhash")
    assert 0.8 <= proof.score < 1.0


def test_near_duplicate_detection_can_be_switched_off():
    """The conservative setting, for runs where a wrong merge is worse than a missed one."""
    revision = TRIBAL_REPORT + " Revised January 2024."
    corpus = docs({"report_v1.pdf": [TRIBAL_REPORT], "report_v2.pdf": [revision]})
    canonical_map = build_canonical_map(corpus, detect_near_duplicates=False)
    assert canonical_map.canonical_count == 2


def test_a_high_threshold_does_not_merge_merely_related_documents():
    """Two water-policy documents share vocabulary; that is not sameness."""
    similar = (
        "Active Management Areas regulate groundwater withdrawal in Arizona under the "
        "1980 Act, with separate provisions for irrigation districts."
    )
    corpus = docs({"a.pdf": [GROUNDWATER_DOC], "b.pdf": [similar]})
    canonical_map = build_canonical_map(corpus, near_duplicate_threshold=0.9)
    assert canonical_map.canonical_count == 2


def test_threshold_must_be_a_probability():
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        build_canonical_map(docs({"a.pdf": ["x"]}), near_duplicate_threshold=1.5)


# ---------------------------------------------------------------------------
# Canonical map: determinism
# ---------------------------------------------------------------------------
def test_canonical_ids_do_not_depend_on_input_order():
    """A map that shuffles between runs would change the fingerprint without the corpus changing."""
    mapping = {
        "zeta.pdf": [TRIBAL_REPORT],
        "alpha.pdf": [TRIBAL_REPORT],
        "middle.pdf": [TRIBAL_REPORT],
        "other.pdf": [GROUNDWATER_DOC],
    }
    forward = build_canonical_map(docs(mapping))
    reversed_map = build_canonical_map(
        [DocumentSnapshot(name=n, chunks=tuple(c)) for n, c in reversed(list(mapping.items()))]
    )
    assert forward.canonical_of == reversed_map.canonical_of


def test_canonical_anchor_is_the_lexicographically_smallest_name():
    corpus = docs({"zeta.pdf": [TRIBAL_REPORT], "alpha.pdf": [TRIBAL_REPORT]})
    canonical_map = build_canonical_map(corpus)
    assert canonical_map.resolve("zeta.pdf") == "alpha.pdf"


def test_repeated_document_names_are_rejected():
    with pytest.raises(ValueError, match="repeated document names"):
        build_canonical_map(
            [DocumentSnapshot("a.pdf", ("x",)), DocumentSnapshot("a.pdf", ("y",))]
        )


def test_unknown_names_resolve_to_themselves():
    """A gold source absent from the corpus is a gate finding, not a crash."""
    canonical_map = build_canonical_map(docs({"a.pdf": [TRIBAL_REPORT]}))
    assert canonical_map.resolve("never_seen.pdf") == "never_seen.pdf"


# ---------------------------------------------------------------------------
# Alias resolver integration
# ---------------------------------------------------------------------------
class FakeResolver:
    """Stands in for CanonicalResolver from eval/corpus_identity.py."""

    def __init__(self, groups):
        self._groups = groups

    def resolve(self, name):
        for canonical, members in self._groups.items():
            if name in members:
                return canonical
        return name


def test_human_reviewed_aliases_merge_documents_with_different_content():
    """Filename identity catches what content identity cannot: an acronym and a full title."""
    corpus = docs(
        {
            "ADPAR.pdf": ["Short summary of the drought preparedness report."],
            "Arizona Drought Preparedness Report 2023.pdf": [
                "A considerably longer version of the same drought preparedness material."
            ],
        }
    )
    resolver = FakeResolver(
        {"adpar": ["ADPAR.pdf", "Arizona Drought Preparedness Report 2023.pdf"]}
    )
    canonical_map = build_canonical_map(corpus, alias_resolver=resolver)

    assert canonical_map.canonical_count == 1
    proof = next(p for p in canonical_map.proofs if p.method == "manual")
    assert "aliases.yaml" in proof.note


def test_alias_merges_do_not_duplicate_an_existing_content_merge():
    corpus = docs({"a.pdf": [TRIBAL_REPORT], "b.pdf": [TRIBAL_REPORT]})
    resolver = FakeResolver({"group": ["a.pdf", "b.pdf"]})
    canonical_map = build_canonical_map(corpus, alias_resolver=resolver)
    assert len(canonical_map.proofs) == 1
    assert canonical_map.proofs[0].method == "exact_hash"


# ---------------------------------------------------------------------------
# Fingerprint: the milestone-3 acceptance check
# ---------------------------------------------------------------------------
def a_corpus():
    return docs({"a.pdf": [TRIBAL_REPORT], "b.pdf": [GROUNDWATER_DOC]})


def fingerprint_of(corpus=None, **overrides):
    settings = {
        "chunker_version": "1.0.0",
        "chunk_size": 1000,
        "chunk_overlap": 200,
        "embedding_model": "text-embedding-3-small",
    }
    settings.update(overrides)
    corpus = corpus or a_corpus()
    identity, _ = build_corpus_identity(corpus, **settings)
    return identity.fingerprint


def test_fingerprint_is_stable_for_an_unchanged_corpus():
    assert fingerprint_of() == fingerprint_of()


def test_fingerprint_changes_on_chunk_size_change():
    """Milestone 3 acceptance check, stated exactly."""
    assert fingerprint_of(chunk_size=1000) != fingerprint_of(chunk_size=500)


@pytest.mark.parametrize(
    "field,value",
    [
        ("chunk_overlap", 0),
        ("chunker_version", "2.0.0"),
        ("embedding_model", "text-embedding-3-large"),
    ],
)
def test_fingerprint_changes_on_any_evidence_affecting_setting(field, value):
    assert fingerprint_of() != fingerprint_of(**{field: value})


def test_fingerprint_changes_when_content_changes():
    altered = docs({"a.pdf": [TRIBAL_REPORT + " Amended."], "b.pdf": [GROUNDWATER_DOC]})
    assert fingerprint_of() != fingerprint_of(altered)


def test_fingerprint_ignores_document_ordering():
    reordered = [DocumentSnapshot("b.pdf", (GROUNDWATER_DOC,)),
                 DocumentSnapshot("a.pdf", (TRIBAL_REPORT,))]
    assert fingerprint_of() == fingerprint_of(reordered)


def test_identity_counts_match_the_map():
    corpus = docs({"a.pdf": [TRIBAL_REPORT], "b.pdf": [TRIBAL_REPORT], "c.pdf": [GROUNDWATER_DOC]})
    identity, canonical_map = build_corpus_identity(
        corpus, "1.0.0", 1000, 200, "text-embedding-3-small"
    )
    assert identity.document_count == 3
    assert identity.canonical_count == 2
    assert identity.chunk_count == 3
    assert len(identity.proofs) == len(canonical_map.proofs)


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------
def test_a_clean_corpus_passes():
    corpus = docs({"a.pdf": [TRIBAL_REPORT], "b.pdf": [GROUNDWATER_DOC]})
    report = run_evidence_gate(corpus, {"a.pdf": ["q001"], "b.pdf": ["q002"]})
    assert report.is_clean
    assert report.redundant_names == 0


def test_exact_duplicates_fail_the_gate():
    corpus = docs({"a.pdf": [TRIBAL_REPORT], "b.pdf": [TRIBAL_REPORT]})
    with pytest.raises(EvidenceGateFailure, match="byte-identical"):
        run_evidence_gate(corpus, {"a.pdf": ["q001"]})


def test_a_missing_gold_source_fails_the_gate():
    """A question whose evidence does not exist cannot be scored, only guessed at."""
    corpus = docs({"a.pdf": [TRIBAL_REPORT]})
    with pytest.raises(EvidenceGateFailure, match="absent from the corpus"):
        run_evidence_gate(corpus, {"a.pdf": ["q001"], "ghost.pdf": ["q002", "q003"]})


def test_the_gate_names_the_affected_questions():
    corpus = docs({"a.pdf": [TRIBAL_REPORT]})
    report = run_evidence_gate(corpus, {"ghost.pdf": ["q002", "q003"]}, strict=False)
    assert report.affected_questions == ["q002", "q003"]
    assert not report.is_clean


def test_gold_sources_are_resolved_through_the_canonical_map():
    """The false miss that made recall@4 read 0.13 against a 0.60 keyword hit rate.

    The gold set names one alias; the corpus holds the document under another. Resolving both
    sides through the same map is what makes this a hit rather than a phantom absence.
    """
    corpus = docs({"ADPAR_2023_FINAL.pdf": [TRIBAL_REPORT]})
    resolver = FakeResolver({"adpar": ["ADPAR.pdf", "ADPAR_2023_FINAL.pdf"]})
    report = run_evidence_gate(
        corpus, {"ADPAR.pdf": ["q001"]}, alias_resolver=resolver, strict=False
    )
    assert report.missing_gold_sources == {}
    assert report.is_clean


def test_alias_resolution_does_not_hide_a_genuinely_missing_document():
    """The fix for phantom absence must not create phantom presence.

    A resolver is configured, but the cited document belongs to no group that any corpus
    document belongs to. It really is missing, and the gate must still say so.
    """
    corpus = docs({"ADPAR_2023_FINAL.pdf": [TRIBAL_REPORT]})
    resolver = FakeResolver({"adpar": ["ADPAR.pdf", "ADPAR_2023_FINAL.pdf"]})
    report = run_evidence_gate(
        corpus, {"never_acquired.pdf": ["q009"]}, alias_resolver=resolver, strict=False
    )
    assert report.missing_gold_sources == {"never_acquired.pdf": ["q009"]}


def test_alias_fallback_only_applies_to_names_outside_the_corpus():
    """A name present in the corpus resolves by content, never by alias group."""
    corpus = docs({"a.pdf": [TRIBAL_REPORT], "b.pdf": [GROUNDWATER_DOC]})
    resolver = FakeResolver({"everything": ["a.pdf", "b.pdf"]})
    canonical_map = build_canonical_map(corpus, alias_resolver=resolver)
    # The resolver merged them, so they share a canonical id, but each known name still maps
    # through canonical_of rather than through the group index.
    assert canonical_map.resolve("a.pdf") == canonical_map.canonical_of["a.pdf"]


def test_known_duplicates_can_be_judged_deliberately():
    """RQ5 judges the corrupted corpus on purpose, with the state recorded."""
    corpus = docs({"a.pdf": [TRIBAL_REPORT], "b.pdf": [TRIBAL_REPORT]})
    report = run_evidence_gate(corpus, {"a.pdf": ["q001"]}, allow_known_duplicates=True)
    assert len(report.exact_duplicate_groups) == 1
    assert not report.is_clean  # allowed through, still not clean


def test_non_strict_mode_reports_without_raising():
    corpus = docs({"a.pdf": [TRIBAL_REPORT], "b.pdf": [TRIBAL_REPORT]})
    report = run_evidence_gate(corpus, {"ghost.pdf": ["q1"]}, strict=False)
    assert report.exact_duplicate_groups and report.missing_gold_sources


def test_gate_report_serialises_and_summarises():
    corpus = docs({"a.pdf": [TRIBAL_REPORT], "b.pdf": [GROUNDWATER_DOC]})
    report = run_evidence_gate(corpus, {"a.pdf": ["q001"]})
    payload = report.to_dict()
    assert payload["is_clean"] is True and payload["fingerprint"] == report.fingerprint
    assert "corpus fingerprint" in report.summary()


def test_gate_fingerprint_matches_a_direct_computation():
    corpus = a_corpus()
    canonical_map = build_canonical_map(corpus)
    expected = corpus_fingerprint(
        corpus, canonical_map, "1.0.0", 1000, 200, "text-embedding-3-small"
    )
    report = run_evidence_gate(corpus, {}, canonical_map=canonical_map)
    assert report.fingerprint == expected
