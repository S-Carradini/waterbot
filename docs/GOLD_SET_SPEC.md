# Gold set specification

What the judge harness needs from the expanded benchmark, in the exact format it will be read
in. Written for the person authoring the questions, not for the person who wrote the harness.

Target: **150–200 questions with verified gold answers**, per Section 12 of
`AI_as_Judge_Architecture.docx`, which makes this a precondition rather than an extension.

Run the validator as you go. It is designed to be run on a half-finished file:

```bash
python -m eval.validate_gold_set eval/benchmark_dataset.json
python -m eval.validate_gold_set eval/benchmark_dataset.json --strict   # CI mode
```

It reports per-rule pass/fail with question ids, and exits non-zero on any error.

---

## 1. The one rule that matters most

**Author every question from the corpus outward, never from a citation list inward.**

The current answer key was authored from `knowledge_sources.py`, a 503-entry URL mapping, rather
than from the 366 documents actually in the vector store. Nineteen named documents did not
exist. Four questions are still quarantined because of it.

Concretely, the required order is:

1. Open a document that is **in the vector store**.
2. Find a passage in it that supports a specific, checkable claim.
3. Write the question from that passage.
4. Copy the supporting text verbatim into `gold_answer_evidence`.
5. Write `gold_answer` so that every clause in it is supported by that quoted text.

If you cannot paste the supporting sentence, the question is not ready. That single discipline
is what makes a gold answer "verified" rather than "plausible", and it is mechanically checked
by the validator.

---

## 2. File format

Extend the existing `eval/benchmark_dataset.json`. Do not start a new file — the harness, the
retrieval metrics and the repair tooling all read this path.

```json
{
  "_meta": {
    "version": "1.0.0",
    "status": "VERIFIED",
    "created": "2026-07-12",
    "last_reviewed": "2026-09-01",
    "total_questions": 175,
    "category_distribution": { "general_policy": 40, "...": 0 },
    "corpus_fingerprint_at_authoring": "08527fbdf140f811",
    "notes": "free text"
  },
  "questions": [ { "...": "one object per question, fields below" } ]
}
```

`corpus_fingerprint_at_authoring` is new and matters: it records which corpus state the answers
were checked against, so that when the corpus is repaired we know which answers need re-checking
rather than guessing.

---

## 3. Fields

### Required on every question

| Field | Type | Rule |
|---|---|---|
| `id` | string | `q###`, unique, zero-padded, never reused after deletion |
| `question` | string | 10–300 chars. One question, not two joined by "and" |
| `category` | string | exactly one of the six in §4 |
| `gold_answer` | string | see §5. For negatives, the expected refusal behaviour |
| `gold_source_ids` | list[string] | document names **as they appear in the vector store**. Empty list only for `out_of_scope_negative` |
| `notes` | string | why this question exists, what it probes. May be empty but must be present |

### Required on every question except `out_of_scope_negative`

| Field | Type | Rule |
|---|---|---|
| `gold_answer_evidence` | list[object] | **the new critical field.** See §5 |
| `verification` | object | who checked it and when. See §6 |

### Required on `numeric_extraction` and `temporal_realtime`

| Field | Type | Rule |
|---|---|---|
| `gold_passage_keywords` | list[string] | distinctive strings that must appear in a correctly retrieved passage — the number itself, its unit, the entity. Used to score retrieval without an LLM |

### Required on `out_of_scope_negative`

| Field | Type | Rule |
|---|---|---|
| `refusal_type` | string | one of `geographic`, `temporal_unknowable`, `personal_advice`, `out_of_domain`, `privacy`, `capability` |
| `acceptable_redirect` | bool | whether a helpful pointer elsewhere is acceptable, or the system should decline flatly |

`refusal_type` is not bookkeeping. Refusal is a scored rubric dimension across *all* questions,
so the harness needs to distinguish "correctly refused a 2030 prediction" from "wrongly refused
an answerable policy question". Without the type, over-refusal and correct refusal collapse into
one number.

### Optional

| Field | Type | Meaning |
|---|---|---|
| `subcategory` | string | free label, e.g. `tribal_settlement`, `shortage_tier` |
| `difficulty` | string | `single_passage`, `multi_passage`, `synthesis` |
| `excluded_from_scoring` | bool | quarantine. Requires `exclusion_reason` |
| `exclusion_reason` | string | why |
| `repair` | object | audit record if the question was edited after authoring. Preserve, do not delete |

---

## 4. Category targets

Keep the existing six. Do not invent new ones — six categories are already baked into the
rubric's `applies_to` rules, the report tables and the ablation grid.

| Category | Now | Target | What it probes |
|---|---|---|---|
| `general_policy` | 15 | 40–45 | AMAs, CAP, groundwater code |
| `entity_grounding` | 10 | 30–35 | attribution to the right tribe, city, agency |
| `numeric_extraction` | 8 | 25–30 | allocations, volumes, percentages, units |
| `multi_hop` | 8 | 25–30 | reasoning across two or more documents |
| `temporal_realtime` | 7 | 20–25 | current levels, shortage tiers, staleness |
| `out_of_scope_negative` | 12 | 20–25 | questions the system must refuse |
| **Total** | **60** | **160–190** | |

