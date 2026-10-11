"""
Tests for the evaluation harness's own metric mathematics.

WHY THIS EXISTS
---------------
The suite gates merges on Recall@k, NDCG@k and MRR, and until now none of
those implementations had a single test. A bug in this arithmetic silently
corrupts every number the suite has ever produced and every decision made
from them — the worst possible failure mode, because it looks like data.

These tests need no database, no API key and no network, so they run on every
commit. Expected values are computed by hand in the docstrings rather than
snapshotted from the implementation, so the tests would fail if the
implementation were wrong today.

Run with:  pytest eval/tests/ -v
"""
import math
import os
import sys

import pytest

_here = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(os.path.dirname(_here))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from eval.corpus_identity import (  # noqa: E402
    CanonicalResolver,
    classify_pair,
    normalize_name,
    propose_alias_groups,
    similarity,
)


def calculate_metrics(*args, **kwargs):
    """Import lazily so a missing app dependency doesn't collect-error the file.

    retrieval_metrics imports the production pgvector store at module scope.
    """
    from eval.retrieval_metrics import calculate_metrics as _impl
    return _impl(*args, **kwargs)


K = [1, 3, 4, 5, 10]


# ---------------------------------------------------------------------------
# Recall / Precision
# ---------------------------------------------------------------------------
class TestRecallPrecision:
    def test_perfect_retrieval_at_rank_one(self):
        m = calculate_metrics(["a.pdf"], ["a.pdf"], [1])
        assert m["recall@1"] == 1.0
        assert m["precision@1"] == 1.0
        assert m["mrr"] == 1.0

    def test_total_miss_scores_zero(self):
        m = calculate_metrics(["x.pdf", "y.pdf"], ["a.pdf"], [1, 3])
        assert m["recall@1"] == 0.0
        assert m["recall@3"] == 0.0
        assert m["mrr"] == 0.0

    def test_partial_recall_with_two_gold_docs(self):
        """1 of 2 gold docs found -> recall 0.5; 1 relevant in top 4 -> precision 0.25."""
        m = calculate_metrics(["a.pdf", "x.pdf", "y.pdf", "z.pdf"], ["a.pdf", "b.pdf"], [4])
        assert m["recall@4"] == 0.5
        assert m["precision@4"] == 0.25

    def test_recall_never_exceeds_one_with_duplicate_chunks(self):
        """Multiple chunks from the same document must count once.

        This is the property that keeps recall in [0, 1]; without set-based
        matching, 4 chunks of the single gold doc would give recall 4.0.
        """
        m = calculate_metrics(["a.pdf"] * 4, ["a.pdf"], [4])
        assert m["recall@4"] == 1.0

    def test_recall_is_monotonic_in_k(self):
        retrieved = ["x.pdf", "y.pdf", "z.pdf", "a.pdf", "b.pdf"]
        m = calculate_metrics(retrieved, ["a.pdf", "b.pdf"], K)
        recalls = [m[f"recall@{k}"] for k in K]
        assert recalls == sorted(recalls), "recall@k must not decrease as k grows"

    def test_no_gold_sources_returns_no_metrics(self):
        """Out-of-scope negatives have no gold docs; retrieval metrics don't apply."""
        assert calculate_metrics(["a.pdf"], [], K) == {}


# ---------------------------------------------------------------------------
# MRR
# ---------------------------------------------------------------------------
class TestMRR:
    @pytest.mark.parametrize("position,expected", [(0, 1.0), (1, 0.5), (2, 1 / 3), (3, 0.25)])
    def test_reciprocal_of_first_relevant_rank(self, position, expected):
        retrieved = ["x.pdf"] * 5
        retrieved[position] = "a.pdf"
        m = calculate_metrics(retrieved, ["a.pdf"], [5])
        assert m["mrr"] == pytest.approx(expected)

    def test_uses_first_hit_not_later_ones(self):
        m = calculate_metrics(["a.pdf", "b.pdf"], ["a.pdf", "b.pdf"], [2])
        assert m["mrr"] == 1.0


