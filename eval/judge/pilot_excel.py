"""The rubric pilot as a spreadsheet, for annotators who do not work in JSON.

Produces one .xlsx per annotator with an instructions sheet, one sheet per arm, an anchor
reference, and a time log. Scores go straight into cells with dropdowns, so there is nothing to
install and nothing to get syntactically wrong. `read_workbook` turns a returned file back into
`PilotLabel`s, which are scored by the unchanged `pilot.arm_results`.

THREE ARMS, TWO PASSES OF WORK
------------------------------
Arm 3 is not separate annotation. `ChecklistScore.fraction` is arm 2's number and
`ChecklistScore.rolled_up()` is arm 3's, computed from the *same ticks*. So the annotator fills
in arm 1 and arm 2, and the arm 3 sheet derives itself with live formulas - visibly, as they
tick, so nothing about it looks like a black box.

WHICH DIMENSIONS GET SCORED
---------------------------
Both arms score the same set, which is not what the two rubric files say on their own. The
anchored rubric gates `citation_validity` behind `requires_citations`, and the answers in this
pilot carry no inline citations, so it drops out. The checklist rubric has no such gate and would
have kept it. Left alone, arm 2 and arm 3 would score a dimension arm 1 does not, and the
agreement numbers would not be comparable - which is the one thing the pilot exists to compare.
`pilot_dimensions` therefore takes the anchored rubric's applicability as authoritative for both.

The cost is that `citation_validity` and `temporal_integrity` go untested by this pilot: the
first because these answers do not cite, the second because no gold item is `temporal_realtime`.
Both are real gaps and belong in the write-up rather than being papered over.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from eval.gold_set import GoldItem
from eval.judge.checklist import ChecklistRubric, load_checklist
from eval.judge.pilot import ARMS, PilotError, PilotLabel
from eval.judge.rubric import Rubric, load_rubric

SHEET_START = "START HERE"
SHEET_ANCHORED = "Arm 1 - Anchored"
SHEET_CHECKLIST = "Arm 2 - Checklist"
SHEET_ROLLUP = "Arm 3 - Rollup (auto)"
SHEET_ANCHORS = "Anchor reference"
SHEET_TIME = "Time log"

NOT_APPLICABLE = "NA"
ANCHORED_CHOICES = ("1", "2", "3", "4", NOT_APPLICABLE)
TICK_CHOICES = ("Yes", "No", NOT_APPLICABLE)

# Time model, derived from the cell counts rather than asserted. Reading an item dominates the
# first pass; ticking dominates the second, and the re-read is faster because the item is
# already familiar.
ONBOARDING_MINUTES = 30.0
MINUTES_FIRST_READ = 2.0
MINUTES_REREAD = 1.0
MINUTES_PER_ANCHORED_CELL = 1.0
MINUTES_PER_TICK = 0.25

_HEADER_FILL = PatternFill("solid", fgColor="1F3864")
_ITEM_FILL = PatternFill("solid", fgColor="DDEBF7")
_INPUT_FILL = PatternFill("solid", fgColor="FFF2CC")
_REFUSE_FILL = PatternFill("solid", fgColor="FCE4D6")
_HEADER_FONT = Font(bold=True, color="FFFFFF", size=11)
_THIN = Side(style="thin", color="BFBFBF")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_WRAP = Alignment(wrap_text=True, vertical="top")
_CENTRE = Alignment(horizontal="center", vertical="center")


class ExcelPilotError(PilotError):
    """The workbook cannot be built or read as asked."""


# ---------------------------------------------------------------------------
# What gets scored
# ---------------------------------------------------------------------------
def pilot_dimensions(
    item: GoldItem,
    rubric: Optional[Rubric] = None,
) -> List[str]:
    """Dimensions scored for one item, in BOTH arms.

    The anchored rubric is authoritative. See the module docstring: letting each rubric decide
    independently makes the arms score different things and the comparison meaningless.

    ``has_citations=False`` because the answers in this pilot are prose with no inline citation
    markers. That is a fact about the material, not a setting to tune.
    """
    rubric = rubric or load_rubric()
    return list(
        rubric.applicable_names(
            item.category,
            has_citations=False,
            is_negative=item.should_refuse,
        )
    )


def checklist_rows(
    item: GoldItem,
    checklist: Optional[ChecklistRubric] = None,
    rubric: Optional[Rubric] = None,
) -> List[Tuple[str, str, int, str]]:
    """``(dimension, item_id, weight, text)`` for every tick box on one item."""
    checklist = checklist or load_checklist()
    rows: List[Tuple[str, str, int, str]] = []
    for dimension in pilot_dimensions(item, rubric):
        try:
            target = checklist.get(dimension)
        except Exception as error:  # dimension exists in one rubric but not the other
            raise ExcelPilotError(
                f"the checklist rubric has no dimension {dimension!r}, which the anchored rubric "
                "scores; the two rubrics have drifted apart and the arms would not be comparable"
            ) from error
        for entry in target.items:
            rows.append((dimension, entry.id, entry.weight, entry.text))
    return rows


@dataclass
class WorkloadEstimate:
    """How much work the built workbook actually contains."""

    n_items: int
    anchored_cells: int
    tick_boxes: int
    minutes: int

    def summary(self) -> str:
        return (
            f"{self.n_items} items, {self.anchored_cells} anchored score cells, "
            f"{self.tick_boxes} tick boxes -> about {self.minutes} min "
            f"({self.minutes / 60:.1f} h) per annotator"
        )


def estimate_workload(
    items: Sequence[GoldItem],
    rubric: Optional[Rubric] = None,
    checklist: Optional[ChecklistRubric] = None,
) -> WorkloadEstimate:
    """Derive the time from the real cell counts, for two annotated arms.

    Arm 3 contributes nothing: it is computed from arm 2's ticks.
    """
    rubric = rubric or load_rubric()
    checklist = checklist or load_checklist()

    anchored_cells = sum(len(pilot_dimensions(i, rubric)) for i in items)
    ticks = sum(len(checklist_rows(i, checklist, rubric)) for i in items)

    minutes = (
        ONBOARDING_MINUTES
        + len(items) * MINUTES_FIRST_READ
        + anchored_cells * MINUTES_PER_ANCHORED_CELL
        + len(items) * MINUTES_REREAD
        + ticks * MINUTES_PER_TICK
    )
    return WorkloadEstimate(
        n_items=len(items),
        anchored_cells=anchored_cells,
        tick_boxes=ticks,
        minutes=int(round(minutes)),
    )


# ---------------------------------------------------------------------------
# Building the workbook
# ---------------------------------------------------------------------------
def _header(sheet: Any, row: int, labels: Sequence[str], widths: Sequence[int]) -> None:
    for column, (label, width) in enumerate(zip(labels, widths), start=1):
        cell = sheet.cell(row=row, column=column, value=label)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = _CENTRE
        cell.border = _BORDER
        sheet.column_dimensions[get_column_letter(column)].width = width
    sheet.freeze_panes = sheet.cell(row=row + 1, column=1)


def _item_banner(sheet: Any, row: int, item: GoldItem, span: int) -> int:
    """Write the question / answer / evidence block for one item. Returns the next free row."""
    kind = "SHOULD PARTLY DECLINE" if item.should_refuse else "should answer"
    fill = _REFUSE_FILL if item.should_refuse else _ITEM_FILL

    for label, text in (
        (f"{item.id}  ({kind})  -  {item.category}", None),
        ("QUESTION", item.question),
        ("ANSWER being scored", item.answer),
        ("EVIDENCE available", " ".join(item.source_quote) or "(none)"),
    ):
        cell = sheet.cell(row=row, column=1, value=label)
        cell.font = Font(bold=True, size=10)
        cell.alignment = _WRAP
        cell.fill = fill
        if text is not None:
            sheet.merge_cells(start_row=row, start_column=2, end_row=row, end_column=span)
            body = sheet.cell(row=row, column=2, value=text)
            body.alignment = _WRAP
            body.fill = fill
        else:
            sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=span)
        sheet.row_dimensions[row].height = 15 if text is None else 42
        row += 1
    return row


def _instructions(
    workbook: Workbook, items: Sequence[GoldItem], estimate: WorkloadEstimate
) -> Any:
    sheet = workbook.create_sheet(SHEET_START, 0)
    sheet.column_dimensions["A"].width = 4
    sheet.column_dimensions["B"].width = 110

    n_refuse = sum(1 for i in items if i.should_refuse)
    lines: List[Tuple[str, str]] = [
        ("h1", "Rubric pilot - please read this page first"),
        ("p", ""),
        ("p", "Thank you for doing this. It takes about "
              f"{estimate.minutes} minutes ({estimate.minutes / 60:.1f} hours) including breaks."),
        ("p", ""),
        ("h2", "What we are trying to find out"),
        ("p", "We are about to let an AI score thousands of answers about Arizona water policy. "
              "Before we trust it, we need to know whether two knowledgeable people, given the "
              "same rubric and the same answer, land on the same score."),
        ("p", "If two people cannot agree, the rubric is the problem, and no AI can fix that. "
              "That is the whole question here. You are not being tested - the rubric is."),
        ("p", ""),
        ("h2", "What you do"),
        ("p", "Two sheets need your input:"),
        ("p", f"   Arm 1 - Anchored   -  give each row a score from 1 to 4 "
              f"({estimate.anchored_cells} cells)"),
        ("p", f"   Arm 2 - Checklist  -  answer each row Yes or No "
              f"({estimate.tick_boxes} cells)"),
        ("p", ""),
        ("p", "Arm 3 fills itself in from your Arm 2 answers. You do not type anything there. "
              "It is on its own sheet so you can see how it works."),
        ("p", ""),
        ("p", "Yellow cells are the ones you fill in. Every one has a dropdown - click the cell "
              "and pick. You can also just type the value."),
        ("p", ""),
        ("h2", "Six rules"),
        ("p", "1.  Finish ALL of Arm 1 before you open Arm 2. Do not go back and forth. If you "
              "score something 3 in Arm 1 and then immediately fill in its checklist, you will "
              "make the checklist match the 3 - and we will have measured your memory instead of "
              "the rubric. Take a break between the two sheets."),
        ("p", "2.  Score the ANSWER, not the question. A weak question with a well-handled "
              "answer still scores well."),
        ("p", "3.  Judge only against the EVIDENCE shown on the row. Do not look anything up. If "
              "you cannot tell whether a claim is supported from what is in front of you, that IS "
              "the finding - score it as unsupported."),
        ("p", "4.  If something genuinely does not apply, put NA. Do not guess a middle value. A "
              "guessed 2 is worse for us than a blank."),
        ("p", "5.  Do not discuss any item with the other annotator until you have both "
              "finished. The entire measurement is how much you agree WITHOUT coordinating."),
        ("p", "6.  Fill in the Time log sheet at the end. Roughly is fine."),
        ("p", ""),
        ("h2", f"Watch for these: {n_refuse} of the {len(items)} questions should be partly declined"),
        ("p", "They have an orange header and say SHOULD PARTLY DECLINE."),
        ("p", "They are not blank refusals. Each one turns down the part that cannot be answered, "
              "then states a correct general fact. For example, asked whether a specific address "
              "in Holbrook has an assured water supply, the right answer refuses the address "
              "lookup, then correctly notes that Holbrook is outside any AMA - so the applicable "
              "programme is 'adequate' water supply, not 'assured'."),
        ("p", "These answers do two things at once, and we honestly do not know whether the "
              "rubric can score them consistently. THIS IS THE CASE WE MOST NEED YOUR JUDGEMENT "
              "ON. If you find one hard to score, write why in the Notes column. That note is "
              "worth as much to us as the score."),
        ("p", ""),
        ("h2", "When you are done"),
        ("p", "Save the file with your name in it and send it back. Nothing else needed."),
    ]

    row = 2
    for kind, text in lines:
        cell = sheet.cell(row=row, column=2, value=text)
        if kind == "h1":
            cell.font = Font(bold=True, size=16, color="1F3864")
        elif kind == "h2":
            cell.font = Font(bold=True, size=12, color="1F3864")
        else:
            cell.font = Font(size=11)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            if len(text) > 95:
                sheet.row_dimensions[row].height = 15 * (len(text) // 95 + 1)
        row += 1
    return sheet


def _anchored_sheet(workbook: Workbook, items: Sequence[GoldItem], rubric: Rubric) -> Any:
    sheet = workbook.create_sheet(SHEET_ANCHORED)
    _header(
        sheet, 1,
        ["Item / Dimension", "What this dimension asks", "Score 1-4", "Notes (optional)"],
        [30, 78, 12, 44],
    )

    validation = DataValidation(
        type="list", formula1='"' + ",".join(ANCHORED_CHOICES) + '"', allow_blank=True,
        showDropDown=False, errorTitle="Not a valid score",
        error="Pick 1, 2, 3, 4 or NA.", promptTitle="Score", prompt="1 = worst, 4 = best.",
    )
    sheet.add_data_validation(validation)

    row = 3
    for item in items:
        row = _item_banner(sheet, row, item, span=4)
        for dimension in pilot_dimensions(item, rubric):
            sheet.cell(row=row, column=1, value=dimension).font = Font(bold=True, size=10)
            question = rubric.get(dimension).question
            body = sheet.cell(row=row, column=2, value=question)
            body.alignment = _WRAP
            score = sheet.cell(row=row, column=3)
            score.fill = _INPUT_FILL
            score.border = _BORDER
            score.alignment = _CENTRE
            validation.add(score)
            sheet.cell(row=row, column=4).fill = _INPUT_FILL
            sheet.cell(row=row, column=4).alignment = _WRAP
            sheet.row_dimensions[row].height = 30
            row += 1
        row += 1
    return sheet


def _checklist_sheet(
    workbook: Workbook, items: Sequence[GoldItem], rubric: Rubric, checklist: ChecklistRubric
) -> Dict[str, Tuple[int, int]]:
    """Build arm 2 and return ``{item_id: (first_row, last_row)}`` for the rollup formulas."""
    sheet = workbook.create_sheet(SHEET_CHECKLIST)
    _header(
        sheet, 1,
        ["Item / Dimension", "Tick box - is this true?", "Yes / No", "Weight", "Notes (optional)"],
        [30, 78, 11, 8, 40],
    )

    validation = DataValidation(
        type="list", formula1='"' + ",".join(TICK_CHOICES) + '"', allow_blank=True,
        showDropDown=False, errorTitle="Not a valid answer",
        error="Pick Yes, No or NA.", promptTitle="Yes or No",
        prompt="Is this statement true of the answer?",
    )
    sheet.add_data_validation(validation)

    spans: Dict[str, Tuple[int, int]] = {}
    row = 3
    for item in items:
        row = _item_banner(sheet, row, item, span=5)
        first = row
        for dimension, entry_id, weight, text in checklist_rows(item, checklist, rubric):
            label = sheet.cell(row=row, column=1, value=f"{dimension}  /  {entry_id}")
            label.font = Font(size=9)
            label.alignment = _WRAP
            body = sheet.cell(row=row, column=2, value=text)
            body.alignment = _WRAP
            tick = sheet.cell(row=row, column=3)
            tick.fill = _INPUT_FILL
            tick.border = _BORDER
            tick.alignment = _CENTRE
            validation.add(tick)
            sheet.cell(row=row, column=4, value=weight).alignment = _CENTRE
            sheet.cell(row=row, column=5).fill = _INPUT_FILL
            sheet.row_dimensions[row].height = 28
            row += 1
        spans[item.id] = (first, row - 1)
        row += 1
    return spans


def _rollup_sheet(
    workbook: Workbook,
    items: Sequence[GoldItem],
    spans: Dict[str, Tuple[int, int]],
    checklist: ChecklistRubric,
) -> Any:
    """Arm 3, as live formulas over arm 2 so the annotator can see it is not a black box."""
    sheet = workbook.create_sheet(SHEET_ROLLUP)
    _header(
        sheet, 1,
        ["Item", "Weight earned", "Weight possible", "Share earned", "Arm 3 score"],
        [16, 15, 17, 14, 14],
    )

    # `ChecklistRubric.bands` is already ((min, score), ...) in descending order.
    bands = list(checklist.bands)

    note = sheet.cell(row=2, column=1, value="This sheet fills itself in from Arm 2. Nothing to do here.")
    note.font = Font(italic=True, size=10)
    sheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=5)

    row = 3
    quoted = f"'{SHEET_CHECKLIST}'"
    for item in items:
        first, last = spans[item.id]
        ticks = f"{quoted}!$C${first}:$C${last}"
        weights = f"{quoted}!$D${first}:$D${last}"
        sheet.cell(row=row, column=1, value=item.id)
        sheet.cell(row=row, column=2, value=f'=SUMIF({ticks},"Yes",{weights})')
        # NA rows leave the denominator alone: an inapplicable box should not count against.
        sheet.cell(row=row, column=3, value=f'=SUM({weights})-SUMIF({ticks},"NA",{weights})')
        sheet.cell(row=row, column=4, value=f'=IF(C{row}=0,"",B{row}/C{row})').number_format = "0%"
        conditions = "".join(f'IF(D{row}>={low},{score},' for low, score in bands[:-1])
        sheet.cell(
            row=row, column=5,
            value=f'=IF(D{row}="","",{conditions}{bands[-1][1]}{")" * (len(bands) - 1)})',
        ).alignment = _CENTRE
        row += 1
    return sheet


def _anchor_reference(workbook: Workbook, items: Sequence[GoldItem], rubric: Rubric) -> Any:
    sheet = workbook.create_sheet(SHEET_ANCHORS)
    _header(sheet, 1, ["Dimension", "Score", "What that score means"], [28, 8, 100])

    used: List[str] = []
    for item in items:
        for name in pilot_dimensions(item, rubric):
            if name not in used:
                used.append(name)

    row = 2
    for name in used:
        dimension = rubric.get(name)
        header = sheet.cell(row=row, column=1, value=name)
        header.font = Font(bold=True, size=11)
        sheet.merge_cells(start_row=row, start_column=2, end_row=row, end_column=3)
        question = sheet.cell(row=row, column=2, value=dimension.question)
        question.font = Font(italic=True)
        question.alignment = _WRAP
        sheet.row_dimensions[row].height = 28
        row += 1
        for level in (4, 3, 2, 1):
            anchor = dimension.anchors.get(level)
            sheet.cell(row=row, column=2, value=level).alignment = _CENTRE
            text = sheet.cell(row=row, column=3, value=(anchor or "").strip())
            text.alignment = _WRAP
            sheet.row_dimensions[row].height = 32
            row += 1
        row += 1
    return sheet


def _time_log(workbook: Workbook) -> Any:
    sheet = workbook.create_sheet(SHEET_TIME)
    _header(sheet, 1, ["", "Minutes you spent", "Anything that slowed you down"], [30, 18, 70])
    for offset, label in enumerate(("Arm 1 - Anchored", "Arm 2 - Checklist")):  # arm 3 is free
        sheet.cell(row=2 + offset, column=1, value=label).font = Font(bold=True)
        cell = sheet.cell(row=2 + offset, column=2)
        cell.fill = _INPUT_FILL
        cell.border = _BORDER
        sheet.cell(row=2 + offset, column=3).fill = _INPUT_FILL
    note = sheet.cell(
        row=5, column=1,
        value="Roughly is fine. We use this only to break a tie between two rubrics that agree "
              "about equally well - the faster one wins, because annotator time is our real "
              "constraint.",
    )
    note.font = Font(italic=True, size=10)
    note.alignment = _WRAP
    sheet.merge_cells(start_row=5, start_column=1, end_row=5, end_column=3)
    return sheet


def build_workbook(
    items: Sequence[GoldItem],
    path: str,
    annotator_id: str = "",
    rubric: Optional[Rubric] = None,
    checklist: Optional[ChecklistRubric] = None,
) -> WorkloadEstimate:
    """Write one annotator's workbook. Returns what it actually asks of them."""
    if not items:
        raise ExcelPilotError("cannot build a workbook with no items")

    rubric = rubric or load_rubric()
    checklist = checklist or load_checklist()
    estimate = estimate_workload(items, rubric, checklist)

    workbook = Workbook()
    workbook.remove(workbook.active)

    _instructions(workbook, items, estimate)
    _anchored_sheet(workbook, items, rubric)
    spans = _checklist_sheet(workbook, items, rubric, checklist)
    _rollup_sheet(workbook, items, spans, checklist)
    _anchor_reference(workbook, items, rubric)
    _time_log(workbook)

    # Stamped where a person will not overwrite it by accident, and read back on import.
    meta = workbook.create_sheet("_meta")
    meta["A1"], meta["B1"] = "annotator_id", annotator_id
    meta["A2"], meta["B2"] = "n_items", len(items)
    meta["A3"], meta["B3"] = "item_ids", ",".join(i.id for i in items)
    meta.sheet_state = "hidden"

    workbook.save(path)
    return estimate


