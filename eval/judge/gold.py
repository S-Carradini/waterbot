"""The gold set as pipeline input.

`eval/gold_set.py` loads and validates the file. This module is the other half: it turns
`GoldItem` rows into the shapes L1, L4 and L5 already expect, so nothing downstream has to learn
what a gold set is.

Why a separate module. The gold set is five columns by deliberate design - question, answer,
source_quote, should_refuse, category - and everything else the pipeline wants is *derived* from
those against the corpus rather than authored by hand. Which documents support an item comes from
resolving its quotes; the fold groups come from those documents. Keeping the derivation here means
the gold file stays small and the corpus stays the single authority on what supports what.

Network-free. Every function takes the corpus as an argument.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from eval.gold_set import GoldItem, resolve_sources
from eval.judge.evidence import CanonicalMap
from eval.judge.freeze import BenchmarkItem


class GoldIntegrationError(ValueError):
    """The gold set cannot drive the pipeline as given."""


# ---------------------------------------------------------------------------
# L1: what to freeze
# ---------------------------------------------------------------------------
def benchmark_items(items: Sequence[GoldItem]) -> List[BenchmarkItem]:
    """Adapt gold rows into the freezer's item shape.

    `should_refuse` is carried explicitly rather than folded into `category`. The freezer stamps
    it onto every `Response`, which is what lets `Response.is_negative` answer correctly later.
    Folding it into the category instead would work for refusal scoring and destroy the topic
    breakdown, which is the other thing the category is for.
    """
    if not items:
        raise GoldIntegrationError("refusing to build a benchmark from an empty gold set")

    seen: Dict[str, str] = {}
    for item in items:
        if item.id in seen:
            raise GoldIntegrationError(f"duplicate gold id {item.id!r}")
        seen[item.id] = item.question

    return sorted(
        (
            BenchmarkItem(
                item_id=item.id,
                question=item.question,
                category=item.category,
                should_refuse=item.should_refuse,
            )
            for item in items
        ),
        key=lambda i: i.item_id,
    )


# ---------------------------------------------------------------------------
# L4: what groups with what
# ---------------------------------------------------------------------------
def item_documents(
    items: Sequence[GoldItem],
    documents: Dict[str, str],
    canonical_map: Optional[CanonicalMap] = None,
) -> Dict[str, List[str]]:
    """Map each gold item to the canonical documents its quotes resolve to.

    This is the input `calibrate.build_groups` needs to satisfy invariant 5. Resolution runs
    through the canonical map on purpose: 127 corpus names share content with another name, so
    two items quoting the same text under different filenames are the same evidence. Grouping on
    raw names would call them independent and let evidence leak across folds - which is the exact
    failure invariant 5 exists to prevent, and it does not announce itself, it just returns an
    optimistic calibration.

    An item whose quotes resolve nowhere gets an empty list, and `build_groups` then gives it its
    own singleton group. That is the honest outcome: an item with no locatable support shares
    evidence with nothing.

    Refusal items are grouped exactly like the rest, because in this gold set they are partial
    refusals rather than blank ones - all five decline the unanswerable part and then ground a
    correct general fact, and all five carry a quote for that grounded half. They can therefore
    share evidence with an answerable item and must be allowed to group with it.
    """
    resolved: Dict[str, List[str]] = {item.id: [] for item in items}

    for resolution in resolve_sources(items, documents):
        for name in resolution.documents:
            canonical = canonical_map.resolve(name) if canonical_map is not None else name
            if canonical not in resolved[resolution.item_id]:
                resolved[resolution.item_id].append(canonical)

    return {item_id: sorted(docs) for item_id, docs in sorted(resolved.items())}


def unsupported_items(
    items: Sequence[GoldItem],
    documents: Dict[str, str],
    canonical_map: Optional[CanonicalMap] = None,
) -> List[str]:
    """Items that cite a quote which resolves to no document, sorted.

    Reported rather than raised. The gold set is the source of truth for scoring; a quote the
    corpus cannot match is a fact about the corpus, and the caller decides whether that is a
    stop-the-run condition or a documented limitation of the run.

    The test is "has a quote that resolves nowhere", not "is answerable". An item citing nothing
    is not unsupported - it makes no sourced claim to support. Refusal items are included on the
    same terms as everything else, because in this gold set they do carry quotes.
    """
    resolved = item_documents(items, documents, canonical_map)
    return sorted(item.id for item in items if item.source_quote and not resolved[item.id])


# ---------------------------------------------------------------------------
# L2/L5: the reference text and the refusal key
# ---------------------------------------------------------------------------
def reference_answers(items: Sequence[GoldItem]) -> Dict[str, str]:
    """`{item_id: gold answer}`, for judge conditions that are shown a reference."""
    return {item.id: item.answer for item in items}


def refusal_labels(items: Sequence[GoldItem]) -> Dict[str, bool]:
    """`{item_id: should_refuse}`, the key for the paired refusal report."""
    return {item.id: item.should_refuse for item in items}


def category_of(items: Sequence[GoldItem]) -> Dict[str, str]:
    """`{item_id: topic category}`, for per-category slicing.

    Distinct from the refusal key. These categories are topics, and reading a scoring class off
    them is the mistake `Response.is_negative` exists to stop.
    """
    return {item.id: item.category for item in items}
