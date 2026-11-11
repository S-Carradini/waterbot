"""
Corpus integrity preflight for the evaluation harness.

WHY THIS EXISTS
---------------
The suite previously reported recall@4 = 0.13 and nobody could tell whether
that meant "retrieval is bad" or "the benchmark is asking about documents that
aren't in the database". It was the latter, twice over:

  1. 34 of 59 gold document IDs (58%) were never retrieved once across all 60
     questions at k=10 — including every newly added PDF in application/newData/,
     which had never been ingested into the evaluated database. The suite's
     headline purpose is measuring the impact of new knowledge sources; it was
     scoring documents that did not exist.

  2. The corpus contains the same document under multiple filenames, so correct
     retrievals were scored as misses (see corpus_identity.py).

Both failures are silent: they produce plausible-looking low scores rather than
an error. A metric that cannot distinguish "the system failed" from "the
measurement is broken" is worse than no metric, because it gets acted upon.

This module makes that distinction explicit and fails loudly before any
expensive LLM calls are made.

USAGE
-----
    python eval/preflight.py                    # integrity gate
    python eval/preflight.py --propose-aliases  # discovery report (read-only)
    python eval/preflight.py --json             # machine-readable, for CI
    python eval/preflight.py --warn-only        # report but always exit 0

Exit codes: 0 = pass (or warn-only), 1 = integrity failure, 2 = cannot connect.
"""

import argparse
import hashlib
import json
import os
import sys
from typing import Dict, List, Set

_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_script_dir)
_application_dir = os.path.join(_project_root, "application")
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
if _application_dir not in sys.path:
    sys.path.insert(0, _application_dir)

from eval.config import resolve_db_url
from eval.corpus_identity import (
    CanonicalResolver,
    build_resolver,
    propose_alias_groups,
)


def load_gold_sources() -> Dict[str, List[str]]:
    """Map gold_source_id -> list of question ids that depend on it."""
    dataset_path = os.path.join(_script_dir, "benchmark_dataset.json")
    with open(dataset_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    gold: Dict[str, List[str]] = {}
    for q in data.get("questions", []):
        # Quarantined questions are knowingly unscored (no corpus document
        # genuinely sources them), so their absent gold ids must not fail the
        # integrity gate — that would make the gate permanently red for a
        # condition already recorded and accepted in the dataset.
        if q.get("excluded_from_scoring"):
            continue
        for src in q.get("gold_source_ids", []) or []:
            gold.setdefault(src, []).append(q["id"])
    return gold


def fetch_corpus_names(db_url: str) -> Dict[str, object]:
    """Read distinct document names, chunk counts and locales from rag_chunks."""
    try:
        import psycopg
    except ImportError as e:
        raise RuntimeError(
            "psycopg is required for preflight. Install the application "
            "requirements, or run with --skip-db to check only the dataset."
        ) from e

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COALESCE(metadata->>'name', ''), COUNT(*)
                FROM rag_chunks
                GROUP BY 1
                ORDER BY 1;
                """
            )
            rows = cur.fetchall()

            cur.execute("SELECT COALESCE(locale, ''), COUNT(*) FROM rag_chunks GROUP BY 1;")
            locales = dict(cur.fetchall())

    names = {r[0]: r[1] for r in rows if r[0]}
    unnamed_chunks = sum(r[1] for r in rows if not r[0])

    return {
        "names": names,
        "unnamed_chunks": unnamed_chunks,
        "locales": locales,
        "total_chunks": sum(names.values()) + unnamed_chunks,
    }


def fetch_content_duplication(db_url: str) -> List[dict]:
    """Find groups of differently-named documents holding IDENTICAL content.

    WHY THIS CHECK EXISTS
    ---------------------
    Filename-based alias discovery cannot tell these two situations apart:

      A) One document ingested under several names (a genuine alias).
         e.g. ADPAR.pdf / ADPAR_2023_FINAL.pdf

      B) Several DIFFERENT documents whose stored content is identical,
         because ingestion wrote one document's text under many names.
         e.g. all eight Tribal Water Study chapters (Ute, SUIT, UMUT,
         Jicarilla, Navajo, Ft. Mojave, CRIT, Quechan) share one identical
         773-chunk body.

    (A) is a measurement problem, fixed in aliases.yaml. (B) is corpus
    corruption that also affects production answers, and must NEVER be
    encoded as an alias — doing so would tell the evaluator that Ute and
    Quechan are the same document and bake the corruption into the metric.

    Only a human can tell A from B, because it depends on what the filenames
    are supposed to mean. This check surfaces the groups; it does not resolve
    them.
    """
    import psycopg

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH doc AS (
                    SELECT metadata->>'name' AS name, content_hash
                    FROM rag_chunks
                    WHERE content_hash IS NOT NULL AND metadata->>'name' IS NOT NULL
                    GROUP BY 1, 2
                ),
                sig AS (
                    SELECT name,
                           count(*) AS n_chunks,
                           md5(string_agg(content_hash, ',' ORDER BY content_hash)) AS fp
                    FROM doc GROUP BY 1
                )
                SELECT fp, max(n_chunks), count(*), array_agg(name ORDER BY name)
                FROM sig
                GROUP BY fp
                HAVING count(*) > 1
                ORDER BY count(*) * max(n_chunks) DESC;
                """
            )
            rows = cur.fetchall()

    return [
        {
            "fingerprint": r[0],
            "chunks_each": r[1],
            "document_count": r[2],
            "documents": list(r[3]),
            "redundant_chunks": (r[2] - 1) * r[1],
        }
        for r in rows
    ]


