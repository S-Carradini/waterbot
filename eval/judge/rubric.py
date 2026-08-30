"""
Rubric loading, validation, and applicability rules.

The rubric is the judge's definition of quality, so a malformed one produces
scores that look fine and mean nothing. This module refuses to load a rubric
that violates the design rules stated in rubric.yaml, rather than letting a
missing anchor or a bad applies_to surface later as a puzzling metric.

The applicability logic lives here (not in the panel runner) because two
separate consumers need identical answers: the prompt builder decides which
dimensions to ask about, and the aggregator decides which nulls are legitimate.
If those two disagreed, a dimension could be scored but discarded, or asked for
and then treated as missing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_RUBRIC_PATH = os.path.join(_HERE, "rubric.yaml")

REQUIRED_LEVELS = (1, 2, 3, 4)
NEGATIVE_CATEGORY = "out_of_scope_negative"


class RubricError(ValueError):
    """Raised when a rubric is structurally invalid."""


@dataclass(frozen=True)
class Dimension:
    name: str
    question: str
    applies_to: Any                # "all" | "answerable" | [category, ...]
    anchors: Dict[int, str]
    requires_evidence: bool = False
    requires_citations: bool = False
    notes: str = ""

    def applies(
        self,
        category: str,
        *,
        has_citations: bool = True,
        is_negative: Optional[bool] = None,
    ) -> bool:
        """Whether this dimension should be scored for a given item.

        `has_citations` only matters for dimensions that declare
        requires_citations; for everything else it is ignored. A response with
        no citations cannot be scored on citation validity, and forcing a score
        there would manufacture a number out of nothing.
        """
        if self.requires_citations and not has_citations:
            return False

        if self.applies_to == "all":
            return True
        if self.applies_to == "answerable":
            # `is_negative` is the caller's explicit answer where it has one. The category
            # comparison is only a fallback, and it is wrong for any source whose categories are
            # topics rather than scoring classes - such as the gold set.
            return not (category == NEGATIVE_CATEGORY if is_negative is None else is_negative)
        if isinstance(self.applies_to, (list, tuple, set)):
            return category in self.applies_to
        raise RubricError(
            f"dimension {self.name!r} has unusable applies_to={self.applies_to!r}"
        )

    def anchor(self, level: int) -> str:
        if level not in self.anchors:
            raise RubricError(f"dimension {self.name!r} has no anchor for level {level}")
        return self.anchors[level]


@dataclass(frozen=True)
class FailureMode:
    name: str
    description: str
    why_it_matters: str = ""


@dataclass(frozen=True)
class Rubric:
    version: str
    status: str
    dimensions: List[Dimension]
    failure_modes: List[FailureMode] = field(default_factory=list)
    categories: List[str] = field(default_factory=list)
    levels: Sequence[int] = REQUIRED_LEVELS

    @property
    def is_piloted(self) -> bool:
        """False while the rubric still declares itself unpiloted.

        Callers that gate on rubric quality read this rather than parsing the
        status string themselves.
        """
        return "DRAFT" not in (self.status or "").upper()

    @property
    def dimension_names(self) -> List[str]:
        return [d.name for d in self.dimensions]

    def get(self, name: str) -> Dimension:
        for d in self.dimensions:
            if d.name == name:
                return d
        raise KeyError(f"no dimension named {name!r}")

    def applicable(
        self,
        category: str,
        *,
        has_citations: bool = True,
        is_negative: Optional[bool] = None,
    ) -> List[Dimension]:
        return [
            d
            for d in self.dimensions
            if d.applies(category, has_citations=has_citations, is_negative=is_negative)
        ]

    def applicable_names(
        self,
        category: str,
        *,
        has_citations: bool = True,
        is_negative: Optional[bool] = None,
    ) -> List[str]:
        return [
            d.name
            for d in self.applicable(
                category, has_citations=has_citations, is_negative=is_negative
            )
        ]


def _validate_dimension(raw: Dict[str, Any], seen: set, categories: List[str]) -> Dimension:
    name = raw.get("name")
    if not name:
        raise RubricError("a dimension is missing 'name'")
    if name in seen:
        raise RubricError(f"duplicate dimension name {name!r}")
    seen.add(name)

    question = raw.get("question")
    if not question:
        raise RubricError(f"dimension {name!r} is missing 'question'")

    applies_to = raw.get("applies_to")
    if applies_to is None:
        raise RubricError(f"dimension {name!r} is missing 'applies_to'")
    if isinstance(applies_to, str):
        if applies_to not in ("all", "answerable"):
            raise RubricError(
                f"dimension {name!r}: applies_to must be 'all', 'answerable', or a "
                f"list of categories; got {applies_to!r}"
            )
    elif isinstance(applies_to, (list, tuple)):
        if not applies_to:
            raise RubricError(f"dimension {name!r}: applies_to list is empty")
        if categories:
            unknown = [c for c in applies_to if c not in categories]
            if unknown:
                raise RubricError(
                    f"dimension {name!r}: applies_to names categories not declared "
                    f"in the rubric: {unknown}"
                )
    else:
        raise RubricError(f"dimension {name!r}: applies_to has unsupported type")

    anchors_raw = raw.get("anchors") or {}
    anchors: Dict[int, str] = {}
    for k, v in anchors_raw.items():
        try:
            level = int(k)
        except (TypeError, ValueError):
            raise RubricError(f"dimension {name!r}: anchor key {k!r} is not an integer")
        text = (v or "").strip()
        if not text:
            raise RubricError(f"dimension {name!r}: anchor {level} is empty")
        anchors[level] = text

    missing = [lv for lv in REQUIRED_LEVELS if lv not in anchors]
    if missing:
        raise RubricError(
            f"dimension {name!r} is missing anchors for level(s) {missing}. "
            f"Every level needs an observable anchor or judges will interpolate."
        )
    extra = [lv for lv in anchors if lv not in REQUIRED_LEVELS]
    if extra:
        raise RubricError(f"dimension {name!r} has anchors outside 1-4: {extra}")

    return Dimension(
        name=name,
        question=question,
        applies_to=applies_to,
        anchors=anchors,
        requires_evidence=bool(raw.get("requires_evidence", False)),
        requires_citations=bool(raw.get("requires_citations", False)),
        notes=(raw.get("notes") or "").strip(),
    )


def load_rubric(path: str = DEFAULT_RUBRIC_PATH) -> Rubric:
    """Load and validate a rubric, or raise RubricError explaining why not."""
    try:
        import yaml
    except ImportError as e:
        raise ImportError(
            "PyYAML is required to load the rubric. "
            "Install with: pip install -r eval/requirements-eval.txt"
        ) from e

    if not os.path.exists(path):
        raise RubricError(f"rubric not found at {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    version = data.get("version")
    if not version:
        raise RubricError("rubric is missing 'version'; results could not be attributed to it")

    categories = list(data.get("categories") or [])

    raw_dims = data.get("dimensions") or []
    if not raw_dims:
        raise RubricError("rubric declares no dimensions")

    seen: set = set()
    dimensions = [_validate_dimension(d, seen, categories) for d in raw_dims]

    scale = data.get("scale") or {}
    levels = tuple(scale.get("levels") or REQUIRED_LEVELS)
    if tuple(levels) != REQUIRED_LEVELS:
        raise RubricError(
            f"scale.levels must be {list(REQUIRED_LEVELS)}; got {list(levels)}. "
            f"The even four-point scale is a deliberate design choice - an odd "
            f"scale gives judges a safe middle and compresses the distribution."
        )

    failure_modes = [
        FailureMode(
            name=fm.get("name", ""),
            description=(fm.get("description") or "").strip(),
            why_it_matters=(fm.get("why_it_matters") or "").strip(),
        )
        for fm in (data.get("failure_modes") or [])
    ]
    for fm in failure_modes:
        if not fm.name:
            raise RubricError("a failure_mode is missing 'name'")

    fm_names = [fm.name for fm in failure_modes]
    if len(fm_names) != len(set(fm_names)):
        raise RubricError("duplicate failure_mode names")

    return Rubric(
        version=version,
        status=data.get("status", ""),
        dimensions=dimensions,
        failure_modes=failure_modes,
        categories=categories,
        levels=levels,
    )


def render_for_prompt(rubric: Rubric, dimensions: Optional[Sequence[str]] = None) -> str:
    """Render rubric text for injection into a judge prompt.

    Anchors are reproduced verbatim. Paraphrasing them per-call would make the
    rubric a moving target and silently decouple the judge's working definition
    from the one humans annotate against.
    """
    names = list(dimensions) if dimensions is not None else rubric.dimension_names
    out: List[str] = []
    for name in names:
        d = rubric.get(name)
        out.append(f"{d.name}: {d.question}")
        for level in sorted(REQUIRED_LEVELS, reverse=True):
            out.append(f"  {level} = {d.anchor(level)}")
        if d.notes:
            out.append(f"  note: {d.notes}")
        out.append("")
    return "\n".join(out).rstrip()
