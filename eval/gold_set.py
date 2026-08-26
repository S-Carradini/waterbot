"""The gold set: five columns, and the corpus fills in the rest.

THE FORMAT
----------
    id             row key, so a question can be referred to later
    question       what gets asked
    answer         the correct answer, in plain language
    source_quote   the exact sentence(s) from the corpus that back the answer
    should_refuse  true if the bot should decline this question
    category       rough topic tag

Nothing else. Everything the pipeline previously wanted from extra columns is either derived
from these or was process metadata that no code reads.

WHY THE QUOTE REPLACES THE DOCUMENT NAME
----------------------------------------
The obvious sixth column is "which document did this come from". It is not needed, and asking
for it is worse than not asking.

The current answer key was written from a citation list rather than from the documents, and
twenty of its named sources turned out not to exist in the corpus. A filename is a claim about
provenance that nobody checks. A verbatim quote is self-verifying: ``resolve_sources`` searches
the corpus for it, and either finds the document that contains it or reports that no document
does. The second outcome is a finding, not a gap - it means the answer is not actually supported.

So the quote does the work the filename was supposed to do, and does it honestly.

WHAT IS GENUINELY LOST
----------------------
One thing: a page or section locator would let a human reviewer find a quote in seconds rather
than by searching. That is a cost to the person checking, not to the system, and it is a fair
trade for a format people will actually fill in.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_GOLD_PATH = os.path.join(_SCRIPT_DIR, "gold_set.json")

REQUIRED_COLUMNS = ("id", "question", "answer", "source_quote", "should_refuse", "category")

QUESTION_MIN, QUESTION_MAX = 10, 300
QUOTE_MIN, QUOTE_MAX = 10, 500

_WHITESPACE = re.compile(r"\s+")
_ID = re.compile(r"^q\d{3,}$")


class GoldSetError(ValueError):
    """Raised when the gold set cannot be read as written."""


def normalise(text: str) -> str:
    """Same normalisation the corpus uses, so a quote matches the document it came from.

    Unicode form, whitespace and case only. Nothing that would let a paraphrase match - the
    point of a verbatim quote is that it is verbatim.
    """
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", text)).strip().casefold()


def _for_matching(quote: str) -> str:
    """A quote prepared for searching, tolerating the one thing every human does.

    People end a quotation with a full stop even when the sentence runs on in the source:

        document  "The Central Arizona Project is a 336-mile long system serving the state."
        quote     "The Central Arizona Project is a 336-mile long system."

    That is a correct quotation and a failed substring match. Trailing sentence punctuation and
    an ellipsis are therefore trimmed before searching.

    Nothing else is relaxed. Internal wording still has to match exactly, because a quote that
    can drift is not evidence - it is a paraphrase with a citation attached, which is the failure
    the gold set exists to prevent.
    """
    return normalise(quote).rstrip(" .,;:…").removesuffix("...")


@dataclass(frozen=True)
class GoldItem:
    """One row of the gold set."""

    id: str
    question: str
    answer: str
    source_quote: Tuple[str, ...]
    should_refuse: bool
    category: str

    @property
    def is_negative(self) -> bool:
        """A question the bot should decline. Needs no supporting quote."""
        return self.should_refuse

    @property
    def n_quotes(self) -> int:
        return len(self.source_quote)

    def to_dict(self) -> Dict[str, object]:
        return {
            "id": self.id,
            "question": self.question,
            "answer": self.answer,
            "source_quote": list(self.source_quote),
            "should_refuse": self.should_refuse,
            "category": self.category,
        }


def _as_quotes(value: object) -> Tuple[str, ...]:
    """Accept one sentence or several. Multi-hop questions simply have more than one."""
    if value is None or value == "":
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(str(v) for v in value if str(v).strip())
    raise GoldSetError(f"source_quote must be a string or a list, got {type(value).__name__}")


def load_gold_set(path: str = DEFAULT_GOLD_PATH) -> List[GoldItem]:
    """Read the gold set. Accepts a bare list or a ``{"questions": [...]}`` wrapper."""
    if not os.path.exists(path):
        raise GoldSetError(f"no gold set at {path}")
    with open(path, "r", encoding="utf-8") as handle:
        raw = json.load(handle)

    rows = raw.get("questions", raw) if isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        raise GoldSetError(f"{path} does not hold a list of questions")

    items: List[GoldItem] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise GoldSetError(f"row {index} is not an object")
        try:
            items.append(
                GoldItem(
                    id=str(row["id"]),
                    question=str(row["question"]),
                    answer=str(row.get("answer", row.get("gold_answer", ""))),
                    source_quote=_as_quotes(row.get("source_quote")),
                    should_refuse=bool(row.get("should_refuse", False)),
                    category=str(row.get("category", "")),
                )
            )
        except KeyError as exc:
            raise GoldSetError(f"row {index} is missing {exc}")
    return items


# ---------------------------------------------------------------------------
# The quote does the work the filename was supposed to do
# ---------------------------------------------------------------------------
@dataclass
class QuoteResolution:
    """Where a quote was found, or that it was not."""

    item_id: str
    quote: str
    documents: Tuple[str, ...]

    @property
    def found(self) -> bool:
        return bool(self.documents)

    @property
    def ambiguous(self) -> bool:
        """The same sentence in several documents.

        Usually a duplicate-ingest artefact rather than a problem with the question - the corpus
        has ten byte-identical documents from a bad acquisition. Reported so it is visible, not
        treated as an error.
        """
        return len(self.documents) > 1


def resolve_sources(
    items: Sequence[GoldItem],
    documents: Dict[str, str],
) -> List[QuoteResolution]:
    """Find which corpus document contains each quote.

    ``documents`` maps document name to its full text. Returns one resolution per quote, so a
    multi-hop question with two quotes produces two.

    A quote nobody can find is the important output. It means the answer is not supported by the
    corpus - either the wording drifted, or the document is not there. Both are worth knowing
    before the question is used to score anything.
    """
    haystacks = {name: normalise(text) for name, text in documents.items()}

    resolutions: List[QuoteResolution] = []
    for item in items:
        for quote in item.source_quote:
            needle = _for_matching(quote)
            matches = tuple(
                sorted(name for name, text in haystacks.items() if needle and needle in text)
            )
            resolutions.append(QuoteResolution(item.id, quote, matches))
    return resolutions


def gold_sources_from_quotes(
    items: Sequence[GoldItem],
    documents: Dict[str, str],
) -> Dict[str, List[str]]:
    """Build the ``{document: [question_ids]}`` map the evidence gate expects.

    This is the bridge: the rest of the pipeline was written to take document names, and now
    derives them from quotes instead of being told. Nothing downstream changes.
    """
    mapping: Dict[str, List[str]] = {}
    for resolution in resolve_sources(items, documents):
        for name in resolution.documents:
            mapping.setdefault(name, [])
            if resolution.item_id not in mapping[name]:
                mapping[name].append(resolution.item_id)
    return {name: sorted(ids) for name, ids in sorted(mapping.items())}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
@dataclass
class GoldSetReport:
    """What is wrong with the gold set, grouped so it reads as a work list."""

    n_items: int = 0
    errors: Dict[str, List[str]] = field(default_factory=dict)
    warnings: Dict[str, List[str]] = field(default_factory=dict)
    category_counts: Dict[str, int] = field(default_factory=dict)
    unresolved_quotes: List[str] = field(default_factory=list)
    ambiguous_quotes: List[str] = field(default_factory=list)

    def error(self, rule: str, detail: str) -> None:
        self.errors.setdefault(rule, []).append(detail)

    def warn(self, rule: str, detail: str) -> None:
        self.warnings.setdefault(rule, []).append(detail)

    @property
    def error_count(self) -> int:
        return sum(len(v) for v in self.errors.values())

    @property
    def warning_count(self) -> int:
        return sum(len(v) for v in self.warnings.values())

    @property
    def clean(self) -> bool:
        return self.error_count == 0

    def to_dict(self) -> Dict[str, object]:
        return {
            "n_items": self.n_items,
            "errors": self.errors,
            "warnings": self.warnings,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "category_counts": self.category_counts,
            "unresolved_quotes": self.unresolved_quotes,
            "ambiguous_quotes": self.ambiguous_quotes,
            "clean": self.clean,
        }


def validate_gold_set(
    items: Sequence[GoldItem],
    documents: Optional[Dict[str, str]] = None,
) -> GoldSetReport:
    """Check the five columns, and the quotes against the corpus if one is supplied.

    Deliberately short. Every rule here is one a person filling in a spreadsheet can act on
    without reading a specification.
    """
    report = GoldSetReport(n_items=len(items))
    seen: set = set()

    for item in items:
        if not _ID.match(item.id):
            report.error("id should look like q001", item.id)
        if item.id in seen:
            report.error("duplicate id", item.id)
        seen.add(item.id)

        length = len(item.question.strip())
        if length < QUESTION_MIN:
            report.error("question is too short", f"{item.id} ({length} chars)")
        elif length > QUESTION_MAX:
            report.warn("question is very long", f"{item.id} ({length} chars)")

        if not item.answer.strip():
            report.error("no answer written", item.id)

        if not item.category.strip():
            report.error("no category", item.id)
        else:
            report.category_counts[item.category] = (
                report.category_counts.get(item.category, 0) + 1
            )

        # The one rule that carries the weight.
        if item.is_negative:
            if item.source_quote:
                report.warn(
                    "a refused question does not need a source quote",
                    f"{item.id} has {item.n_quotes}",
                )
        elif not item.source_quote:
            report.error(
                "no source quote - the answer is not backed by anything", item.id
            )
        else:
            for quote in item.source_quote:
                size = len(quote.strip())
                if size < QUOTE_MIN:
                    report.error("source quote is too short to check", f"{item.id}: {quote!r}")
                elif size > QUOTE_MAX:
                    report.error(
                        "source quote is too long - quote the sentence, not the page",
                        f"{item.id} ({size} chars)",
                    )

    if documents:
        for resolution in resolve_sources(items, documents):
            if not resolution.found:
                report.unresolved_quotes.append(resolution.item_id)
                report.error(
                    "quote not found in any document - check the wording, or the document is "
                    "missing",
                    f"{resolution.item_id}: {resolution.quote[:60]!r}",
                )
            elif resolution.ambiguous:
                report.ambiguous_quotes.append(resolution.item_id)
                report.warn(
                    "quote appears in several documents (usually a duplicate ingest)",
                    f"{resolution.item_id}: {len(resolution.documents)} documents",
                )

    return report


def format_report(report: GoldSetReport) -> str:
    """Plain text, grouped by problem, so it reads as a to-do list."""
    lines = [f"Gold set: {report.n_items} questions", ""]

    if report.category_counts:
        lines.append("  By category")
        for category, count in sorted(report.category_counts.items()):
            lines.append(f"    {category:28s} {count:4d}")
        lines.append("")

    if report.errors:
        lines.append(f"  MUST FIX ({report.error_count})")
        for rule, details in sorted(report.errors.items()):
            lines.append(f"    {rule}  [{len(details)}]")
            for detail in details[:10]:
                lines.append(f"        {detail}")
            if len(details) > 10:
                lines.append(f"        ... and {len(details) - 10} more")
        lines.append("")

    if report.warnings:
        lines.append(f"  WORTH A LOOK ({report.warning_count})")
        for rule, details in sorted(report.warnings.items()):
            lines.append(f"    {rule}  [{len(details)}]")
            for detail in details[:5]:
                lines.append(f"        {detail}")
        lines.append("")

    if report.clean:
        lines.append("  No errors.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: Optional[Sequence[str]] = None) -> int:
    """``python -m eval.gold_set [path] [--corpus documents.json]``

    Runs on a half-finished file on purpose. The output is a work list, not a verdict.
    """
    import argparse

    parser = argparse.ArgumentParser(description="Check the gold set.")
    parser.add_argument("path", nargs="?", default=DEFAULT_GOLD_PATH)
    parser.add_argument(
        "--corpus",
        default=None,
        help="JSON mapping document name to full text; enables the quote check",
    )
    args = parser.parse_args(argv)

    try:
        items = load_gold_set(args.path)
    except GoldSetError as exc:
        print(f"Could not read the gold set: {exc}")
        return 2

    documents = None
    if args.corpus:
        with open(args.corpus, "r", encoding="utf-8") as handle:
            documents = json.load(handle)

    report = validate_gold_set(items, documents)
    print(format_report(report))
    if documents is None:
        print("  Quotes were not checked against the corpus. Pass --corpus to check them.")
    return 1 if report.error_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
