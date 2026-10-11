"""Build the human-evaluator workbook for the qualitative round.

WHAT IS BEING RATED. Not the chatbot. The JUDGE. Each row puts one judge's written judgement of
one chatbot answer in front of a human, who scores whether that judgement is intelligible and
sensible against the ten plain-language criteria already in the workbook.

This is deliberately not an agreement study. Agreement - does the judge land on the same number
as a human - is what Cohen's kappa measures, and the factual pipeline already does it. A judge
can reach the right score through incoherent reasoning and score perfectly on agreement. Whether
the reasoning holds together is not reducible to a metric, so a human has to read it. That is the
contribution this round exists to support.

ONE ROW PER (QUESTION, JUDGE), NOT PER SAMPLE. Measured on the q019 smoke run: within a judge,
20 of 21 dimension-sets were unanimous across k=5 at temperature 0 - only gemma's `tone` varied.
Between judges, `plain_language` spanned 2 to 4. The repeats carry almost no information; the
judges carry all of it. Ten questions x three judges is 30 ratable rows. Collapsing to one row
per question would discard the between-judge signal, which is the interesting half; 150 rows
(every sample) would not get rated at all.
"""
from __future__ import annotations

import json
import os
import statistics
from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence

SHEET = "Response Evaluation"
QUESTION_COL = 3
ANSWER_COL = 4          # "Chatbot Answer" in the template - now holds RealWaterBot's real answer
TOTAL_COL = 15         # =SUM(E:N)
PERCENT_COL = 16       # =O/10
JUDGEMENT_COL = 17     # NEW: "AI Judge's Written Judgement", appended after Percent


def chatbot_answers_from(path: str) -> Dict[str, str]:
    """item_id -> the chatbot's frozen answer, from a responses/*.jsonl."""
    out: Dict[str, str] = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            out[str(d["item_id"])] = str(d.get("answer", ""))
    return out


def representative_sample(verdicts: Sequence[Any]) -> Any:
    """The sample that best represents a judge's view of one item.

    Picks the sample whose scores sit closest to that judge's own median on every dimension, so
    the text a human reads is the reasoning behind the judge's typical verdict rather than an
    outlier. Ties break on the lowest sample index, which keeps the choice reproducible.
    """
    if not verdicts:
        raise ValueError("no verdicts to choose from")
    if len(verdicts) == 1:
        return verdicts[0]

    dimensions = sorted(verdicts[0].dimensions)
    medians: Dict[str, Optional[float]] = {}
    for dim in dimensions:
        scored = [
            v.dimensions[dim].score for v in verdicts
            if dim in v.dimensions and v.dimensions[dim].score is not None
        ]
        medians[dim] = statistics.median(scored) if scored else None

    def distance(verdict: Any) -> tuple:
        total = 0.0
        for dim in dimensions:
            median = medians[dim]
            entry = verdict.dimensions.get(dim)
            if median is None or entry is None or entry.score is None:
                continue
            total += abs(entry.score - median)
        return (total, verdict.sample_index)

    return min(verdicts, key=distance)


def render_judgement(verdict: Any, include_scores: bool) -> str:
    """The judge's judgement as a human will read it.

    `include_scores` is a real methodological choice, not a formatting one. With scores shown, a
    rater can check whether the reasoning supports the number, but tends to drift into rating
    whether they AGREE with the number. Without them, the rating isolates reasoning quality,
    which is the construct this round is actually measuring.
    """
    blocks: List[str] = []
    for dim in sorted(verdict.dimensions):
        entry = verdict.dimensions[dim]
        header = dim.replace("_", " ").upper()
        if include_scores:
            shown = "abstained" if entry.score is None else f"{entry.score}/4"
            header = f"{header} — {shown}"
        lines = [header]
        if entry.quoted_span:
            lines.append(f'  quoting: "{entry.quoted_span.strip()}"')
        lines.append(f"  {entry.rationale.strip()}")
        blocks.append("\n".join(lines))

    if verdict.failure_modes:
        blocks.append("PROBLEMS IDENTIFIED\n  " + ", ".join(sorted(verdict.failure_modes)))
    return "\n\n".join(blocks)


def load_verdicts(paths: Sequence[str]) -> List[Any]:
    from eval.judge.schemas import Verdict

    verdicts: List[Verdict] = []
    for path in paths:
        if not os.path.exists(path):
            raise SystemExit(f"no verdict file at {path}")
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    verdicts.append(Verdict.model_validate_json(line))
    if not verdicts:
        raise SystemExit("no verdicts to write")
    return verdicts


