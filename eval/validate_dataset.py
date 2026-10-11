"""
Benchmark dataset validator.

WHY THIS EXISTS
---------------
benchmark_dataset.json is the ground truth every score is computed against,
and it shipped marked "DRAFT — REQUIRES HUMAN REVIEW BEFORE USE" while being
used as a merge gate. Its own _meta documented an assumption that was never
checked — that gold_source_ids match chunk metadata['name'] — and that
assumption was false for 19 of 59 documents, because the IDs were authored
from knowledge_sources.py (a 503-entry URL/citation mapping used to render
source links in the UI) rather than from the vector store (366 documents).

A benchmark nobody validates is not ground truth, it is an opinion. This
module checks the dataset structurally AND against the live corpus, so the
gold set has to earn the authority the gates give it.

Checks are graded:
  ERROR — makes scores wrong or uninterpretable. Blocks.
  WARN  — quality/statistical-power concern. Does not block.
  INFO  — informational.

USAGE
    python eval/validate_dataset.py             # structural + corpus checks
    python eval/validate_dataset.py --no-db     # structural checks only
    python eval/validate_dataset.py --json      # machine-readable
"""

import argparse
import json
import os
import re
import sys
from collections import Counter
from typing import Dict, List, Optional, Set

_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_script_dir)
_application_dir = os.path.join(_project_root, "application")
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
if _application_dir not in sys.path:
    sys.path.insert(0, _application_dir)

from eval.corpus_identity import build_resolver

NEGATIVE_CATEGORY = "out_of_scope_negative"
REQUIRED_FIELDS = ["id", "question", "gold_answer", "gold_source_ids", "category"]

# Minimum questions per category to support reporting a per-category mean.
# Below this, a single question moves the category average by >12 points.
MIN_CATEGORY_N = 8


class Finding:
    def __init__(self, severity: str, code: str, message: str, question_id: str = None):
        self.severity = severity
        self.code = code
        self.message = message
        self.question_id = question_id

    def as_dict(self) -> dict:
        return {
            "severity": self.severity,
            "code": self.code,
            "question_id": self.question_id,
            "message": self.message,
        }

    def __str__(self) -> str:
        where = f"[{self.question_id}] " if self.question_id else ""
        return f"{self.severity:5s} {self.code:26s} {where}{self.message}"


