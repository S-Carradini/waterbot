"""M5: the three-arm rubric pilot.

The pilot decides which rubric two people can actually apply consistently, before any judge
score is treated as meaning something. Three arms, from the August 2026 review:

    anchored     the existing 4-point anchored rubric (`rubric.yaml`)
    checklist    binary yes/no items (`rubric_checklist.yaml`)
    rollup       the same checklist rolled up to a per-dimension 1-4 score

`checklist.py` already holds the arms and `compare_arms`, which picks a winner from
`ArmResult`s. This module is the two halves around it: choosing the twenty items, and turning
the labels that come back into those `ArmResult`s.

WHAT THIS MODULE DOES NOT DO. It does not produce the agreement number on its own. Two people
have to sit down and annotate; `pilot_status` reports honestly that the check is open until they
have. Nothing here fabricates the missing half.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from eval.gold_set import GoldItem
from eval.judge.agreement import cohens_kappa
from eval.judge.checklist import ArmResult, compare_arms

ARMS: Tuple[str, ...] = ("anchored", "checklist", "rollup")

# The pilot is a rubric test, not a system test. Twenty was the architecture's number; the pilot
# actually runs on the twelve below, chosen by hand. `select_pilot_items` still implements the
# automatic stratified pick and is kept for re-selection if the gold set ever changes.
DEFAULT_PILOT_SIZE = 20

# The twelve items the pilot runs on, fixed by hand rather than sampled.
#
# Hand-picked because the automatic stratified pick optimises for even coverage, and that is not
# what this pilot needs most. What it needs is the cases where two annotators are most likely to
# diverge: the partial refusals, and the exempt/non-exempt well pair where the distinction is
# real but easy to blur.
#
# Composition: 4 of the gold set's 5 refusal items, all five topic categories, and four
# well-related items. q030 is the excluded refusal item - it duplicates q009 almost exactly (both
# ask about assured supply at an address outside any AMA, off the same source quote), so it would
# have spent annotator time without testing anything q009 does not.
PILOT_ITEM_IDS: Tuple[str, ...] = (
    "q004", "q008", "q009", "q012", "q013", "q017",
    "q018", "q020", "q021", "q022", "q023", "q027",
)

# Below this, the arm is not usable as-is and the rubric gets rewritten before any judge work.
# Chosen as "substantial" on the conventional Landis-Koch reading, and deliberately not the 0.8
# figure from general-chat leaderboards - specialist-domain inter-expert agreement runs lower,
# which is why M10 targets a ratio to the measured ceiling rather than an absolute.
USABLE_AGREEMENT = 0.60


class PilotError(ValueError):
    """The pilot cannot be prepared or scored as asked."""


# ---------------------------------------------------------------------------
# Choosing the twenty
# ---------------------------------------------------------------------------
def _stratum(item: GoldItem) -> str:
    """Refusal status first, topic second.

    Refusal status leads because it is the split the pilot most needs to exercise: in this gold
    set the refusal items are *partial* refusals that decline one half and ground the other, and
    whether a rubric can score that consistently is an open question the pilot exists to answer.
    """
    return f"{'refuse' if item.should_refuse else 'answer'}::{item.category}"


def _stable_rank(item_id: str, salt: str) -> str:
    """Deterministic per-item ordering that does not depend on dict iteration or list order."""
    return hashlib.sha256(f"{salt}:{item_id}".encode("utf-8")).hexdigest()


def fixed_pilot_items(
    items: Sequence[GoldItem],
    item_ids: Sequence[str] = PILOT_ITEM_IDS,
) -> List[GoldItem]:
    """Take exactly the named items, in id order.

    The default path for the pilot. Raises on an unknown id rather than quietly returning a
    shorter list - a pilot that silently ran on eleven items would still produce a kappa, and
    nobody reading it would know the twelfth was missing.
    """
    if not item_ids:
        raise PilotError("no pilot item ids given")

    by_id = {item.id: item for item in items}
    missing = [item_id for item_id in item_ids if item_id not in by_id]
    if missing:
        raise PilotError(f"gold set has no item(s): {sorted(missing)}")

    duplicates = sorted({i for i in item_ids if list(item_ids).count(i) > 1})
    if duplicates:
        raise PilotError(f"repeated pilot item id(s): {duplicates}")

    return sorted((by_id[item_id] for item_id in item_ids), key=lambda i: i.id)


def select_pilot_items(
    items: Sequence[GoldItem],
    n: int = DEFAULT_PILOT_SIZE,
    salt: str = "pilot-v1",
) -> List[GoldItem]:
    """Pick ``n`` items, spread across refusal status and topic, deterministically.

    Round-robins across strata rather than sampling, so a stratum holding one item is still
    represented. That matters here: the gold set has a category with a single member, and a
    proportional sample would drop it.

    Deterministic by construction - the order comes from hashing the item id with a fixed salt,
    so the same gold set always yields the same pilot. A pilot that changed between runs would
    make its own agreement number unreproducible.
    """
    if not items:
        raise PilotError("cannot build a pilot from an empty gold set")
    if n <= 0:
        raise PilotError(f"pilot size must be positive, got {n}")

    by_stratum: Dict[str, List[GoldItem]] = defaultdict(list)
    for item in items:
        by_stratum[_stratum(item)].append(item)
    for members in by_stratum.values():
        members.sort(key=lambda i: _stable_rank(i.id, salt))

    # Largest strata first so the round-robin does not starve them when n is small.
    order = sorted(by_stratum, key=lambda s: (-len(by_stratum[s]), s))

    chosen: List[GoldItem] = []
    depth = 0
    while len(chosen) < n:
        added = False
        for name in order:
            if depth < len(by_stratum[name]):
                chosen.append(by_stratum[name][depth])
                added = True
                if len(chosen) == n:
                    break
        if not added:
            break  # every stratum exhausted; the gold set is smaller than n
        depth += 1

    return sorted(chosen, key=lambda i: i.id)


def pilot_composition(items: Sequence[GoldItem]) -> Dict[str, object]:
    """What the chosen pilot actually covers, for the record."""
    return {
        "n_items": len(items),
        "n_refusal": sum(1 for i in items if i.should_refuse),
        "n_answerable": sum(1 for i in items if not i.should_refuse),
        "categories": dict(
            sorted((c, sum(1 for i in items if i.category == c)) for c in {i.category for i in items})
        ),
        "item_ids": [i.id for i in items],
    }


# ---------------------------------------------------------------------------
# The packet the annotators receive
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PilotTask:
    """One item, for one arm, as one annotator sees it."""

    item_id: str
    arm: str
    question: str
    answer: str
    category: str
    should_refuse: bool

    def to_dict(self) -> Dict[str, object]:
        return {
            "item_id": self.item_id,
            "arm": self.arm,
            "question": self.question,
            "answer": self.answer,
            "category": self.category,
            "should_refuse": self.should_refuse,
        }


def build_packet(
    items: Sequence[GoldItem],
    answers: Optional[Dict[str, str]] = None,
    arms: Sequence[str] = ARMS,
) -> List[PilotTask]:
    """Every (item, arm) pair, ordered so one arm is completed before the next begins.

    Arms are kept apart on purpose. Interleaving them would let an annotator's 4-point judgement
    anchor their checklist answers on the same item, and the pilot would then be measuring
    consistency of memory rather than of the rubric.

    ``answers`` supplies the system response to be judged; where an item has none, the gold answer
    stands in so the rubric can still be exercised on real text.
    """
    unknown = [a for a in arms if a not in ARMS]
    if unknown:
        raise PilotError(f"unknown pilot arm(s): {sorted(unknown)}")

    answers = answers or {}
    return [
        PilotTask(
            item_id=item.id,
            arm=arm,
            question=item.question,
            answer=answers.get(item.id, item.answer),
            category=item.category,
            should_refuse=item.should_refuse,
        )
        for arm in arms
        for item in sorted(items, key=lambda i: i.id)
    ]


def write_packet(tasks: Sequence[PilotTask], path: str) -> str:
    """Write the packet as JSON. Returns the path."""
    with open(path, "w", encoding="utf-8") as handle:
        json.dump([t.to_dict() for t in tasks], handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    return path


# ---------------------------------------------------------------------------
# Scoring the labels that come back
# ---------------------------------------------------------------------------
@dataclass
class PilotLabel:
    """One annotator's score for one item under one arm."""

    item_id: str
    arm: str
    annotator_id: str
    score: Optional[float]
    seconds: Optional[float] = None


