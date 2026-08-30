# Rubric pilot (M5): protocol for two annotators

Two people, twelve questions, three scoring methods, about two and a half hours each. This
decides which rubric gets used for everything afterwards. Until it is done, no judge score means
anything, and the panel runner refuses to run without an explicit override.

## Why this exists

We are about to have an AI score thousands of answers about Arizona water policy. Before we
trust those scores, we need to know that two informed people, given the same rubric and the same
answer, land in the same place. If they do not, the rubric is the problem, and no amount of
model quality fixes it.

We test three rubrics rather than one because we do not know which is easiest to apply
consistently, and guessing would waste the annotator time we spend later.

## What you need

- Two annotators. Both need to be comfortable with Arizona water terminology (AMA, assured vs
  adequate water supply, ADWR). They must **not** discuss items while scoring.
- About two and a half hours each, including breaks and reading the rubrics.
- The packet: `python -m eval.judge.pilot prepare --out pilot_packet.json`

That produces 36 tasks — 12 questions, each scored three ways.

The twelve are fixed by hand, not sampled. They cover all five topic categories, four of the five
questions the system should partly decline, and four well-related questions including the
exempt / non-exempt pair.

## The three arms

| Arm | What you do | Scale |
|---|---|---|
| `anchored` | Read the anchor descriptions, pick the level that fits | 1–4 |
| `checklist` | Answer each yes/no item independently | 0 or 1 per item |
| `rollup` | Same checklist, then convert to a level using the bands | 1–4 |

**Do all 12 of one arm before starting the next.** Do not jump between arms on the same
question. If you score a question 3 on the anchored rubric and then immediately fill in its
checklist, you will fill the checklist to match the 3 — and we will have measured your memory
instead of the rubric.

Take a break between arms.

## Scoring rules

1. **Score the answer, not the question.** A bad question with a well-handled answer scores well.
2. **Score only what you are asked.** If a dimension does not apply, mark it not-applicable
   rather than guessing a middle value. A guessed 2 is worse than a blank.
3. **Do not look anything up.** Judge the answer against the evidence shown. If you cannot tell
   whether a claim is supported from what is in front of you, that *is* the finding — mark it
   unsupported.
4. **Record roughly how long each arm takes you.** Annotator hours are the binding constraint on
   this whole project. A rubric that is marginally more reliable and twice as slow buys us fewer
   labelled items overall, and we would rather know that now.
5. **Do not discuss items with the other annotator until both of you are finished.** The whole
   measurement is how much you agree *without* coordinating.

## One thing to watch: the partial refusals

Four of the twelve questions are ones the system should partly decline — a third of the set, so
you will hit them often. They are not blank refusals. Each one declines the part that cannot be
answered and then states a correct general fact.

For example — *"Is there an assured water supply at 9972 Cattleman Rd, Holbrook, AZ?"* The right
answer refuses the address lookup, then correctly notes that Holbrook is outside any AMA, so the
applicable program is "adequate" water supply, not "assured".

**This is the case we most need your judgement on.** An answer like that is doing two things at
once, and it is genuinely unclear whether the current rubric can score it consistently. If you
find yourself unsure how to score one of these, say so in the notes — that note is as valuable
as the score.

## Recording your answers

Write one JSON file per annotator, or one combined file:

```json
[
  {"item_id": "q001", "arm": "anchored", "annotator_id": "ann_a", "score": 3, "seconds": 45},
  {"item_id": "q001", "arm": "anchored", "annotator_id": "ann_b", "score": 3, "seconds": 60}
]
```

`score` may be `null` for anything you could not judge. Do not invent a number to fill a gap —
blanks are dropped from the statistics and counted openly, which is the honest treatment.

## Scoring the pilot

```
python -m eval.judge.pilot score --labels pilot_labels.json
```

This reports Cohen's kappa per arm and picks a winner: highest agreement, with time per item as
the tie-break. It exits non-zero while the check is still open, so it cannot be mistaken for a
pass.

## What counts as passing

The best arm needs **kappa of 0.60 or above**. Below that, the rubric gets rewritten before any
judge work — that outcome is a legitimate result of this pilot, not a failure of it.

Note that 0.60 is deliberately not the 0.8 figure you may have seen quoted. That number comes
from general-purpose chat evaluation with ties removed. Agreement in specialist domains runs
lower, which is why later milestones target a *ratio to the measured human ceiling* rather than
an absolute number.

All three arms get reported, not just the winner. The losing arms are a publishable methods
result, not waste.

One caveat on reading the result. Twelve items is a small sample, so each arm's agreement number
carries real uncertainty. The scorer already treats arms within 0.05 of each other as tied and
picks the faster one. At this sample size, be sceptical of a slightly larger gap too: a 0.10 lead
on twelve items is not solid evidence that one rubric beats another, and choosing the faster of
the two is a sound call.
