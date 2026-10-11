"""
Propose replacements for gold_source_ids that are absent from the corpus.

WHY THIS EXISTS
---------------
19 gold_source_ids name documents that are not in the vector store. All 19 are
keys in application/mappings/knowledge_sources.py — a URL/citation mapping used
to render source links in the UI — so the benchmark was authored against the
wrong source of truth. Those questions can never score above zero recall.

METHOD, AND THE TRAP IT AVOIDS
------------------------------
The tempting fix is to run each question through the retriever and adopt
whatever documents come back as the new gold set. That is circular: it defines
ground truth as "whatever the system under test retrieves", which forces recall
to 1.0 and destroys the benchmark's ability to detect a regression forever.

Instead, candidates are found by LEXICAL evidence — distinctive terms taken
from the human-written gold_answer, matched against raw document text. Lexical
matching is a different mechanism from the dense-vector retriever being
evaluated, so a document scoring well here is evidence about the corpus, not
an echo of the retriever's opinion.

Output is a PROPOSAL for human review. Nothing is written to the dataset.

USAGE
    python eval/propose_gold_repairs.py
    python eval/propose_gold_repairs.py --json > proposals.json
"""

import argparse
import json
import os
import re
import sys
from collections import Counter
from typing import Dict, List, Set, Tuple

_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_script_dir)
_application_dir = os.path.join(_project_root, "application")
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
if _application_dir not in sys.path:
    sys.path.insert(0, _application_dir)

from eval.config import resolve_db_url
from eval.corpus_identity import build_resolver

NEGATIVE_CATEGORY = "out_of_scope_negative"

# Words too common in an Arizona-water corpus to discriminate between documents.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "in", "to", "for", "on", "at", "by",
    "is", "are", "was", "were", "be", "been", "it", "its", "that", "this",
    "these", "those", "as", "from", "with", "which", "has", "have", "had",
    "will", "would", "can", "could", "may", "might", "also", "such", "than",
    "then", "there", "their", "they", "you", "your", "we", "our", "not",
    "water", "arizona", "state", "states", "river", "supply", "use", "used",
    "using", "management", "plan", "report", "system", "area", "areas",
    "million", "acre", "feet", "per", "year", "years", "about", "more", "most",
    "other", "into", "over", "under", "between", "through", "during", "each",
}


def load_dataset() -> dict:
    with open(os.path.join(_script_dir, "benchmark_dataset.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def distinctive_terms(text: str, limit: int = 18) -> List[str]:
    """Pull discriminating terms from a gold answer.

    Prefers multi-word proper nouns and numerics, which identify a document far
    better than common topical vocabulary does.
    """
    phrases: List[str] = []

    # Capitalised multi-word phrases: "Central Arizona Project", "Lake Mead"
    for match in re.findall(r"\b([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){1,4})\b", text or ""):
        cleaned = match.strip()
        if len(cleaned) > 6:
            phrases.append(cleaned.lower())

    # Numbers with units or years: "1.5 million", "1980", "336-mile"
    for match in re.findall(r"\b\d[\d,\.]*(?:\s*(?:million|billion|percent|acre-feet|mile|miles))?\b", text or ""):
        cleaned = match.strip()
        if len(cleaned) >= 3:
            phrases.append(cleaned.lower())

    # Rare single words
    words = re.findall(r"\b[a-zA-Z]{6,}\b", (text or "").lower())
    for w in words:
        if w not in _STOPWORDS:
            phrases.append(w)

    seen: Set[str] = set()
    ordered: List[str] = []
    for p in phrases:
        if p not in seen:
            seen.add(p)
            ordered.append(p)
    return ordered[:limit]


def fetch_doc_text(db_url: str) -> Dict[str, str]:
    import psycopg
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT metadata->>'name', lower(string_agg(content, ' '))
                FROM rag_chunks
                WHERE metadata->>'name' IS NOT NULL
                GROUP BY 1;
            """)
            return {r[0]: (r[1] or "") for r in cur.fetchall()}


def score_documents(terms: List[str], doc_text: Dict[str, str], top_n: int = 3) -> List[Tuple[str, float, List[str]]]:
    """Rank documents by how many distinctive terms they contain.

    Score is the fraction of the question's distinctive terms present, with a
    mild length penalty so a very large document does not win simply by
    containing everything.
    """
    if not terms:
        return []

    scored: List[Tuple[str, float, List[str]]] = []
    for name, text in doc_text.items():
        if not text:
            continue
        hits = [t for t in terms if t in text]
        if not hits:
            continue
        coverage = len(hits) / len(terms)
        # Length penalty: normalise by log of document size.
        import math
        penalty = 1.0 + math.log10(max(len(text), 10) / 10000.0) * 0.15
        scored.append((name, coverage / max(penalty, 0.5), hits))

    scored.sort(key=lambda x: -x[1])
    return scored[:top_n]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--top", type=int, default=3)
    args = parser.parse_args()

    data = load_dataset()
    resolver = build_resolver()
    db_url = resolve_db_url()
    doc_text = fetch_doc_text(db_url)
    corpus_canonical = {resolver.resolve(n) for n in doc_text}

    proposals = []
    for q in data.get("questions", []):
        if q.get("category") == NEGATIVE_CATEGORY:
            continue

        gold_sources = q.get("gold_source_ids", []) or []
        absent = [s for s in gold_sources if resolver.resolve(s) not in corpus_canonical]
        if not absent:
            continue

        kept = [s for s in gold_sources if resolver.resolve(s) in corpus_canonical]
        terms = distinctive_terms(f"{q.get('question','')} {q.get('gold_answer','')}")
        candidates = score_documents(terms, doc_text, top_n=args.top)

        proposals.append({
            "id": q["id"],
            "question": q.get("question", ""),
            "category": q.get("category", ""),
            "absent_sources": absent,
            "kept_sources": kept,
            "distinctive_terms": terms,
            "candidates": [
                {"name": n, "score": round(s, 3), "matched_terms": h[:8]}
                for n, s, h in candidates
            ],
        })

    if args.json:
        print(json.dumps(proposals, indent=2))
        return 0

    print("=" * 78)
    print("GOLD SOURCE REPAIR PROPOSALS (review required — nothing written)")
    print("=" * 78)
    print(f"  {len(proposals)} question(s) reference absent documents.\n")

    for p in proposals:
        print(f"[{p['id']}] ({p['category']}) {p['question'][:66]}")
        print(f"   ABSENT : {', '.join(p['absent_sources'])}")
        if p["kept_sources"]:
            print(f"   KEEP   : {', '.join(p['kept_sources'])}")
        if not p["candidates"]:
            print(f"   -> NO CANDIDATE FOUND. Corpus may genuinely lack this content.")
        for c in p["candidates"]:
            print(f"   -> {c['score']:.3f}  {c['name'][:60]}")
            print(f"              matched: {', '.join(c['matched_terms'][:6])}")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