def arm_results(
    labels: Sequence[PilotLabel],
    weights: Optional[str] = "quadratic",
) -> List[ArmResult]:
    """Per-arm annotator agreement, as `ArmResult`s ready for `compare_arms`.

    Cohen's kappa, per decision 028, which also fixes the pilot at exactly two annotators - kappa
    is defined for two raters and this is a two-person pilot by design.

    Weighted quadratically for the ordinal arms because on a 1-4 scale a 1-versus-4 disagreement
    is worse than 3-versus-4, and unweighted kappa calls them the same. The binary checklist arm
    is scored unweighted, since with two categories weighting changes nothing and asking for it
    only invites confusion.

    Items either annotator left unscored are dropped pairwise and counted in `notes`, never
    imputed.
    """
    by_arm: Dict[str, List[PilotLabel]] = defaultdict(list)
    for label in labels:
        by_arm[label.arm].append(label)

    results: List[ArmResult] = []
    for arm in sorted(by_arm):
        arm_labels = by_arm[arm]
        annotators = sorted({label.annotator_id for label in arm_labels})

        if len(annotators) != 2:
            results.append(
                ArmResult(
                    arm=arm,
                    agreement=None,
                    mean_seconds_per_item=_mean_seconds(arm_labels),
                    n_items=len({label.item_id for label in arm_labels}),
                    notes=(
                        f"needs exactly 2 annotators for Cohen's kappa, found {len(annotators)}"
                    ),
                )
            )
            continue

        first, second = annotators
        scores: Dict[str, Dict[str, Optional[float]]] = defaultdict(dict)
        for label in arm_labels:
            scores[label.item_id][label.annotator_id] = label.score

        paired = [
            (scores[item][first], scores[item][second])
            for item in sorted(scores)
            if scores[item].get(first) is not None and scores[item].get(second) is not None
        ]
        dropped = len(scores) - len(paired)

        if not paired:
            results.append(
                ArmResult(
                    arm=arm,
                    agreement=None,
                    mean_seconds_per_item=_mean_seconds(arm_labels),
                    n_items=0,
                    notes=f"no item was scored by both annotators ({dropped} incomplete)",
                )
            )
            continue

        a = [pair[0] for pair in paired]
        b = [pair[1] for pair in paired]
        # Binary arm: weighting two categories is meaningless, so do not ask for it.
        binary = set(a) | set(b) <= {0.0, 1.0, 0, 1}
        kappa = cohens_kappa(a, b, weights=None if binary else weights)

        note = "" if not dropped else f"{dropped} item(s) not scored by both annotators, dropped"
        results.append(
            ArmResult(
                arm=arm,
                agreement=kappa,
                mean_seconds_per_item=_mean_seconds(arm_labels),
                n_items=len(paired),
                notes=note,
            )
        )
    return results