# ---------------------------------------------------------------------------
# Reading a returned workbook
# ---------------------------------------------------------------------------
def _cell_text(value: object) -> str:
    return "" if value is None else str(value).strip()


def read_workbook(
    path: str,
    annotator_id: Optional[str] = None,
    checklist: Optional[ChecklistRubric] = None,
) -> List[PilotLabel]:
    """Turn a filled-in workbook into `PilotLabel`s for all three arms.

    Arm 3 is recomputed here from the arm 2 ticks rather than read out of the sheet, because the
    sheet holds formulas and a workbook saved by some tools carries no cached values for them.
    Recomputing also means a hand-edited arm 3 cell cannot quietly disagree with its own ticks.

    A blank or NA cell becomes a `None` score, which `arm_results` drops pairwise and counts. It
    is never imputed.
    """
    if not os.path.exists(path):
        raise ExcelPilotError(f"no workbook at {path}")

    checklist = checklist or load_checklist()
    workbook = load_workbook(path, data_only=True)

    if annotator_id is None:
        meta = workbook["_meta"] if "_meta" in workbook.sheetnames else None
        annotator_id = _cell_text(meta["B1"].value) if meta else ""
    if not annotator_id:
        raise ExcelPilotError(
            f"{os.path.basename(path)} does not name an annotator; pass --annotator"
        )

    labels: List[PilotLabel] = []
    minutes = _read_time_log(workbook)

    # -- arm 1 -------------------------------------------------------------
    for item_id, dimension, value in _walk_scored_rows(workbook[SHEET_ANCHORED], score_column=3):
        score: Optional[float]
        if value in ("", NOT_APPLICABLE):
            score = None
        else:
            try:
                score = float(value)
            except ValueError as error:
                raise ExcelPilotError(
                    f"{SHEET_ANCHORED}: {item_id}/{dimension} has {value!r}, "
                    "expected 1-4 or NA"
                ) from error
            if not 1 <= score <= 4:
                raise ExcelPilotError(
                    f"{SHEET_ANCHORED}: {item_id}/{dimension} has {value!r}, outside 1-4"
                )
        labels.append(
            PilotLabel(f"{item_id}::{dimension}", "anchored", annotator_id, score)
        )

    # -- arms 2 and 3 ------------------------------------------------------
    ticked: Dict[Tuple[str, str], List[Tuple[str, bool]]] = {}
    for item_id, label, value in _walk_scored_rows(workbook[SHEET_CHECKLIST], score_column=3):
        dimension, _, entry_id = label.partition("  /  ")
        if value in ("", NOT_APPLICABLE):
            continue
        ticked.setdefault((item_id, dimension.strip()), []).append(
            (entry_id.strip(), value.lower() == "yes")
        )

    for (item_id, dimension), entries in sorted(ticked.items()):
        target = checklist.get(dimension)
        weights = {entry.id: entry.weight for entry in target.items}
        unknown = sorted(e for e, _ in entries if e not in weights)
        if unknown:
            raise ExcelPilotError(
                f"{SHEET_CHECKLIST}: {item_id}/{dimension} has unknown tick box(es) {unknown}; "
                "the workbook was built from a different rubric version"
            )
        possible = sum(weights[e] for e, _ in entries)
        earned = sum(weights[e] for e, yes in entries if yes)
        fraction = earned / possible if possible else 0.0

        unit = f"{item_id}::{dimension}"
        labels.append(PilotLabel(unit, "checklist", annotator_id, round(fraction, 6)))
        labels.append(
            PilotLabel(unit, "rollup", annotator_id, float(_band(fraction, checklist)))
        )

    # Every anchored row produces a label even when blank, so an untouched workbook still yields
    # a full set of None scores. Test for an actual score, or a returned-but-unfilled file would
    # sail through and surface much later as "no item was scored by both annotators".
    if not any(label.score is not None for label in labels):
        raise ExcelPilotError(f"{os.path.basename(path)} has no scores filled in")

    _spread_time_across_units(labels, minutes)
    return labels