# ---------------------------------------------------------------------------
# NDCG
# ---------------------------------------------------------------------------
class TestNDCG:
    def test_perfect_ranking_is_one(self):
        m = calculate_metrics(["a.pdf", "b.pdf", "x.pdf"], ["a.pdf", "b.pdf"], [2])
        assert m["ndcg@2"] == pytest.approx(1.0)

    def test_ranking_order_matters(self):
        """Same documents retrieved, better order must score strictly higher."""
        good = calculate_metrics(["a.pdf", "x.pdf", "y.pdf", "z.pdf"], ["a.pdf"], [4])
        bad = calculate_metrics(["x.pdf", "y.pdf", "z.pdf", "a.pdf"], ["a.pdf"], [4])
        assert good["ndcg@4"] > bad["ndcg@4"]
        # Recall cannot see the difference — that is exactly why NDCG is here.
        assert good["recall@4"] == bad["recall@4"]

    def test_known_value_single_hit_at_rank_two(self):
        """DCG = 1/log2(3); IDCG = 1/log2(2) = 1  ->  NDCG = 0.6309."""
        m = calculate_metrics(["x.pdf", "a.pdf"], ["a.pdf"], [2])
        assert m["ndcg@2"] == pytest.approx(1 / math.log2(3))

    def test_bounded_between_zero_and_one(self):
        m = calculate_metrics(["a.pdf", "b.pdf", "c.pdf"], ["a.pdf", "b.pdf", "c.pdf"], K)
        for k in K:
            assert 0.0 <= m[f"ndcg@{k}"] <= 1.0

    def test_duplicate_chunks_of_one_document_stay_bounded(self):
        """Regression: NDCG counted every chunk, not every document.

        Retrieval returns chunks and several usually come from the same
        document, so this is the common case, not an edge case. Counting each
        chunk as a separate hit gave ndcg@4 = 2.56 for a single gold document
        — and the per-category average reached 1.1248 on a real run before
        this was caught.
        """
        m = calculate_metrics(["a.pdf"] * 4, ["a.pdf"], [4])
        assert m["ndcg@4"] == pytest.approx(1.0)
        assert m["recall@4"] == 1.0  # recall was always right; NDCG disagreed

    @pytest.mark.parametrize("retrieved,gold", [
        (["a.pdf"] * 10, ["a.pdf"]),
        (["a.pdf", "a.pdf", "b.pdf", "b.pdf"], ["a.pdf", "b.pdf"]),
        (["a.pdf", "x.pdf", "a.pdf", "b.pdf"], ["a.pdf", "b.pdf"]),
        (["a.pdf"] * 3 + ["b.pdf"] * 3, ["a.pdf", "b.pdf", "c.pdf"]),
    ])
    def test_never_exceeds_one_with_repeated_sources(self, retrieved, gold):
        m = calculate_metrics(retrieved, gold, K)
        for k in K:
            assert 0.0 <= m[f"ndcg@{k}"] <= 1.0, f"ndcg@{k}={m[f'ndcg@{k}']}"

    def test_first_occurrence_rank_is_what_counts(self):
        """A gold doc appearing early beats the same doc appearing late."""
        early = calculate_metrics(["a.pdf", "x.pdf", "x.pdf"], ["a.pdf"], [3])
        late = calculate_metrics(["x.pdf", "x.pdf", "a.pdf"], ["a.pdf"], [3])
        assert early["ndcg@3"] > late["ndcg@3"]


# ---------------------------------------------------------------------------
# Keyword hit rate
# ---------------------------------------------------------------------------
class TestKeywordHitRate:
    def test_counts_each_keyword_once_across_all_chunks(self):
        m = calculate_metrics(
            ["a.pdf"], ["a.pdf"], [1],
            retrieved_texts=["the allocation is 1.5 maf", "unrelated text"],
            gold_passage_keywords=["1.5 maf", "missing phrase"],
        )
        assert m["keyword_hit_rate"] == 0.5

    def test_is_case_insensitive(self):
        m = calculate_metrics(
            ["a.pdf"], ["a.pdf"], [1],
            retrieved_texts=["The Central Arizona Project"],
            gold_passage_keywords=["central arizona project"],
        )
        assert m["keyword_hit_rate"] == 1.0

    def test_absent_when_no_keywords_supplied(self):
        m = calculate_metrics(["a.pdf"], ["a.pdf"], [1], retrieved_texts=["text"])
        assert "keyword_hit_rate" not in m


# ---------------------------------------------------------------------------
# Canonical identity — the fix for the aliased-filename scoring bug
# ---------------------------------------------------------------------------
class TestNormalization:
    @pytest.mark.parametrize("raw,expected", [
        ("ADPAR.pdf", "adpar"),
        ("ADPAR_2023_FINAL.pdf", "adpar 2023"),
        ("Brief History of Water Resources-2.pdf", "brief history of water resources 2"),
        ("Lower_Colorado_River_Water_Quality_Partnership.pdf",
         "lower colorado river water quality partnership"),
        ("Report (17).pdf", "report"),
    ])
    def test_normalizes_formatting_noise(self, raw, expected):
        assert normalize_name(raw) == expected

    def test_case_and_separator_variants_collapse(self):
        assert normalize_name("IMPACTS_OF_SHORTAGE.pdf") == normalize_name("impacts-of-shortage.pdf")

    def test_meaningful_tokens_are_never_dropped(self):
        """'City' distinguishes these names; normalization must not erase it."""
        assert normalize_name("Lake Havasu Water Savers.pdf") != normalize_name(
            "Lake Havasu City Water Savers.pdf"
        )