def _mean_seconds(labels: Sequence[PilotLabel]) -> Optional[float]:
    timed = [label.seconds for label in labels if label.seconds is not None]
    return sum(timed) / len(timed) if timed else None


# ---------------------------------------------------------------------------
# The acceptance check
# ---------------------------------------------------------------------------
@dataclass
class PilotStatus:
    """Whether M5's acceptance check is met, and on what evidence."""

    passed: bool
    reason: str
    winner: Optional[str] = None
    agreement: Optional[float] = None
    arms: List[Dict[str, object]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "passed": self.passed,
            "reason": self.reason,
            "winner": self.winner,
            "agreement": self.agreement,
            "threshold": USABLE_AGREEMENT,
            "arms": self.arms,
        }

    def summary(self) -> str:
        head = "PASS" if self.passed else "OPEN"
        lines = [f"M5 rubric pilot: {head} - {self.reason}", ""]
        for arm in self.arms:
            agreement = arm.get("agreement")
            shown = "not computed" if agreement is None else f"kappa {agreement:.3f}"
            lines.append(f"  {str(arm.get('arm')):10s} {shown:18s} n={arm.get('n_items')}")
            if arm.get("notes"):
                lines.append(f"             {arm['notes']}")
        return "\n".join(lines)


def pilot_status(labels: Sequence[PilotLabel]) -> PilotStatus:
    """M5's acceptance check: two humans reach usable agreement, or the rubric gets rewritten.

    Returns OPEN rather than raising when there are no labels. The pilot needing people is the
    expected state, not an error, and a check that crashes when un-run is a check nobody runs.
    """
    if not labels:
        return PilotStatus(
            passed=False,
            reason="no annotations yet - the pilot needs two people and about half a day",
        )

    results = arm_results(labels)
    comparison = compare_arms(results)
    arms = [r.to_dict() for r in results]

    winner = comparison.get("winner")
    if winner is None:
        return PilotStatus(
            passed=False,
            reason=str(comparison.get("reason", "no arm produced an agreement number")),
            arms=arms,
        )

    best = max(
        (r for r in results if r.agreement is not None),
        key=lambda r: r.agreement,  # type: ignore[arg-type,return-value]
    )
    if best.agreement is None or best.agreement < USABLE_AGREEMENT:
        return PilotStatus(
            passed=False,
            reason=(
                f"best arm {best.arm!r} reached kappa {best.agreement:.3f}, below the usable "
                f"threshold of {USABLE_AGREEMENT} - rewrite the rubric before any judge work"
            ),
            winner=None,
            agreement=best.agreement,
            arms=arms,
        )

    return PilotStatus(
        passed=True,
        reason=f"arm {winner!r} reached usable agreement",
        winner=str(winner),
        agreement=best.agreement,
        arms=arms,
    )