def build(
    template: str,
    out: str,
    verdicts: Sequence[Any],
    include_scores: bool = False,
    blind_judge_names: bool = True,
    chatbot_answers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Write one row per (question, judge) into a copy of the evaluator workbook.

    Layout per row: the Test Question (col C), the chatbot's actual answer (col D, filled from
    `chatbot_answers` when given), the human scoring grid (E-N) with its Total/Percent formulas,
    and the AI judge's written judgement (col Q). The rater sees the question, what the chatbot
    said, and what the judge said about it.
    """
    import openpyxl
    from openpyxl.styles import Alignment

    answers = chatbot_answers or {}
    workbook = openpyxl.load_workbook(template)
    ws = workbook[SHEET]

    header_row = next(
        r for r in range(1, ws.max_row + 1)
        if str(ws.cell(row=r, column=QUESTION_COL).value or "").strip().lower() == "test question"
    )

    # The original question rows, in order, keyed by the item_id the freeze assigned.
    originals: List[Dict[str, Any]] = []
    for r in range(header_row + 1, ws.max_row + 1):
        number = ws.cell(row=r, column=1).value
        question = ws.cell(row=r, column=QUESTION_COL).value
        # The workbook carries a Summary block below the questions, whose column A holds labels
        # like "Average Score". A question row is one whose number is genuinely a number.
        if question is None or not str(question).strip():
            continue
        try:
            number = int(number)
        except (TypeError, ValueError):
            continue
        originals.append({
            "row": r,
            "number": number,
            "item_id": f"Q{int(number):02d}",
            "difficulty": ws.cell(row=r, column=2).value,
            "question": str(question),
        })

    by_item_judge: Dict[str, Dict[str, List[Any]]] = defaultdict(lambda: defaultdict(list))
    for v in verdicts:
        by_item_judge[v.item_id][v.judge_model_id].append(v)

    judges = sorted({v.judge_model_id for v in verdicts})
    # Blinded so a rater cannot form an opinion of a vendor and apply it to every row. The
    # mapping is written to the key file, not into the sheet the rater sees.
    labels = {j: f"Judge {chr(ord('A') + i)}" for i, j in enumerate(judges)}

    # Rewrite the block of question rows as (question x judge) rows.
    first_row = header_row + 1
    ws.delete_rows(first_row, max(len(originals), 1))

    written = 0
    rows_written: List[Dict[str, Any]] = []
    cursor = first_row
    for original in originals:
        for judge in judges:
            samples = by_item_judge.get(original["item_id"], {}).get(judge, [])
            if not samples:
                continue
            chosen = representative_sample(samples)
            ws.insert_rows(cursor)
            ws.cell(row=cursor, column=1).value = original["number"]
            ws.cell(row=cursor, column=2).value = original["difficulty"]
            ws.cell(row=cursor, column=QUESTION_COL).value = original["question"]
            # Column D keeps its "Chatbot Answer" meaning - the chatbot's real answer, repeated
            # on both of this question's judge rows.
            ws.cell(row=cursor, column=ANSWER_COL).value = answers.get(original["item_id"], "")
            # Column Q: the AI judge's written judgement (blinded).
            ws.cell(row=cursor, column=JUDGEMENT_COL).value = render_judgement(
                chosen, include_scores)
            # The scoring formulas follow the row as it moves.
            ws.cell(row=cursor, column=TOTAL_COL).value = f"=SUM(E{cursor}:N{cursor})"
            ws.cell(row=cursor, column=PERCENT_COL).value = f"=O{cursor}/10"
            for col in (QUESTION_COL, ANSWER_COL, JUDGEMENT_COL):
                ws.cell(row=cursor, column=col).alignment = Alignment(
                    wrap_text=True, vertical="top")
            ws.row_dimensions[cursor].height = 260
            rows_written.append({
                "row": cursor,
                "item_id": original["item_id"],
                "question_number": original["number"],
                "judge_model_id": judge,
                "judge_label": labels[judge],
                "sample_index": chosen.sample_index,
                "scores": {d: e.score for d, e in sorted(chosen.dimensions.items())},
                "failure_modes": sorted(chosen.failure_modes),
            })
            cursor += 1
            written += 1

    ws.column_dimensions["C"].width = 52
    ws.column_dimensions["D"].width = 70
    ws.column_dimensions["Q"].width = 96

    # Column D keeps the template's "Chatbot Answer" header. Column Q gets the judgement header.
    ws.cell(row=header_row, column=JUDGEMENT_COL).value = "AI Judge's Written Judgement"

    workbook.save(out)
    return {"rows": written, "judges": labels, "detail": rows_written}