class TestCanonicalResolver:
    def _resolver(self):
        return CanonicalResolver([
            {
                "canonical_id": "ADPAR_2023_FINAL.pdf",
                "verified": False,
                "members": ["ADPAR.pdf", "ADPAR_2023_FINAL.pdf"],
            },
            {
                "canonical_id": "Tucson One Water.pdf",
                "verified": True,
                "members": ["Tucson One Water.pdf", "Tucson One Water-2.pdf"],
            },
        ])

    def test_aliases_resolve_to_the_same_id(self):
        r = self._resolver()
        assert r.resolve("ADPAR.pdf") == r.resolve("ADPAR_2023_FINAL.pdf")

    def test_unknown_names_resolve_to_themselves(self):
        r = self._resolver()
        assert r.resolve("Totally Unrelated.pdf") == normalize_name("Totally Unrelated.pdf")

    def test_distinct_documents_stay_distinct(self):
        r = self._resolver()
        assert r.resolve("ADPAR.pdf") != r.resolve("Tucson One Water.pdf")

    def test_resolves_full_paths_to_basename(self):
        r = self._resolver()
        assert r.resolve("/data/docs/ADPAR.pdf") == r.resolve("ADPAR.pdf")

    def test_unverified_groups_are_reported(self):
        r = self._resolver()
        assert r.unverified_groups == ["ADPAR_2023_FINAL.pdf"]

    def test_resolve_all_preserves_order_and_duplicates(self):
        """MRR and NDCG are rank-sensitive, so resolution must not reorder or dedupe."""
        r = self._resolver()
        out = r.resolve_all(["x.pdf", "ADPAR.pdf", "x.pdf"])
        assert len(out) == 3
        assert out[0] == out[2]
        assert out[1] == r.resolve("ADPAR_2023_FINAL.pdf")

    def test_empty_resolver_behaves_like_plain_normalization(self):
        r = CanonicalResolver([])
        assert r.resolve("Anything.pdf") == normalize_name("Anything.pdf")


class TestResolverEffectOnScoring:
    def test_alias_turns_a_false_miss_into_a_hit(self):
        """The exact bug: gold names one alias, retrieval returns another."""
        resolver = CanonicalResolver([{
            "canonical_id": "ADPAR_2023_FINAL.pdf",
            "verified": True,
            "members": ["ADPAR.pdf", "ADPAR_2023_FINAL.pdf"],
        }])
        retrieved, gold = ["ADPAR.pdf"], ["ADPAR_2023_FINAL.pdf"]

        assert calculate_metrics(retrieved, gold, [1])["recall@1"] == 0.0
        assert calculate_metrics(retrieved, gold, [1], resolver=resolver)["recall@1"] == 1.0

    def test_resolver_does_not_create_hits_for_unrelated_documents(self):
        resolver = CanonicalResolver([{
            "canonical_id": "ADPAR_2023_FINAL.pdf",
            "verified": True,
            "members": ["ADPAR.pdf", "ADPAR_2023_FINAL.pdf"],
        }])
        m = calculate_metrics(["Unrelated.pdf"], ["ADPAR.pdf"], [1], resolver=resolver)
        assert m["recall@1"] == 0.0