Why these proportions: the doc notes that at n=7–15 a single question moves a category mean by
7–14 points, so per-category claims are not currently supportable. At n≈25 one question moves
the mean about 4 points, which is under the effect sizes we expect to report. `general_policy`
stays largest because it is the broadest construct; `numeric_extraction` and `entity_grounding`
matter most for the failure modes the paper is about, so they grow proportionally more than
`general_policy` does.

**Keep at least 12 negatives that are unchanged from today's set.** Milestone 1's instability
measurement is on the current 12; changing them out from under it would break comparability with
the motivating result.

---

## 5. Gold answers and evidence

### `gold_answer`

- 1–4 sentences. Long enough to contain the checkable facts, short enough that a human can
  compare it to a response quickly.
- Every factual clause must be supported by `gold_answer_evidence`.
- No hedging language, no "approximately" unless the source hedges.
- Units always explicit and always as the source states them. `acre-feet` and `acre-feet per
  year` are different quantities and conflating them is one of the four named failure modes.
- For `out_of_scope_negative`, write what a correct refusal looks like, as today.

### `gold_answer_evidence` — the field that makes it verified

```json
"gold_answer_evidence": [
  {
    "source_id": "USBR 24-Month Studies.pdf",
    "quote": "a total of 0.598 maf will be held back in Lake Powell from December 2025 through April 2026",
    "locator": "p. 4, Table 2"
  }
]
```

| Key | Rule |
|---|---|
| `source_id` | must also appear in `gold_source_ids` |
| `quote` | **verbatim** from the document. Not paraphrased, not reflowed. 10–500 chars |
| `locator` | page, section or table, enough for a reviewer to find it in under a minute |

At least one entry per question. `multi_hop` questions need **at least two entries from
different `source_id`s** — that is what makes them multi-hop rather than aspirationally so, and
the validator enforces it.

The quotes are not decoration. They become the reference condition in RQ3 (evidence-grounded
versus reference-based judging), and they let the harness check citation validity mechanically,
without an LLM in the loop.

---

## 6. Verification record

```json
"verification": {
  "status": "verified",
  "verified_by": "initials or role, not full names",
  "verified_on": "2026-09-01",
  "method": "read_source",
  "second_reviewer": "initials",
  "disagreement": null
}
```

| Key | Allowed values |
|---|---|
| `status` | `verified`, `pending`, `disputed` |
| `method` | `read_source` (opened the document and read the passage), `domain_expert` (subject knowledge, source located after) |
| `second_reviewer` | required when `status` is `verified`. Null otherwise |
| `disagreement` | free text if the two reviewers disagreed and how it resolved. Keep the record, do not overwrite it |

**Two people per question, and the second person must be able to find the quote from the
locator alone.** That is the review protocol Section 12 asks for to stop a repeat of the
citation-mapping error. A question with `status: verified` and no `second_reviewer` fails
validation.

Use initials or roles, never full names — the file is destined for public release.

---

## 7. What the validator checks

Errors (exit non-zero):

1. Duplicate or malformed `id`
2. Unknown `category`
3. Missing required field for the category
4. `gold_source_ids` empty on a non-negative question
5. `gold_answer_evidence` missing, empty, or with a `source_id` not in `gold_source_ids`
6. `quote` outside 10–500 chars
7. `multi_hop` with fewer than two distinct evidence sources
8. `status: verified` without a `second_reviewer`
9. `excluded_from_scoring` without an `exclusion_reason`
10. Category counts below the §4 minimum (only under `--strict`)

Warnings (reported, exit zero):

- `gold_source_ids` naming a document not in the corpus — needs a live database, so it is
  skipped when one is not configured. `eval/preflight.py` is the authoritative check for this
  and should be run before any paper-grade run.
- `question` over 300 chars, or containing " and " twice (often two questions in a trench coat)
- `numeric_extraction` whose `gold_answer` contains no digit
- Category counts below target but above minimum

The corpus-existence check is the one that caught the original 19 missing documents, so run
`python -m eval.preflight` against a live database before declaring the set finished.

---

## 8. What I do not need from you

To be explicit about the boundary, since these are easy to confuse with the gold set:

- **Expert rubric labels** (humans scoring responses 1–4 on grounding, correctness, and so on).
  These come out of the annotation UI I am building in L4, in its own format, from your
  annotators. You do not author these by hand.
- **Frozen bot responses.** The harness generates and freezes these itself in L1.
- **The corpus repair.** Separate track, open thread #5.

---

## 9. Suggested order of work

1. Fix the 4 quarantined questions or drop them. They are already flagged.
2. Add `gold_answer_evidence` and `verification` to the existing 56. This is the slowest part
   and it is pure verification, no authoring — and it converts the set from "sources validated,
   answers unverified" to actually verified.
3. Author new questions category by category, largest gap first: `general_policy`,
   `entity_grounding`, `numeric_extraction`.
4. Run `--strict` and fix what it reports.
5. Run `eval/preflight.py` against the live database for the corpus-existence check.

Step 2 before step 3. An expanded set with unverified answers is a bigger version of the current
problem, and Section 15 already lists unverified gold answers as a high-severity threat.
