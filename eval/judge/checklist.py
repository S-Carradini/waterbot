"""Checklist rubrics, and the rollup that makes them comparable to the anchored scale.

THE THREE ARMS OF THE M5 PILOT
------------------------------
    arm 1  anchored 4-point       rubric.py / rubric.yaml
    arm 2  pure binary checklist  this module, scored pass/fail per item
    arm 3  checklist rolled up    this module, weighted fraction mapped onto 1-4

Arm 3 is the interesting one. A weighted sum of yes/no answers is CONTINUOUS, which means it
carries more resolution than an integer median while still landing on the same 1-4 target the
rest of the stack calibrates against. Decision 005 already works around the fact that isotonic
regression on four integer levels degenerates into a lookup table; a checklist rollup removes
the cause rather than the symptom.

WHAT THE PILOT DECIDES, NOT THIS MODULE
---------------------------------------
Nothing here asserts that checklists are better. The literature found they win on general
benchmarks; whether they win on Arizona water policy with these annotators is an empirical
question with a scheduled experiment attached. This module makes all three arms runnable so the
experiment can answer it.

Pure and network-free.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from eval.judge.schemas import stable_hash

DEFAULT_CHECKLIST_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "rubric_checklist.yaml"
)

ANSWERABLE = "answerable"
NEGATIVE_CATEGORY = "out_of_scope_negative"


class ChecklistError(ValueError):
    """Raised when a checklist rubric cannot be loaded or scored as written."""


@dataclass(frozen=True)
class ChecklistItem:
    """One yes/no criterion.

    ``weight`` is coarse on purpose - 3, 2, 1 - because a finer scale invites arguing about
    weights instead of about answers.
    """

    id: str
    text: str
    weight: int = 1

    def __post_init__(self) -> None:
        if self.weight <= 0:
            raise ChecklistError(f"item {self.id!r} has a non-positive weight")
        if not self.text.strip():
            raise ChecklistError(f"item {self.id!r} has no text")


@dataclass(frozen=True)
class ChecklistDimension:
    """A dimension expressed as weighted yes/no items rather than anchored levels."""

    name: str
    question: str
    applies_to: Tuple[str, ...]
    items: Tuple[ChecklistItem, ...]

    def __post_init__(self) -> None:
        if not self.items:
            raise ChecklistError(f"dimension {self.name!r} has no items")
        ids = [i.id for i in self.items]
        if len(set(ids)) != len(ids):
            raise ChecklistError(f"dimension {self.name!r} repeats an item id")

    @property
    def total_weight(self) -> int:
        return sum(i.weight for i in self.items)

    def applies(self, category: str, *, is_negative: Optional[bool] = None) -> bool:
        if "all" in self.applies_to:
            return True
        if ANSWERABLE in self.applies_to:
            # See Dimension.applies in rubric.py: explicit flag first, category only as fallback.
            return not (category == NEGATIVE_CATEGORY if is_negative is None else is_negative)
        return category in self.applies_to


@dataclass
class ChecklistRubric:
    """A loaded checklist rubric, plus the bands that roll it up onto the 1-4 scale."""

    version: str
    status: str
    dimensions: Tuple[ChecklistDimension, ...]
    bands: Tuple[Tuple[float, int], ...]  # (minimum fraction, score), highest first
    failure_modes: Tuple[str, ...] = ()
    raw: Dict = field(default_factory=dict)

    @property
    def is_piloted(self) -> bool:
        return "NOT YET PILOTED" not in self.status.upper()

    @property
    def dimension_names(self) -> List[str]:
        return [d.name for d in self.dimensions]

    def get(self, name: str) -> ChecklistDimension:
        for dimension in self.dimensions:
            if dimension.name == name:
                return dimension
        raise ChecklistError(f"no dimension named {name!r}")

    def applicable_names(
        self, category: str, *, is_negative: Optional[bool] = None
    ) -> List[str]:
        return [
            d.name for d in self.dimensions if d.applies(category, is_negative=is_negative)
        ]

    @property
    def rubric_hash(self) -> str:
        """Identity of the rubric, for the measurement version.

        Covers item ids, text and weights. Changing a weight changes what a score means, so it
        has to change the hash, and it does.
        """
        return stable_hash(
            {
                "version": self.version,
                "bands": [list(b) for b in self.bands],
                "dimensions": {
                    d.name: {
                        "applies_to": list(d.applies_to),
                        "items": [[i.id, i.text, i.weight] for i in d.items],
                    }
                    for d in self.dimensions
                },
            }
        )

    def total_items(self) -> int:
        return sum(len(d.items) for d in self.dimensions)


def load_checklist(path: str = DEFAULT_CHECKLIST_PATH) -> ChecklistRubric:
    """Load and validate a checklist rubric from YAML."""
    import yaml

    if not os.path.exists(path):
        raise ChecklistError(f"no checklist rubric at {path}")
    with open(path, "r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)

    if not isinstance(raw, dict):
        raise ChecklistError(f"{path} is not a mapping")

    scoring = raw.get("scoring") or {}
    rollup = scoring.get("rollup") or {}
    bands_raw = rollup.get("bands") or []
    if not bands_raw:
        raise ChecklistError(f"{path} defines no rollup bands; arm 3 could not be scored")

    bands: List[Tuple[float, int]] = []
    for band in bands_raw:
        try:
            bands.append((float(band["min"]), int(band["score"])))
        except (KeyError, TypeError, ValueError) as exc:
            raise ChecklistError(f"{path} has a malformed rollup band {band!r}: {exc}")
    bands.sort(key=lambda b: -b[0])
    if bands[-1][0] > 0.0:
        raise ChecklistError(
            f"{path} rollup bands do not cover a fraction of 0.0; some responses would be "
            "unscoreable"
        )

    dimensions: List[ChecklistDimension] = []
    for entry in raw.get("dimensions") or []:
        applies = entry.get("applies_to", ANSWERABLE)
        if isinstance(applies, str):
            applies = (applies,)
        items = tuple(
            ChecklistItem(
                id=item["id"], text=item["text"], weight=int(item.get("weight", 1))
            )
            for item in entry.get("items") or []
        )
        dimensions.append(
            ChecklistDimension(
                name=entry["name"],
                question=entry.get("question", ""),
                applies_to=tuple(applies),
                items=items,
            )
        )
    if not dimensions:
        raise ChecklistError(f"{path} defines no dimensions")

    names = [d.name for d in dimensions]
    if len(set(names)) != len(names):
        raise ChecklistError(f"{path} repeats a dimension name")

    return ChecklistRubric(
        version=str(raw.get("version", "unversioned")),
        status=str(raw.get("status", "")),
        dimensions=tuple(dimensions),
        bands=tuple(bands),
        failure_modes=tuple(m["name"] for m in raw.get("failure_modes") or []),
        raw=raw,
    )


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ChecklistScore:
    """One dimension's checklist result, in all three arms' currencies at once."""

    dimension: str
    checked: Tuple[str, ...]
    total_weight: int
    earned_weight: int

    @property
    def fraction(self) -> float:
        """Arm 2's number: the weighted share of items passed, continuous in [0, 1]."""
        return self.earned_weight / self.total_weight if self.total_weight else 0.0

    def rolled_up(self, bands: Sequence[Tuple[float, int]]) -> int:
        """Arm 3's number: the fraction mapped onto the 1-4 scale."""
        for minimum, score in bands:
            if self.fraction >= minimum:
                return score
        return bands[-1][1] if bands else 1

    def to_dict(self) -> Dict[str, object]:
        return {
            "dimension": self.dimension,
            "checked": list(self.checked),
            "earned_weight": self.earned_weight,
            "total_weight": self.total_weight,
            "fraction": self.fraction,
        }