# ---------------------------------------------------------------------------
# Alias discovery safety — must never merge a numbered series
# ---------------------------------------------------------------------------
class TestAliasDiscoverySafety:
    @pytest.mark.parametrize("a,b", [
        ("2018_Legislative_Session_Summary_-_Water_Bills.pdf",
         "2019_Legislative_Session_Summary_-_Water_Bills.pdf"),
        ("Ch.-5.1-Ute-Current-Future-Water-Use.pdf",
         "Ch.-5.2-SUIT-Current-Future-Water-Use.pdf"),
    ])
    def test_numerically_differing_series_are_classified_distinct(self, a, b):
        assert classify_pair(a, b) == "distinct_series"

    @pytest.mark.parametrize("a,b", [
        # Differ by basin name, not by number, so the numeric rule does not
        # apply — but they are still distinct documents and must never be
        # merged automatically.
        ("ADWR_Supply_Demand_Agua_Fria_Basin_2024.pdf",
         "ADWR_Supply_Demand_Big_Sandy_Basin_2024.pdf"),
        ("Phoenix Fifth Active Management Plan.pdf",
         "Pinal Fifth Active Management Plan.pdf"),
    ])
    def test_similar_but_distinct_documents_are_never_auto_merged(self, a, b):
        """The safety property that matters: no silent merge.

        'needs_review' is the correct verdict here — a human decides. What
        must never happen is 'alias_confident', which would union them and
        inflate recall by treating different basins/AMAs as one document.
        """
        assert classify_pair(a, b) != "alias_confident"
        assert propose_alias_groups([a, b], threshold=0.80)["confident_groups"] == []

    @pytest.mark.parametrize("a,b", [
        ("Tucson One Water.pdf", "Tucson One Water-2.pdf"),
        ("ADPAR.pdf", "ADPAR_2023_FINAL.pdf"),
        ("Lower Colorado River Water Quality Partnership.pdf",
         "Lower_Colorado_River_Water_Quality_Partnership.pdf"),
    ])
    def test_formatting_variants_are_confident_aliases(self, a, b):
        assert classify_pair(a, b) == "alias_confident"

    def test_different_counties_require_human_review(self):
        verdict = classify_pair(
            "Arizona_Water_Factsheet_Pima_County.pdf",
            "Arizona_Water_Factsheet_Gila_County.pdf",
        )
        assert verdict == "needs_review"

    def test_series_never_enters_confident_groups(self):
        """Regression guard for the transitive-blob failure.

        At threshold 0.80 a naive single-link clustering merged all eight
        Legislative Session Summaries into one 'document', which would have
        inflated recall by treating distinct years as interchangeable.
        """
        names = [f"{y}_Legislative_Session_Summary_-_Water_Bills.pdf"
                 for y in range(2018, 2026)]
        result = propose_alias_groups(names, threshold=0.80)
        assert result["confident_groups"] == []
        assert len(result["series_families"]) == 1
        assert len(result["series_families"][0]) == 8

    def test_real_alias_is_still_discovered(self):
        result = propose_alias_groups(
            ["Tucson One Water.pdf", "Tucson One Water-2.pdf", "Unrelated Doc.pdf"],
            threshold=0.80,
        )
        assert result["confident_groups"] == [["Tucson One Water-2.pdf", "Tucson One Water.pdf"]]

    def test_known_aliases_are_not_re_proposed(self):
        resolver = CanonicalResolver([{
            "canonical_id": "Tucson One Water.pdf",
            "verified": True,
            "members": ["Tucson One Water.pdf", "Tucson One Water-2.pdf"],
        }])
        result = propose_alias_groups(
            ["Tucson One Water.pdf", "Tucson One Water-2.pdf"],
            threshold=0.80,
            known=resolver,
        )
        assert result["confident_groups"] == []

    def test_similarity_is_symmetric_and_self_identical(self):
        a, b = "ADPAR.pdf", "ADPAR_2023_FINAL.pdf"
        assert similarity(a, b) == similarity(b, a)
        assert similarity(a, a) == 1.0


# ---------------------------------------------------------------------------
# Remote-database guard
# ---------------------------------------------------------------------------
class TestRemoteDatabaseGuard:
    """EVAL_DATABASE_URL pointed at the production Railway proxy, so the whole
    harness read from live data and any ingest script could have written to it.
    These tests pin the guard that now prevents that by default."""

    PROD = "postgresql://u:p@gondola.proxy.rlwy.net:30189/railway"
    LOCAL = "postgresql://postgres:password@localhost:5432/waterbot_local"

    @pytest.mark.parametrize("url,expected", [
        ("postgresql://u:p@localhost:5432/db", True),
        ("postgresql://u:p@127.0.0.1:5432/db", True),
        ("postgresql://u:p@host.docker.internal:5432/db", True),
        ("postgresql://u:p@db:5432/db", True),
        ("postgresql://u:p@gondola.proxy.rlwy.net:30189/railway", False),
        ("postgresql://u:p@postgres-jik5.railway.internal:5432/railway", False),
    ])
    def test_local_host_detection(self, url, expected):
        from eval.config import is_local_url
        assert is_local_url(url) is expected

    def test_remote_override_is_refused_by_default(self):
        from eval.config import resolve_db_url, RemoteDatabaseBlocked
        with pytest.raises(RemoteDatabaseBlocked):
            resolve_db_url(self.PROD, allow_remote=False)

    def test_remote_is_allowed_with_explicit_opt_in(self):
        from eval.config import resolve_db_url
        assert resolve_db_url(self.PROD, allow_remote=True) == self.PROD

    def test_local_override_always_passes(self):
        from eval.config import resolve_db_url
        assert resolve_db_url(self.LOCAL, allow_remote=False) == self.LOCAL

    def test_remote_env_var_is_refused_by_default(self, monkeypatch):
        from eval.config import resolve_db_url, RemoteDatabaseBlocked
        monkeypatch.setenv("EVAL_DATABASE_URL", self.PROD)
        monkeypatch.delenv("EVAL_ALLOW_REMOTE", raising=False)
        with pytest.raises(RemoteDatabaseBlocked):
            resolve_db_url()

    def test_eval_allow_remote_env_var_opts_in(self, monkeypatch):
        from eval.config import resolve_db_url
        monkeypatch.setenv("EVAL_DATABASE_URL", self.PROD)
        monkeypatch.setenv("EVAL_ALLOW_REMOTE", "1")
        assert resolve_db_url() == self.PROD