def _spread_time_across_units(labels: List[PilotLabel], minutes: Dict[str, Optional[float]]) -> None:
    """Turn each arm's TOTAL minutes into per-unit seconds.

    The time log asks for the whole sheet, because that is the only figure a person can report
    honestly - nobody stopwatches individual rows. `ArmResult.mean_seconds_per_item` expects a
    per-unit number, so the total is divided by the units that arm actually produced. Storing the
    total directly would report a whole sheet's duration as the cost of one row and make the
    tie-break nonsense.

    Arm 3 inherits arm 2's time because it is arm 2's ticks rolled up - it costs no extra effort,
    and charging it a second time would make the cheapest arm look the most expensive.
    """
    source = {"anchored": "anchored", "checklist": "checklist", "rollup": "checklist"}
    counts: Dict[str, int] = {}
    for label in labels:
        counts[label.arm] = counts.get(label.arm, 0) + 1

    for label in labels:
        total = minutes.get(source[label.arm])
        units = counts.get(label.arm, 0)
        label.seconds = (total * 60.0 / units) if total is not None and units else None


def _band(fraction: float, checklist: ChecklistRubric) -> int:
    bands = getattr(checklist, "bands", None) or [
        {"min": 0.90, "score": 4}, {"min": 0.70, "score": 3},
        {"min": 0.40, "score": 2}, {"min": 0.00, "score": 1},
    ]
    for band in bands:
        low = band["min"] if isinstance(band, dict) else band[0]
        score = band["score"] if isinstance(band, dict) else band[1]
        if fraction >= low:
            return int(score)
    return 1


