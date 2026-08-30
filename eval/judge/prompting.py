"""Prompt rendering and the verdict schema for constrained decoding (L2).

WHY PLAIN TEXT AND NOT A TEMPLATE ENGINE
----------------------------------------
The templates carry literal JSON braces in the output contract, which makes both ``str.format``
and Jinja's default delimiters hazardous - a stray brace becomes a silent rendering error or,
worse, a silently dropped block. Substitution here is explicit token replacement over a plain
text file. It also means ``eval/judge/`` gains no dependency for something this simple
(CLAUDE.md: ask before adding a dependency).

WHY THE SYSTEM AND USER BLOCKS ARE SPLIT
----------------------------------------
The role plus the full rubric is byte-identical across every item and is the largest input
block. Splitting it out lets it be marked for prompt caching, which is where most of the 92%
grading cost goes. The split lives inside one template file so a prompt version is still one
file and one hash.

CONSTRAINED DECODING, NOT PROMPTED JSON
---------------------------------------
``verdict_json_schema`` builds the schema that providers enforce natively. Prompting for JSON
and parsing the result is the largest avoidable source of missing verdicts - and missing
verdicts are not missing at random, they concentrate on hard items, so the loss is a bias rather
than attrition.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from eval.judge.rubric import Rubric, render_for_prompt
from eval.judge.schemas import Passage, Response, stable_hash

PROMPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")
SEPARATOR = "---USER---"

POINTWISE_V1 = "pointwise_v1"
PAIRWISE_V1 = "pairwise_v1"
REPAIR_V1 = "repair_v1"


class PromptError(RuntimeError):
    """Raised when a template cannot be rendered into a usable prompt."""


@dataclass(frozen=True)
class RenderedPrompt:
    """A prompt ready to send, with the identity that binds a verdict to it."""

    system: str
    user: str
    prompt_hash: str
    template_name: str

    @property
    def approximate_tokens(self) -> int:
        """Rough size estimate for budgeting before a call is made.

        Four characters per token is crude and deliberately so: it is used to refuse a run that
        would obviously blow the budget, not to bill anyone. Real usage comes from the response.
        """
        return (len(self.system) + len(self.user)) // 4


def load_template(name: str, prompts_dir: str = PROMPTS_DIR) -> tuple:
    """Return ``(system_block, user_block, template_hash)`` for a template name."""
    path = os.path.join(prompts_dir, f"{name}.txt")
    if not os.path.exists(path):
        available = sorted(
            f[: -len(".txt")] for f in os.listdir(prompts_dir) if f.endswith(".txt")
        )
        raise PromptError(f"no template {name!r} in {prompts_dir}; available: {available}")

    with open(path, "r", encoding="utf-8") as handle:
        raw = handle.read()

    if SEPARATOR not in raw:
        raise PromptError(f"template {name!r} has no {SEPARATOR} separating system from user")
    system, user = raw.split(SEPARATOR, 1)
    # The hash covers the whole file, so a change to either block is a new prompt version.
    return system.strip(), user.strip(), stable_hash(raw)


_PLACEHOLDER = re.compile(r"\{\{([A-Z_][A-Z0-9_]*)\}\}")


def _substitute(text: str, values: Dict[str, str], where: str) -> str:
    """Replace ``{{TOKEN}}`` placeholders, refusing to leave any unfilled.

    An unfilled placeholder reaching a judge would be a prompt containing a literal
    ``{{EVIDENCE}}``, which the model would answer anyway. Raising turns a subtly wrong verdict
    into an obvious failure.

    The completeness check runs against the TEMPLATE, before substitution, never against the
    result. Substituted content routinely contains braces - the repair prompt embeds a judge's
    malformed JSON output verbatim - and scanning afterwards would reject exactly the inputs the
    repair path exists to handle.
    """
    required = set(_PLACEHOLDER.findall(text))
    missing = sorted(required - set(values))
    if missing:
        raise PromptError(
            f"{where}: placeholder(s) {', '.join('{{' + m + '}}' for m in missing)} "
            "were never filled"
        )
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def format_evidence(passages: Sequence[Passage]) -> str:
    """Number passages as the judge will cite them.

    Numbering is the ``evidence_id``, which ``Response`` guarantees is dense and 1-based, so a
    cited number is unambiguous. Document ids are shown because citation validity is a scored
    dimension and the judge cannot check a citation it cannot see.
    """
    if not passages:
        return "(no passages were retrieved for this question)"
    return "\n\n".join(
        f"[{p.evidence_id}] ({p.canonical_doc_id})\n{p.text}"
        for p in sorted(passages, key=lambda p: p.evidence_id)
    )


def format_citations(citations: Sequence[str]) -> str:
    return ", ".join(citations) if citations else "(the response displayed no citations)"


def render_pointwise(
    response: Response,
    rubric: Rubric,
    dimensions: Optional[Sequence[str]] = None,
    template_name: str = POINTWISE_V1,
    prompts_dir: str = PROMPTS_DIR,
) -> RenderedPrompt:
    """Render the pointwise judging prompt for one frozen response.

    ``dimensions`` defaults to the rubric's own applicability rules for this response's category.
    A dimension that does not apply is not scored at all rather than scored as zero - scoring an
    inapplicable dimension penalises a system for our bookkeeping.
    """
    system_template, user_template, template_hash = load_template(template_name, prompts_dir)

    names = list(dimensions) if dimensions is not None else rubric.applicable_names(
        response.category,
        has_citations=bool(response.citations),
        is_negative=response.is_negative,
    )
    if not names:
        raise PromptError(
            f"no rubric dimension applies to category {response.category!r}; "
            "there is nothing to judge"
        )

    failure_modes = "\n".join(f"  - {mode.name}: {mode.description}" for mode in rubric.failure_modes) \
        if getattr(rubric, "failure_modes", None) else "  (none defined)"

    system = _substitute(
        system_template,
        {"RUBRIC": render_for_prompt(rubric, names), "FAILURE_MODES": failure_modes},
        f"{template_name} system block",
    )
    user = _substitute(
        user_template,
        {
            "QUESTION": response.question,
            "EVIDENCE": format_evidence(response.passages),
            "RESPONSE": response.answer,
            "CITATIONS": format_citations(response.citations),
            "DIMENSIONS": ", ".join(names),
        },
        f"{template_name} user block",
    )
    return RenderedPrompt(system, user, template_hash, template_name)


def render_pairwise(
    first: Response,
    second: Response,
    rubric: Rubric,
    template_name: str = PAIRWISE_V1,
    prompts_dir: str = PROMPTS_DIR,
) -> RenderedPrompt:
    """Render a pairwise comparison. Evidence comes from the first response.

    Both responses answer the same question; showing one evidence block keeps the comparison
    about the answers rather than about who retrieved better, which is a separate question the
    retrieval metrics already answer.
    """
    if first.item_id != second.item_id:
        raise PromptError(
            f"cannot compare responses to different items: {first.item_id} vs {second.item_id}"
        )
    system_template, user_template, template_hash = load_template(template_name, prompts_dir)

    system = _substitute(
        system_template,
        {"RUBRIC": render_for_prompt(rubric)},
        f"{template_name} system block",
    )
    user = _substitute(
        user_template,
        {
            "QUESTION": first.question,
            "EVIDENCE": format_evidence(first.passages),
            "RESPONSE_FIRST": first.answer,
            "RESPONSE_SECOND": second.answer,
        },
        f"{template_name} user block",
    )
    return RenderedPrompt(system, user, template_hash, template_name)


def render_repair(
    previous_output: str,
    problems: Sequence[str],
    template_name: str = REPAIR_V1,
    prompts_dir: str = PROMPTS_DIR,
) -> RenderedPrompt:
    """Render the one repair attempt allowed after a validation failure."""
    system_template, user_template, template_hash = load_template(template_name, prompts_dir)
    system = system_template
    user = _substitute(
        user_template,
        {
            "PREVIOUS": previous_output.strip() or "(empty)",
            "PROBLEMS": "\n".join(f"  - {p}" for p in problems) or "  - (unspecified)",
        },
        f"{template_name} user block",
    )
    return RenderedPrompt(system, user, template_hash, template_name)


# ---------------------------------------------------------------------------
# The schema providers enforce
# ---------------------------------------------------------------------------
def verdict_json_schema(dimensions: Sequence[str], failure_modes: Sequence[str]) -> Dict:
    """JSON schema for a pointwise verdict, for provider-native constrained decoding.

    Property order matters: ``rationale`` precedes ``score`` because models emit properties in
    schema order, and requiring the justification before the number measurably improves accuracy
    and makes every disagreement auditable. It is the one place where schema ordering is a
    methodological choice rather than a formatting preference.
    """
    if not dimensions:
        raise PromptError("a verdict schema needs at least one dimension")

    # EVIDENCE-LOCKING. Models emit properties in schema order, so this order forces the judge to
    # commit to what it looked at before it can justify anything, and to justify before it can
    # score. Rationale-first alone left both free to be written after the verdict was decided.
    dimension_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["evidence_ids", "quoted_span", "rationale", "insufficient_evidence", "score"],
        "properties": {
            "evidence_ids": {"type": "array", "items": {"type": "integer", "minimum": 1}},
            "quoted_span": {"type": "string"},
            "rationale": {"type": "string", "minLength": 1},
            "insufficient_evidence": {"type": "boolean"},
            "score": {"type": ["integer", "null"], "enum": [1, 2, 3, 4, None]},
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["dimensions", "failure_modes", "overall_confidence"],
        "properties": {
            "dimensions": {
                "type": "object",
                "additionalProperties": False,
                "required": list(dimensions),
                "properties": {name: dimension_schema for name in dimensions},
            },
            "failure_modes": {
                "type": "array",
                "items": {"type": "string", "enum": list(failure_modes)} if failure_modes
                else {"type": "string"},
            },
            "overall_confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        },
    }


def pairwise_json_schema() -> Dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["rationale", "evidence_ids", "winner"],
        "properties": {
            "rationale": {"type": "string", "minLength": 1},
            "evidence_ids": {"type": "array", "items": {"type": "integer", "minimum": 1}},
            "winner": {"type": "string", "enum": ["first", "second", "tie"]},
        },
    }


def verdict_schema_hash(dimensions: Sequence[str], failure_modes: Sequence[str]) -> str:
    """Identity of the verdict SHAPE, for the measurement version.

    Covers the field order as well as the field set, because order is what evidence-locking
    changes and order changes what judges emit. Without this in the measurement version, that
    change would be invisible to the comparison guard.
    """
    return stable_hash(verdict_json_schema(dimensions, failure_modes))