# ---------------------------------------------------------------------------
# How long it takes
# ---------------------------------------------------------------------------
# Calibrated from the original 20-item plan: 60 tasks in about four hours including breaks, so
# roughly 3.5 minutes of actual scoring per task. Onboarding is charged once - reading the three
# rubrics before the first arm - and does not shrink with the item count.
MINUTES_PER_TASK = 3.5
ONBOARDING_MINUTES = 30


def estimated_minutes_per_annotator(n_items: int, n_arms: int = len(ARMS)) -> int:
    """Rough wall-clock minutes for one annotator, including reading the rubrics."""
    return int(round(ONBOARDING_MINUTES + n_items * n_arms * MINUTES_PER_TASK))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: Optional[Sequence[str]] = None) -> int:
    """Emit the pilot packet, or score the labels that came back.

        python -m eval.judge.pilot prepare --out pilot_packet.json
        python -m eval.judge.pilot score   --labels pilot_labels.json
    """
    import argparse

    from eval.gold_set import DEFAULT_GOLD_PATH, load_gold_set

    parser = argparse.ArgumentParser(description="M5 three-arm rubric pilot")
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare", help="choose the items and write the annotation packet")
    prepare.add_argument("--gold", default=DEFAULT_GOLD_PATH)
    prepare.add_argument("--out", default="pilot_packet.json")
    prepare.add_argument(
        "--auto",
        action="store_true",
        help="re-select items automatically instead of using the fixed twelve",
    )
    prepare.add_argument("--n", type=int, default=DEFAULT_PILOT_SIZE)
    prepare.add_argument("--salt", default="pilot-v1")

    score = sub.add_parser("score", help="score returned labels against the acceptance check")
    score.add_argument("--labels", required=True)

    args = parser.parse_args(argv)

    if args.command == "prepare":
        gold = load_gold_set(args.gold)
        items = (
            select_pilot_items(gold, n=args.n, salt=args.salt)
            if args.auto
            else fixed_pilot_items(gold)
        )
        write_packet(build_packet(items), args.out)
        n_refuse = sum(1 for i in items if i.should_refuse)
        print(f"wrote {args.out}: {len(items)} items x {len(ARMS)} arms")
        print(f"  refusal {n_refuse}, answerable {len(items) - n_refuse}")
        for category in sorted({i.category for i in items}):
            print(f"  {sum(1 for i in items if i.category == category):2d}  {category}")
        # Annotator time is the binding constraint on the whole project, so say it up front.
        print(f"  ~{estimated_minutes_per_annotator(len(items))} min per annotator")
        return 0

    with open(args.labels, encoding="utf-8") as handle:
        raw = json.load(handle)
    labels = [
        PilotLabel(
            item_id=row["item_id"],
            arm=row["arm"],
            annotator_id=row["annotator_id"],
            score=row.get("score"),
            seconds=row.get("seconds"),
        )
        for row in raw
    ]
    status = pilot_status(labels)
    print(status.summary())
    # Exit non-zero while the check is open, so a runner cannot mistake it for a pass.
    return 0 if status.passed else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