def _walk_scored_rows(sheet: Any, score_column: int) -> Iterator[Tuple[str, str, str]]:
    """Yield ``(item_id, row_label, value)`` for the input rows, tracking the item banners."""
    current = ""
    for row in sheet.iter_rows(min_row=1, values_only=False):
        first = _cell_text(row[0].value)
        if not first:
            continue
        # Banner rows look like "q004  (should answer)  -  <category>".
        if "  (" in first and (") " in first or first.endswith(")")):
            current = first.split("  (")[0].strip()
            continue
        if first in ("QUESTION", "ANSWER being scored", "EVIDENCE available"):
            continue
        if first in ("Item / Dimension",):
            continue
        if not current:
            continue
        yield current, first, _cell_text(row[score_column - 1].value)


def _read_time_log(workbook: Any) -> Dict[str, Optional[float]]:
    minutes: Dict[str, Optional[float]] = {"anchored": None, "checklist": None}
    if SHEET_TIME not in workbook.sheetnames:
        return minutes
    sheet = workbook[SHEET_TIME]
    for row, key in ((2, "anchored"), (3, "checklist")):
        raw = sheet.cell(row=row, column=2).value
        try:
            minutes[key] = float(raw) if raw is not None else None
        except (TypeError, ValueError):
            minutes[key] = None
    return minutes


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: Optional[Sequence[str]] = None) -> int:
    """Build annotator workbooks, or read filled-in ones back.

        python -m eval.judge.pilot_excel build --annotators ann_a ann_b
        python -m eval.judge.pilot_excel read  --files pilot_ann_a.xlsx pilot_ann_b.xlsx
    """
    import argparse
    import json

    from eval.gold_set import DEFAULT_GOLD_PATH, load_gold_set
    from eval.judge.pilot import fixed_pilot_items, pilot_status

    parser = argparse.ArgumentParser(description="Rubric pilot as spreadsheets")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="write one .xlsx per annotator")
    build.add_argument("--gold", default=DEFAULT_GOLD_PATH)
    build.add_argument("--annotators", nargs="+", default=["ann_a", "ann_b"])
    build.add_argument("--out-dir", default=".")

    read = sub.add_parser("read", help="read filled-in workbooks and score the pilot")
    read.add_argument("--files", nargs="+", required=True)
    read.add_argument("--labels-out", default="pilot_labels.json")

    args = parser.parse_args(argv)

    if args.command == "build":
        items = fixed_pilot_items(load_gold_set(args.gold))
        for annotator in args.annotators:
            path = os.path.join(args.out_dir, f"pilot_{annotator}.xlsx")
            estimate = build_workbook(items, path, annotator_id=annotator)
            print(f"wrote {path}")
        print(f"  {estimate.summary()}")
        print("  three arms: two you fill in, one computed from arm 2")
        return 0

    labels: List[PilotLabel] = []
    for path in args.files:
        found = read_workbook(path)
        print(f"{os.path.basename(path)}: {len(found)} scores")
        labels.extend(found)

    with open(args.labels_out, "w", encoding="utf-8") as handle:
        json.dump(
            [
                {"item_id": l.item_id, "arm": l.arm, "annotator_id": l.annotator_id,
                 "score": l.score, "seconds": l.seconds}
                for l in labels
            ],
            handle, indent=2,
        )
    print(f"wrote {args.labels_out}\n")

    status = pilot_status(labels)
    print(status.summary())
    return 0 if status.passed else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