def score_checklist(
    rubric: ChecklistRubric,
    dimension: str,
    checked_item_ids: Sequence[str],
) -> ChecklistScore:
    """Turn a set of ticked boxes into a score.

    An unknown item id raises rather than being ignored: a tick against an item that does not
    exist means the annotator or the judge was working from a different rubric version, and
    silently dropping it would understate the score without saying so.
    """
    target = rubric.get(dimension)
    known = {i.id for i in target.items}
    unknown = sorted(set(checked_item_ids) - known)
    if unknown:
        raise ChecklistError(
            f"dimension {dimension!r} has no item(s) {unknown}; the tick came from a different "
            "rubric version"
        )

    checked = tuple(sorted(set(checked_item_ids)))
    earned = sum(i.weight for i in target.items if i.id in checked)
    return ChecklistScore(
        dimension=dimension,
        checked=checked,
        total_weight=target.total_weight,
        earned_weight=earned,
    )


def render_checklist_for_prompt(
    rubric: ChecklistRubric, dimensions: Optional[Sequence[str]] = None
) -> str:
    """Render the checklist as it should appear in a judge prompt or an annotation screen."""
    names = list(dimensions) if dimensions is not None else rubric.dimension_names
    blocks: List[str] = []
    for name in names:
        dimension = rubric.get(name)
        lines = [f"{dimension.name}: {dimension.question}"]
        for item in dimension.items:
            lines.append(f"  [ ] ({item.weight}) {item.id}: {item.text}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# The pilot comparison
# ---------------------------------------------------------------------------
@dataclass
class ArmResult:
    """One arm's outcome in the pilot: how well annotators agreed, and how long it took."""

    arm: str
    agreement: Optional[float]
    mean_seconds_per_item: Optional[float]
    n_items: int
    notes: str = ""

    def to_dict(self) -> Dict[str, object]:
        return {
            "arm": self.arm,
            "agreement": self.agreement,
            "mean_seconds_per_item": self.mean_seconds_per_item,
            "n_items": self.n_items,
            "notes": self.notes,
        }


def compare_arms(results: Sequence[ArmResult]) -> Dict[str, object]:
    """Pick the pilot's winner on agreement, with time per item as the tie-break.

    Agreement decides because a rubric two people cannot apply consistently is not a rubric.
    Time breaks ties because annotator hours are the binding constraint on the whole project, and
    a rubric that is 2% more reliable and twice as slow buys fewer labelled items overall.

    Reports every arm, not just the winner. The losing arms are a methods result worth publishing,
    not waste.
    """
    scored = [r for r in results if r.agreement is not None]
    if not scored:
        return {"winner": None, "reason": "no arm produced an agreement number", "arms": []}

    best = max(scored, key=lambda r: r.agreement)
    close = [
        r for r in scored
        if r is not best and abs(r.agreement - best.agreement) < 0.05
    ]
    reason = f"highest annotator agreement ({best.agreement:.3f})"
    if close:
        candidates = [best] + close
        timed = [r for r in candidates if r.mean_seconds_per_item is not None]
        if timed:
            fastest = min(timed, key=lambda r: r.mean_seconds_per_item)
            if fastest is not best:
                best = fastest
                reason = (
                    f"agreement within 0.05 of the best arm, and faster per item "
                    f"({fastest.mean_seconds_per_item:.0f}s)"
                )

    return {
        "winner": best.arm,
        "reason": reason,
        "arms": [r.to_dict() for r in sorted(results, key=lambda r: r.arm)],
    }
