# Rubric pilot (M5): protocol for two annotators

Two people, twelve questions, three scoring methods, about two hours each. This decides which
rubric gets used for everything afterwards. Until it is done, no judge score means anything, and
the panel runner refuses to run without an explicit override.

**Annotators need nothing from this page.** Send them `pilot_annotator_1.xlsx` and
`pilot_annotator_2.xlsx`; the instructions are on the first sheet of each. This page is for
whoever runs the pilot.

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
- About two hours each, including breaks and reading the rubrics.
- One workbook per person:

```bash
python -m eval.judge.pilot_excel build --annotators alice bob
```

Each workbook holds 28 score cells (arm 1) and 112 tick boxes (arm 2). Arm 3 fills itself in.
The JSON packet is still available for anyone who prefers it:
`python -m eval.judge.pilot prepare --out pilot_packet.json`

The twelve are fixed by hand, not sampled. They cover all five topic categories, four of the five
questions the system should partly decline, and four well-related questions including the
exempt / non-exempt pair.

## The three arms

| Arm | What the annotator does | Scale |
|---|---|---|
| `anchored` | Read the anchor descriptions, pick the level that fits | 1–4 |
| `checklist` | Answer each yes/no item independently | Yes / No |
| `rollup` | **Nothing** — computed from the checklist ticks | 1–4 |

**Three arms, two passes of work.** Arm 3 is arm 2's ticks weighted and banded, so it costs no
annotator time. The workbook derives it with live formulas on its own sheet, so it is visible
rather than taken on trust.

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

## What the pilot does and does not test

Both arms score the same three dimensions: grounding, correctness, and refusal appropriateness.
Refusal items get refusal appropriateness only.

Two rubric dimensions go untested, and this belongs in the write-up:

- **`citation_validity`** — the answers being scored are prose with no inline citations, so there
  is nothing to check a citation against. The anchored rubric drops it automatically; the
  checklist rubric would have kept it, and is aligned to the anchored rubric so the arms stay
  comparable.
- **`temporal_integrity`** — it applies only to `temporal_realtime` items, and the gold set has
  none.

Scoring units are (item × dimension), not items: 28 units per arm rather than 12. That is what
makes agreement on a twelve-item pilot worth reading at all.

## Scoring the pilot

```bash
python -m eval.judge.pilot_excel read --files pilot_alice.xlsx pilot_bob.xlsx
```

That reads both workbooks, writes `pilot_labels.json`, and prints the result. Blank and `NA`
cells become null scores, dropped pairwise and counted openly rather than imputed. If you already
have labels in JSON:

```bash
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

---

# RESULT (run 2026-09-04)

Two annotators, the fixed twelve, 28 scored (item x dimension) units per arm.

| Arm | Cohen's kappa | Units agreed | Wilson 95% on raw agreement | Annotator time |
|---|---|---|---|---|
| anchored | **0.839** weighted / 0.604 unweighted | 20/28 | [0.529, 0.847] | 45 min |
| checklist | 1.000 | 28/28 | [0.879, 1.000] | 30 min |
| rollup | 1.000 | 28/28 | [0.879, 1.000] | derived, free |

Both finished in 75 minutes against the 122-minute estimate.

**Outcome: PASS. `anchored` is the rubric in force** - by explicit decision, not by the
automatic tie-break, which picked `checklist`. See `decisions.md` 036. The selection is recorded
in `rubric.yaml` (`selected: true`), `rubric_checklist.yaml` (`selected: false`) and
`pilot.py:SELECTED_ARM`; `pilot_status` prints a NOTE whenever the recorded decision and the
computed winner differ, which they do here.

## Why the arm with lower agreement was chosen

**A ceiling is not a measurement.** kappa 1.000 has no usable interval. The checklist's 67
Yes/No calls bound true agreement only at [0.946, 1.000], and it beat `rollup` on a speed
tie-break rather than on reliability.

**The checklist cannot see under-refusal.** Three of its four `refusal_appropriateness` items
begin "if it declined", so a response that answered something it should have declined has almost
nothing to fail. Worked case, q021 (Kingman), same annotator, same answer:

| | Score | Why |
|---|---|---|
| anchored | **1** | "It clearly didn't have the evidence it needed to make any kind of claim" |
| rollup | **4.00** | One applicable box, ticked Yes; the other three went NA |

The mirror case, q022 grounding, runs the other way: anchored **4**, rollup **1.00**, because the
checklist forced per-claim scrutiny that the holistic scale let slide.

## The finding the pilot was not designed to produce

Holding the annotator fixed and comparing their own anchored score against their own rollup
score for the same unit:

| | Annotator 1 | Annotator 2 |
|---|---|---|
| Exact match | 16/28 (57%) | 10/28 (36%) |
| Within one level | 24/28 (86%) | 23/28 (82%) |
| Three or more levels apart | 2/28 | 2/28 |
| Weighted kappa between arms | 0.605 | **0.465** |

Annotator 2 agrees with *themselves across the two rubrics* less than the two annotators agree
with *each other* on the anchored arm. The arms are not measuring the same construct. Reliability
is not validity: the checklist agreed more partly because it looks at less.

All three arms are a publishable methods result, and the between-arm disagreement is the most
interesting part of it.

## Where the anchored disagreements fell

Eight units out of 28. Seven were one level apart, one was two levels apart, **none were
opposite verdicts** - a healthy pattern for an ordinal scale.

| By dimension | Count |
|---|---|
| `refusal_appropriateness` | **4** |
| `grounding` | 3 |
| `correctness` | 1 |

| By item | Count |
|---|---|
| q018 (exempt well) | 3 |
| q017 (non-exempt well) | 2 |
| q013, q020, q023 | 1 each |

Both concentrations were predicted. The historical tester data showed all five of its
disagreements clustering on the non-exempt-well question and the address-specific supply
question, and the twelve were hand-picked to sit there. **The item selection worked.**

`refusal_appropriateness` taking 4 of the 8 is evidence that scoring partial refusals on that
dimension alone is too blunt. It is not yet an answer. Open thread 11 stays open.

## Known defect to fix before the checklist is used for anything

`refusal_appropriateness` needs an item that fires when the response answered something it should
have declined, not gated behind "if it declined". The rubric file is deliberately left unmodified
so the arm comparison above stays reproducible.