def redundant_docs_delta(duplication: List[dict]) -> int:
    """How many document names collapse away if each cluster were one document."""
    return sum(d["document_count"] - 1 for d in duplication)


def corpus_fingerprint(names: Dict[str, int]) -> str:
    """Stable hash of corpus composition, for the run manifest.

    Lets any historical result be tied to the exact corpus that produced it,
    so a score change can be attributed to the corpus rather than the code.
    """
    payload = "\n".join(f"{n}:{c}" for n, c in sorted(names.items()))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def run_preflight(db_url: str = None, propose: bool = False) -> dict:
    db_url = resolve_db_url(db_url)
    corpus = fetch_corpus_names(db_url)
    corpus_names: Dict[str, int] = corpus["names"]

    resolver = build_resolver()
    gold = load_gold_sources()

    # Resolve both sides through the same canonical mapping.
    corpus_canonical: Set[str] = {resolver.resolve(n) for n in corpus_names}

    missing: Dict[str, List[str]] = {}
    present: Dict[str, str] = {}
    for src, question_ids in gold.items():
        canonical = resolver.resolve(src)
        if canonical in corpus_canonical:
            present[src] = canonical
        else:
            missing[src] = question_ids

    affected_questions = sorted({q for qs in missing.values() for q in qs})

    duplication = fetch_content_duplication(db_url)
    docs_in_dup_clusters = sum(d["document_count"] for d in duplication)
    redundant_chunks = sum(d["redundant_chunks"] for d in duplication)

    result = {
        "db_url_prefix": db_url[:40],
        "corpus": {
            "distinct_documents": len(corpus_names),
            "canonical_documents": len(corpus_canonical),
            "total_chunks": corpus["total_chunks"],
            "unnamed_chunks": corpus["unnamed_chunks"],
            "locales": corpus["locales"],
            "fingerprint": corpus_fingerprint(corpus_names),
        },
        "gold_sources": {
            "total": len(gold),
            "present": len(present),
            "missing": len(missing),
            "missing_detail": {k: v for k, v in sorted(missing.items())},
            "affected_questions": affected_questions,
        },
        "aliases": {
            "groups_active": resolver.group_count,
            "groups_unverified": len(resolver.unverified_groups),
            "unverified_detail": resolver.unverified_groups,
        },
        "content_duplication": {
            "cluster_count": len(duplication),
            "documents_affected": docs_in_dup_clusters,
            "redundant_chunks": redundant_chunks,
            "truly_distinct_documents": len(corpus_names) - redundant_docs_delta(duplication),
            "clusters": duplication,
        },
        "passed": len(missing) == 0,
    }

    if propose:
        candidates = propose_alias_groups(
            set(corpus_names) | set(gold), threshold=0.80, known=resolver
        )
        result["proposals"] = candidates

    return result


