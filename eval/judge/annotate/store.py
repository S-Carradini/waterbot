"""L4: persistence for human labels.

Separated from the Streamlit app so every rule here is testable without launching a UI. The app
is a thin shell over these functions; the guarantees live here.

PRE-ADJUDICATION LABELS ARE KEPT FOREVER
----------------------------------------
Adjudication resolves disagreements, and the resolved labels are what calibration fits on. But
the agreement between annotators BEFORE adjudication is the human ceiling, and it is the number
that makes every judge result interpretable. Overwriting an original label with its adjudicated
version would destroy the ceiling and there would be no way to recover it.

So labels are append-only JSONL, adjudications are written as new records with
``adjudicated=True``, and the original is never touched. ``ceiling_matrix`` reads only
pre-adjudication records, by construction.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from eval.judge.schemas import HumanLabel


class LabelStoreError(RuntimeError):
    """Raised when the label store is asked to do something that would lose a label."""


class LabelStore:
    """Append-only JSONL of human labels."""

    def __init__(self, path: str) -> None:
        self.path = path

    def exists(self) -> bool:
        return os.path.exists(self.path)

    def append(self, labels: Sequence[HumanLabel]) -> int:
        """Append labels. Never rewrites, never deduplicates.

        A repeated (response, dimension, annotator, round) is allowed on purpose: an annotator
        revising a score within a session is legitimate, and ``load_latest`` resolves it by
        taking the last write. Refusing here would make the UI's autosave impossible.
        """
        if not labels:
            return 0
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(self.path, "a", encoding="utf-8", newline="") as handle:
            for label in labels:
                handle.write(
                    json.dumps(
                        label.model_dump(mode="json"),
                        sort_keys=True,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )
                handle.write("\n")
        return len(labels)

    def load_all(self) -> List[HumanLabel]:
        """Every record ever written, in order. The audit trail."""
        if not self.exists():
            return []
        labels: List[HumanLabel] = []
        with open(self.path, "r", encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    labels.append(HumanLabel.model_validate(json.loads(line)))
                except Exception as exc:  # noqa: BLE001 - any bad row names its line
                    raise LabelStoreError(f"{self.path} line {number} is unreadable: {exc}")
        return labels

    def load_latest(self, include_adjudicated: bool = True) -> List[HumanLabel]:
        """The current label per (response, dimension, annotator), last write winning."""
        latest: Dict[Tuple[str, str, str], HumanLabel] = {}
        for label in self.load_all():
            if not include_adjudicated and label.adjudicated:
                continue
            latest[(label.response_id, label.dimension, label.annotator_id)] = label
        return [latest[key] for key in sorted(latest)]

    def load_pre_adjudication(self) -> List[HumanLabel]:
        """Only original labels. The human ceiling is computed from these and nothing else."""
        return self.load_latest(include_adjudicated=False)

    def progress(self, assigned: int) -> Dict[str, object]:
        labels = self.load_latest(include_adjudicated=False)
        return {
            "assigned": assigned,
            "completed": len(labels),
            "remaining": max(0, assigned - len(labels)),
            "fraction": len(labels) / assigned if assigned else 0.0,
        }


# ---------------------------------------------------------------------------
# The human ceiling matrix
# ---------------------------------------------------------------------------
def ceiling_matrix(
    labels: Sequence[HumanLabel],
    dimension: str,
    annotators: Optional[Sequence[str]] = None,
) -> Tuple[List[str], List[str], List[List[Optional[float]]]]:
    """Build the annotators x items matrix that agreement statistics need.

    Only items every listed annotator scored are included, because agreement is undefined on an
    item only one person saw. Abstentions stay ``None`` rather than being dropped, so alpha can
    use them.

    Returns ``(annotators, response_ids, rows)`` ready for ``agreement.agreement_report``.
    """
    relevant = [label for label in labels if label.dimension == dimension]
    if annotators is None:
        annotator_list = sorted({label.annotator_id for label in relevant})
    else:
        annotator_list = list(annotators)

    by_annotator: Dict[str, Dict[str, HumanLabel]] = defaultdict(dict)
    for label in relevant:
        by_annotator[label.annotator_id][label.response_id] = label

    if not annotator_list:
        return ([], [], [])

    shared = set(by_annotator[annotator_list[0]]) if annotator_list[0] in by_annotator else set()
    for annotator in annotator_list[1:]:
        shared &= set(by_annotator.get(annotator, {}))
    items = sorted(shared)

    rows = [
        [
            by_annotator[annotator][item].score
            if item in by_annotator.get(annotator, {})
            else None
            for item in items
        ]
        for annotator in annotator_list
    ]
    return (annotator_list, items, rows)


# ---------------------------------------------------------------------------
# Adjudication
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Disagreement:
    """One (response, dimension) the annotators did not settle."""

    response_id: str
    dimension: str
    scores: Dict[str, Optional[int]]

    @property
    def spread(self) -> int:
        present = [s for s in self.scores.values() if s is not None]
        return max(present) - min(present) if len(present) >= 2 else 0

    @property
    def has_abstention(self) -> bool:
        return any(score is None for score in self.scores.values())


def find_disagreements(
    labels: Sequence[HumanLabel],
    threshold: int = 1,
) -> List[Disagreement]:
    """Items where annotators differ by more than ``threshold`` levels, or where one abstained.

    An abstention against a score is a disagreement worth adjudicating in its own right: one
    person found the evidence sufficient and another did not, which is exactly the kind of
    ambiguity the rubric should be able to settle.
    """
    grouped: Dict[Tuple[str, str], Dict[str, Optional[int]]] = defaultdict(dict)
    for label in labels:
        if label.adjudicated:
            continue
        grouped[(label.response_id, label.dimension)][label.annotator_id] = label.score

    disagreements = []
    for (response_id, dimension), scores in sorted(grouped.items()):
        if len(scores) < 2:
            continue
        candidate = Disagreement(response_id, dimension, dict(scores))
        if candidate.spread > threshold or candidate.has_abstention:
            disagreements.append(candidate)
    return disagreements


def adjudicate(
    disagreement: Disagreement,
    score: Optional[int],
    adjudicator_id: str,
    round_index: int = 1,
    notes: str = "",
) -> HumanLabel:
    """Record a resolution as a NEW label. The originals are untouched.

    The adjudicator is recorded as the annotator on this record so the audit trail shows who
    decided, and ``adjudicated=True`` keeps it out of every ceiling calculation.
    """
    return HumanLabel(
        response_id=disagreement.response_id,
        dimension=disagreement.dimension,
        annotator_id=adjudicator_id,
        score=score,
        insufficient_evidence=score is None,
        pool="probe",  # adjudication does not move an item between pools
        round_index=round_index,
        adjudicated=True,
        notes=notes or f"adjudicated over {sorted(disagreement.scores)}",
    )


def adjudicated_scores(labels: Sequence[HumanLabel]) -> Dict[Tuple[str, str], Optional[int]]:
    """The final score per (response, dimension): adjudicated where it exists, else consensus.

    Where annotators agreed there is nothing to adjudicate, so the agreed score stands. Where
    they disagreed and no adjudication exists yet, the item is absent rather than averaged - an
    unresolved disagreement is not a score.
    """
    originals: Dict[Tuple[str, str], Dict[str, Optional[int]]] = defaultdict(dict)
    resolved: Dict[Tuple[str, str], Optional[int]] = {}

    for label in labels:
        key = (label.response_id, label.dimension)
        if label.adjudicated:
            resolved[key] = label.score
        else:
            originals[key][label.annotator_id] = label.score

    final: Dict[Tuple[str, str], Optional[int]] = {}
    for key, scores in originals.items():
        if key in resolved:
            final[key] = resolved[key]
            continue
        values = list(scores.values())
        if len(set(values)) == 1:
            final[key] = values[0]
        # otherwise unresolved: deliberately omitted
    for key, score in resolved.items():
        final.setdefault(key, score)
    return final