def load_dataset(path: str = None) -> dict:
    path = path or os.path.join(_script_dir, "benchmark_dataset.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _normalize_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def check_structure(data: dict) -> List[Finding]:
    """Schema, uniqueness, category integrity, negative-set conventions."""
    findings: List[Finding] = []
    questions = data.get("questions", [])

    if not questions:
        findings.append(Finding("ERROR", "EMPTY_DATASET", "No questions found."))
        return findings

    meta = data.get("_meta", {})
    status = str(meta.get("status", ""))
    if "DRAFT" in status.upper() or "REQUIRES HUMAN REVIEW" in status.upper():
        findings.append(Finding(
            "ERROR", "UNREVIEWED_DATASET",
            f"_meta.status is {status!r}. The dataset gates merges but declares "
            f"itself unreviewed. Review it, then update this field."
        ))

    seen_ids: Set[str] = set()
    seen_questions: Dict[str, str] = {}

    for q in questions:
        qid = q.get("id", "<no-id>")

        for field in REQUIRED_FIELDS:
            if field not in q:
                findings.append(Finding("ERROR", "MISSING_FIELD", f"missing '{field}'", qid))

        if qid in seen_ids:
            findings.append(Finding("ERROR", "DUPLICATE_ID", f"id {qid!r} used more than once", qid))
        seen_ids.add(qid)

        question_text = _normalize_text(q.get("question", ""))
        if not question_text:
            findings.append(Finding("ERROR", "EMPTY_QUESTION", "question is empty", qid))
        elif question_text in seen_questions:
            findings.append(Finding(
                "ERROR", "DUPLICATE_QUESTION",
                f"identical question text to {seen_questions[question_text]}", qid))
        else:
            seen_questions[question_text] = qid

        gold_answer = (q.get("gold_answer") or "").strip()
        category = q.get("category", "")
        gold_sources = q.get("gold_source_ids", []) or []

        if not gold_answer:
            findings.append(Finding("ERROR", "EMPTY_GOLD_ANSWER", "gold_answer is empty", qid))
        elif len(gold_answer) < 40 and category != NEGATIVE_CATEGORY:
            findings.append(Finding(
                "WARN", "THIN_GOLD_ANSWER",
                f"gold_answer is only {len(gold_answer)} chars; answer_correctness "
                f"grading is unreliable against very short references", qid))

        # Negative-set conventions: negatives must have NO gold sources, and
        # every positive must have at least one, or retrieval silently skips it.
        if category == NEGATIVE_CATEGORY:
            if gold_sources:
                findings.append(Finding(
                    "ERROR", "NEGATIVE_HAS_SOURCES",
                    f"out_of_scope_negative must have empty gold_source_ids, has "
                    f"{len(gold_sources)}", qid))
        else:
            if not gold_sources:
                findings.append(Finding(
                    "ERROR", "NO_GOLD_SOURCES",
                    "non-negative question has no gold_source_ids, so it is excluded "
                    "from every retrieval metric without warning", qid))
            if len(set(gold_sources)) != len(gold_sources):
                dupes = [s for s, c in Counter(gold_sources).items() if c > 1]
                findings.append(Finding(
                    "ERROR", "DUPLICATE_GOLD_SOURCE",
                    f"repeated gold_source_ids {dupes}; inflates the recall denominator", qid))

        keywords = q.get("gold_passage_keywords", []) or []
        for kw in keywords:
            if not str(kw).strip():
                findings.append(Finding("ERROR", "EMPTY_KEYWORD", "empty gold_passage_keyword", qid))

    # Category integrity against declared distribution
    actual = Counter(q.get("category", "<none>") for q in questions)
    declared = meta.get("category_distribution", {})
    for cat, declared_n in declared.items():
        if actual.get(cat, 0) != declared_n:
            findings.append(Finding(
                "ERROR", "CATEGORY_COUNT_MISMATCH",
                f"_meta says {cat}={declared_n}, dataset has {actual.get(cat, 0)}"))
    for cat in actual:
        if declared and cat not in declared:
            findings.append(Finding(
                "WARN", "UNDECLARED_CATEGORY", f"category {cat!r} not in _meta.category_distribution"))

    declared_total = meta.get("total_questions")
    if declared_total is not None and declared_total != len(questions):
        findings.append(Finding(
            "ERROR", "TOTAL_MISMATCH",
            f"_meta.total_questions={declared_total} but dataset has {len(questions)}"))

    # Statistical power
    for cat, n in sorted(actual.items()):
        if n < MIN_CATEGORY_N:
            findings.append(Finding(
                "WARN", "UNDERPOWERED_CATEGORY",
                f"category {cat!r} has only n={n}; one question moves its mean by "
                f"{100.0 / n:.0f} points, so per-category figures are not reliable"))

    return findings


def check_against_corpus(data: dict, db_url: str = None) -> List[Finding]:
    """Verify gold sources exist, and that gold answers are grounded in them."""
    import psycopg
    from eval.config import resolve_db_url

    findings: List[Finding] = []
    db_url = resolve_db_url(db_url)
    resolver = build_resolver()

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT metadata->>'name' FROM rag_chunks WHERE metadata->>'name' IS NOT NULL;")
            corpus_names = [r[0] for r in cur.fetchall()]

            # Full text per document, for grounding checks.
            cur.execute("""
                SELECT metadata->>'name', lower(string_agg(content, ' '))
                FROM rag_chunks WHERE metadata->>'name' IS NOT NULL GROUP BY 1;
            """)
            doc_text = {r[0]: r[1] for r in cur.fetchall()}

    canonical_corpus = {resolver.resolve(n) for n in corpus_names}
    canonical_text: Dict[str, str] = {}
    for name, text in doc_text.items():
        canonical_text.setdefault(resolver.resolve(name), "")
        canonical_text[resolver.resolve(name)] += " " + text

    for q in data.get("questions", []):
        qid = q.get("id", "<no-id>")
        category = q.get("category", "")
        if category == NEGATIVE_CATEGORY:
            continue

        # Quarantined questions are deliberately unscored: the corpus has no
        # document that genuinely sources them. Reported, not treated as an
        # error, so they stay visible as pending source acquisition rather
        # than silently contributing zero recall.
        if q.get("excluded_from_scoring"):
            findings.append(Finding(
                "INFO", "QUARANTINED",
                f"excluded from scoring — {q.get('exclusion_reason', 'no reason given')}", qid))
            continue

        gold_sources = q.get("gold_source_ids", []) or []
        present = []
        for src in gold_sources:
            if resolver.resolve(src) in canonical_corpus:
                present.append(src)
            else:
                findings.append(Finding(
                    "ERROR", "GOLD_SOURCE_ABSENT",
                    f"gold source {src!r} is not in the corpus; this question can "
                    f"never score above 0 recall for it", qid))

        # Keyword grounding: the passage keywords must actually occur in the
        # gold documents, otherwise keyword_hit_rate measures nothing.
        keywords = q.get("gold_passage_keywords", []) or []
        if keywords and present:
            combined = " ".join(canonical_text.get(resolver.resolve(s), "") for s in present)
            for kw in keywords:
                if str(kw).strip().lower() not in combined:
                    findings.append(Finding(
                        "ERROR", "KEYWORD_NOT_IN_GOLD_DOC",
                        f"gold_passage_keyword {kw!r} does not appear in its gold "
                        f"document(s); the passage-level metric is unachievable", qid))

    return findings


def summarize(findings: List[Finding]) -> dict:
    counts = Counter(f.severity for f in findings)
    by_code = Counter(f.code for f in findings)
    return {
        "errors": counts.get("ERROR", 0),
        "warnings": counts.get("WARN", 0),
        "by_code": dict(by_code.most_common()),
        "passed": counts.get("ERROR", 0) == 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the benchmark dataset")
    parser.add_argument("--no-db", action="store_true", help="skip corpus checks")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    data = load_dataset()
    findings = check_structure(data)

    if not args.no_db:
        try:
            findings += check_against_corpus(data)
        except Exception as e:
            findings.append(Finding("WARN", "CORPUS_CHECK_SKIPPED", f"could not reach corpus: {e}"))

    summary = summarize(findings)

    if args.json:
        print(json.dumps({
            "summary": summary,
            "findings": [f.as_dict() for f in findings],
        }, indent=2))
        return 0 if summary["passed"] else 1

    print("=" * 72)
    print("BENCHMARK DATASET VALIDATION")
    print("=" * 72)
    print(f"  Questions: {len(data.get('questions', []))}")
    print()

    for severity in ("ERROR", "WARN", "INFO"):
        group = [f for f in findings if f.severity == severity]
        if not group:
            continue
        print(f"--- {severity} ({len(group)}) ---")
        for f in group[:60]:
            print(f"  {f}")
        if len(group) > 60:
            print(f"  ... and {len(group) - 60} more")
        print()

    print("=" * 72)
    print(f"  Findings by type:")
    for code, n in summary["by_code"].items():
        print(f"    {code:26s} {n}")
    print()
    print("PASS: dataset is valid" if summary["passed"]
          else f"FAIL: {summary['errors']} error(s) must be fixed")
    print("=" * 72)
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