def print_human(result: dict) -> None:
    c = result["corpus"]
    g = result["gold_sources"]
    a = result["aliases"]

    print("=" * 72)
    print("CORPUS PREFLIGHT")
    print("=" * 72)
    print(f"  Database          : {result['db_url_prefix']}...")
    print(f"  Chunks            : {c['total_chunks']:,}")
    print(f"  Distinct documents: {c['distinct_documents']} "
          f"({c['canonical_documents']} after alias resolution)")
    print(f"  Locales           : {c['locales']}")
    print(f"  Corpus fingerprint: {c['fingerprint']}")
    if c["unnamed_chunks"]:
        print(f"  WARN: {c['unnamed_chunks']:,} chunks have no metadata['name'] "
              f"and can never be credited to any gold source.")

    print()
    print(f"  Alias groups active   : {a['groups_active']}")
    if a["groups_unverified"]:
        print(f"  WARN: {a['groups_unverified']} alias group(s) are UNVERIFIED. "
              f"They are active and therefore affect recall.")
        print(f"        Review eval/aliases.yaml and set verified: true.")

    dup = result.get("content_duplication", {})
    if dup.get("cluster_count"):
        print()
        print(f"  CONTENT DUPLICATION: {dup['documents_affected']} document name(s) "
              f"across {dup['cluster_count']} cluster(s) hold identical content")
        print(f"    ({dup['redundant_chunks']:,} redundant chunks; "
              f"~{dup['truly_distinct_documents']} truly distinct documents)")
        print(f"    Each cluster is EITHER an alias (same doc, many names -> aliases.yaml)")
        print(f"    OR corpus corruption (different docs, same stored text -> re-ingest).")
        print(f"    Only a human can tell which. Largest clusters:")
        for cluster in dup["clusters"][:5]:
            names = cluster["documents"]
            shown = ", ".join(n[:44] for n in names[:3])
            more = f" (+{len(names) - 3} more)" if len(names) > 3 else ""
            print(f"      [{cluster['document_count']} docs x {cluster['chunks_each']} chunks] {shown}{more}")

    print()
    print(f"  Gold sources: {g['present']}/{g['total']} present in corpus")

    if g["missing"]:
        print()
        print(f"  FAIL: {g['missing']} gold source(s) are NOT in the corpus.")
        print(f"        {len(g['affected_questions'])} benchmark question(s) cannot")
        print(f"        possibly be answered correctly. Any recall figure computed")
        print(f"        now measures corpus completeness, not retrieval quality.")
        print()
        for src, qids in list(g["missing_detail"].items())[:40]:
            print(f"          - {src}  (questions: {', '.join(qids)})")
        if len(g["missing_detail"]) > 40:
            print(f"          ... and {len(g['missing_detail']) - 40} more")
        print()
        print("  Fix: ingest the missing documents, or correct the gold_source_ids")
        print("       in benchmark_dataset.json, or add an alias in aliases.yaml.")

    if "proposals" in result:
        p = result["proposals"]
        print()
        print("=" * 72)
        print("ALIAS DISCOVERY (report only — nothing was modified)")
        print("=" * 72)
        print(f"\n  Confident candidate groups: {len(p['confident_groups'])}")
        for group in p["confident_groups"]:
            print(f"    - {' | '.join(group)}")
        print(f"\n  Needs human review: {len(p['review_pairs'])} pair(s)")
        for a_, b_, score in p["review_pairs"][:20]:
            print(f"    - {score}  {a_}  <->  {b_}")
        if len(p["review_pairs"]) > 20:
            print(f"    ... and {len(p['review_pairs']) - 20} more")
        print(f"\n  Numbered series (NOT aliases, auto-rejected): "
              f"{len(p['series_families'])} family/families")
        for family in p["series_families"]:
            print(f"    - {family[0]} ... (+{len(family) - 1} more)")

    print()
    print("=" * 72)
    print("PASS: corpus integrity OK" if result["passed"] else "FAIL: corpus integrity check failed")
    print("=" * 72)


def main() -> int:
    parser = argparse.ArgumentParser(description="Corpus integrity preflight")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--propose-aliases", action="store_true",
                        help="report candidate alias groups (read-only)")
    parser.add_argument("--warn-only", action="store_true",
                        help="report problems but always exit 0")
    args = parser.parse_args()

    try:
        result = run_preflight(propose=args.propose_aliases)
    except Exception as e:
        msg = f"Preflight could not inspect the corpus: {e}"
        if args.json:
            print(json.dumps({"error": str(e), "passed": False}, indent=2))
        else:
            print(f"ERROR: {msg}")
            print("Is the local Docker database running? (docker compose up -d)")
        return 2

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print_human(result)

    if args.warn_only:
        return 0
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
