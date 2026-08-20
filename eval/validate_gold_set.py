"""Validate the benchmark against docs/GOLD_SET_SPEC.md.

Built to be run on a half-finished file. It reports every problem it can find in one pass,
grouped by rule, with question ids, so authoring can proceed against a checklist rather than
one error at a time.

    python -m eval.validate_gold_set                      # default dataset path
    python -m eval.validate_gold_set path/to/file.json
    python -m eval.validate_gold_set --strict             # also enforce category minimums

Exit codes: 0 clean or warnings only, 1 errors found, 2 file unreadable.

WHY THIS IS SEPARATE FROM eval/validate_dataset.py
--------------------------------------------------
That validator checks the dataset the harness reads today. This one checks the properties the
JUDGE needs and that today's dataset does not yet have: verbatim supporting quotes, a two-person
verification record, and refusal typing. Keeping them separate means expanding the gold set
cannot silently break the existing suite, and the existing suite's rules cannot silently relax
these.

The corpus-existence check deliberately lives in eval/preflight.py instead of here: it needs a
live database, and a validator that only works with a database configured is a validator nobody
runs while authoring.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATASET = os.path.join(_SCRIPT_DIR, "benchmark_dataset.json")

CATEGORIES = (
    "general_policy",
    "entity_grounding",
    "numeric_extraction",
    "temporal_realtime",
    "multi_hop",
    "out_of_scope_negative",
)

NEGATIVE = "out_of_scope_negative"

# (minimum, target) per category, from GOLD_SET_SPEC.md section 4. Minimum is what --strict
# enforces; target is what warnings nudge toward.
CATEGORY_TARGETS: Dict[str, Tuple[int, int]] = {
    "general_policy": (40, 45),
    "entity_grounding": (30, 35),
    "numeric_extraction": (25, 30),
    "multi_hop": (25, 30),
    "temporal_realtime": (20, 25),
    NEGATIVE: (20, 25),
}

REFUSAL_TYPES = (
    "geographic",
    "temporal_unknowable",
    "personal_advice",
    "out_of_domain",
    "privacy",
    "capability",
)

VERIFICATION_STATUSES = ("verified", "pending", "disputed")
VERIFICATION_METHODS = ("read_source", "domain_expert")

ID_RE = re.compile(r"^q\d{3,}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

QUESTION_MIN, QUESTION_MAX = 10, 300
QUOTE_MIN, QUOTE_MAX = 10, 500


class Findings:
    """Collects problems by rule so the report groups rather than interleaves."""

    def __init__(self) -> None:
        self.errors: Dict[str, List[str]] = defaultdict(list)
        self.warnings: Dict[str, List[str]] = defaultdict(list)

    def error(self, rule: str, detail: str) -> None:
        self.errors[rule].append(detail)

    def warn(self, rule: str, detail: str) -> None:
        self.warnings[rule].append(detail)

    @property
    def error_count(self) -> int:
        return sum(len(v) for v in self.errors.values())

    @property
    def warning_count(self) -> int:
        return sum(len(v) for v in self.warnings.values())


def _is_str(value: Any) -> bool:
    return isinstance(value, str)


def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def check_question(q: Dict[str, Any], index: int, seen_ids: set, findings: Findings) -> None:
    qid = q.get("id")
    label = qid if _is_str(qid) else f"<index {index}>"

    # -- identity ---------------------------------------------------------
    if not _is_str(qid) or not ID_RE.match(qid):
        findings.error("malformed id", f"{label}: ids must look like q001")
        return
    if qid in seen_ids:
        findings.error("duplicate id", f"{qid}")
        return
    seen_ids.add(qid)

    category = q.get("category")
    if category not in CATEGORIES:
        findings.error("unknown category", f"{qid}: {category!r}")
        return
    is_negative = category == NEGATIVE

    # -- always required --------------------------------------------------
    question = q.get("question")
    if not _nonempty_str(question):
        findings.error("missing question text", qid)
    else:
        length = len(question)
        if length < QUESTION_MIN:
            findings.error("question too short", f"{qid}: {length} chars")
        elif length > QUESTION_MAX:
            findings.warn("question over 300 chars", f"{qid}: {length} chars")
        if question.lower().count(" and ") >= 2:
            findings.warn(
                "possibly two questions in one",
                f"{qid}: contains ' and ' twice",
            )

    if not _nonempty_str(q.get("gold_answer")):
        findings.error("missing gold_answer", qid)

    if "notes" not in q:
        findings.error("missing notes field", f"{qid}: may be empty, must be present")

    sources = q.get("gold_source_ids")
    if not isinstance(sources, list) or any(not _nonempty_str(s) for s in sources):
        findings.error("malformed gold_source_ids", f"{qid}: must be a list of strings")
        sources = []
    elif not sources and not is_negative:
        findings.error("empty gold_source_ids", f"{qid}: only negatives may have none")

    # -- quarantine -------------------------------------------------------
    if q.get("excluded_from_scoring") and not _nonempty_str(q.get("exclusion_reason")):
        findings.error("quarantined without reason", qid)

    # -- negatives --------------------------------------------------------
    if is_negative:
        refusal_type = q.get("refusal_type")
        if refusal_type is None:
            findings.error("negative missing refusal_type", qid)
        elif refusal_type not in REFUSAL_TYPES:
            findings.error(
                "unknown refusal_type",
                f"{qid}: {refusal_type!r}, expected one of {', '.join(REFUSAL_TYPES)}",
            )
        if not isinstance(q.get("acceptable_redirect"), bool):
            findings.error("negative missing acceptable_redirect", f"{qid}: must be true/false")
        return  # negatives need no evidence or verification record

    # -- evidence ---------------------------------------------------------
    evidence = q.get("gold_answer_evidence")
    if evidence is None:
        findings.error("missing gold_answer_evidence", qid)
    elif not isinstance(evidence, list) or not evidence:
        findings.error("empty gold_answer_evidence", f"{qid}: need at least one quote")
    else:
        evidence_sources = []
        for position, entry in enumerate(evidence):
            where = f"{qid}[{position}]"
            if not isinstance(entry, dict):
                findings.error("malformed evidence entry", where)
                continue
            source_id = entry.get("source_id")
            if not _nonempty_str(source_id):
                findings.error("evidence missing source_id", where)
            else:
                evidence_sources.append(source_id)
                if sources and source_id not in sources:
                    findings.error(
                        "evidence cites a source not in gold_source_ids",
                        f"{where}: {source_id!r}",
                    )
            quote = entry.get("quote")
            if not _nonempty_str(quote):
                findings.error("evidence missing quote", where)
            else:
                length = len(quote)
                if length < QUOTE_MIN:
                    findings.error("quote too short", f"{where}: {length} chars")
                elif length > QUOTE_MAX:
                    findings.error("quote too long", f"{where}: {length} chars, max {QUOTE_MAX}")
            if not _nonempty_str(entry.get("locator")):
                findings.error("evidence missing locator", where)

        if category == "multi_hop" and len(set(evidence_sources)) < 2:
            findings.error(
                "multi_hop with fewer than two distinct sources",
                f"{qid}: {len(set(evidence_sources))} distinct",
            )

    # -- verification -----------------------------------------------------
    verification = q.get("verification")
    if verification is None:
        findings.error("missing verification record", qid)
    elif not isinstance(verification, dict):
        findings.error("malformed verification record", qid)
    else:
        status = verification.get("status")
        if status not in VERIFICATION_STATUSES:
            findings.error(
                "unknown verification status",
                f"{qid}: {status!r}, expected one of {', '.join(VERIFICATION_STATUSES)}",
            )
        method = verification.get("method")
        if method is not None and method not in VERIFICATION_METHODS:
            findings.error("unknown verification method", f"{qid}: {method!r}")
        if status == "verified":
            if not _nonempty_str(verification.get("verified_by")):
                findings.error("verified without verified_by", qid)
            if not _nonempty_str(verification.get("second_reviewer")):
                findings.error("verified without a second_reviewer", qid)
            verified_on = verification.get("verified_on")
            if not _is_str(verified_on) or not DATE_RE.match(verified_on or ""):
                findings.error("verified without a YYYY-MM-DD verified_on", qid)

    # -- category-specific ------------------------------------------------
    if category in ("numeric_extraction", "temporal_realtime"):
        keywords = q.get("gold_passage_keywords")
        if not isinstance(keywords, list) or not keywords:
            findings.error("missing gold_passage_keywords", f"{qid}: required for {category}")
        elif any(not _nonempty_str(k) for k in keywords):
            findings.error("malformed gold_passage_keywords", qid)

    if category == "numeric_extraction":
        answer = q.get("gold_answer")
        if _is_str(answer) and not any(ch.isdigit() for ch in answer):
            findings.warn("numeric question with no digit in gold_answer", qid)


def check_categories(counts: Counter, findings: Findings, strict: bool) -> None:
    for category, (minimum, target) in CATEGORY_TARGETS.items():
        count = counts.get(category, 0)
        if count < minimum:
            message = f"{category}: {count}, minimum {minimum}, target {target}"
            if strict:
                findings.error("category below minimum", message)
            else:
                findings.warn("category below minimum", message)
        elif count < target:
            findings.warn("category below target", f"{category}: {count}, target {target}")


def check_meta(meta: Dict[str, Any], counts: Counter, findings: Findings) -> None:
    if not isinstance(meta, dict):
        findings.error("malformed _meta", "must be an object")
        return
    declared = meta.get("total_questions")
    actual = sum(counts.values())
    if isinstance(declared, int) and declared != actual:
        findings.warn("_meta.total_questions is stale", f"declared {declared}, actual {actual}")
    if not _nonempty_str(meta.get("corpus_fingerprint_at_authoring")):
        findings.warn(
            "_meta.corpus_fingerprint_at_authoring missing",
            "records which corpus state answers were checked against",
        )


def validate(path: str, strict: bool = False) -> Findings:
    findings = Findings()
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)

    questions = data.get("questions")
    if not isinstance(questions, list):
        findings.error("malformed file", "'questions' must be a list")
        return findings

    seen_ids: set = set()
    for index, question in enumerate(questions):
        if not isinstance(question, dict):
            findings.error("malformed question", f"index {index} is not an object")
            continue
        check_question(question, index, seen_ids, findings)

    counts = Counter(
        q.get("category") for q in questions if isinstance(q, dict) and q.get("category")
    )
    check_categories(counts, findings, strict)
    check_meta(data.get("_meta", {}), counts, findings)
    return findings


def report(findings: Findings, counts: Counter, path: str, strict: bool) -> None:
    total = sum(counts.values())
    print(f"Gold set validation: {path}")
    print(f"  {total} questions" + ("  [strict]" if strict else ""))
    print()

    print("  Category coverage")
    for category in CATEGORIES:
        count = counts.get(category, 0)
        minimum, target = CATEGORY_TARGETS[category]
        if count >= target:
            mark = "ok "
        elif count >= minimum:
            mark = "-  "
        else:
            mark = "!  "
        print(f"    {mark}{category:24s} {count:4d}   minimum {minimum:3d}  target {target:3d}")
    print()

    if findings.errors:
        print(f"  ERRORS ({findings.error_count})")
        for rule, details in sorted(findings.errors.items()):
            print(f"    {rule}  [{len(details)}]")
            for detail in details[:12]:
                print(f"        {detail}")
            if len(details) > 12:
                print(f"        ... and {len(details) - 12} more")
        print()

    if findings.warnings:
        print(f"  WARNINGS ({findings.warning_count})")
        for rule, details in sorted(findings.warnings.items()):
            print(f"    {rule}  [{len(details)}]")
            for detail in details[:6]:
                print(f"        {detail}")
            if len(details) > 6:
                print(f"        ... and {len(details) - 6} more")
        print()

    if not findings.errors and not findings.warnings:
        print("  Clean.")
    elif not findings.errors:
        print("  No errors.")

    print()
    print("  Corpus existence of gold_source_ids is NOT checked here (needs a live database).")
    print("  Run `python -m eval.preflight` before any paper-grade run.")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the benchmark gold set.")
    parser.add_argument("path", nargs="?", default=DEFAULT_DATASET)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="treat category minimums as errors, for CI",
    )
    args = parser.parse_args(argv)

    try:
        findings = validate(args.path, strict=args.strict)
    except FileNotFoundError:
        print(f"No such file: {args.path}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"{args.path} is not valid JSON: {exc}", file=sys.stderr)
        return 2

    with open(args.path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    counts = Counter(
        q.get("category")
        for q in data.get("questions", [])
        if isinstance(q, dict) and q.get("category")
    )

    report(findings, counts, args.path, args.strict)
    return 1 if findings.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
