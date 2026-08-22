"""The ablation grid: one config file, resumable, under budget.

Every research question in section 12 is a slice of this grid. Judge model, panel size and
samples, protocol, reference mode, rationale placement, rubric variant, corpus state, persona -
each is a factor, and a cell is one combination of levels.

THREE PROPERTIES, EACH LEARNED FROM A REAL FAILURE
--------------------------------------------------
1. **Cost is estimated before anything runs.** A 3x5 panel on 200 questions across a full grid
   multiplies fast, and the API quota was already exhausted mid-session once during this project.
   ``estimate_cost`` runs first and the grid refuses to start if the projection exceeds the cap.

2. **The grid is resumable.** Cells write to a ledger as they complete, and a re-run skips what
   is already done. A grid that has to restart from zero after a rate limit is a grid nobody
   finishes.

3. **Every cell carries its own measurement version.** Factors that change what a number MEANS -
   the rubric, the prompt, the judge set, k, temperature, the corpus - flow into the cell's
   measurement version, so L5 refuses to compare cells that are not comparable. Factors that
   only change cost or presentation do not. Getting this wrong would let the report quietly
   compare an anchored-rubric cell against an unanchored one as though they measured the same
   thing.

Pure and network-free: the grid decides what to run and in what order. Actually running a cell
is an injected callable.
"""

from __future__ import annotations

import itertools
import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from eval.judge.schemas import MeasurementVersion, stable_hash

GRID_VERSION = "1.0.0"


class AblationError(ValueError):
    """Raised when a grid cannot be built or run as specified."""


class BudgetRefused(RuntimeError):
    """Raised before spending when the projected cost exceeds the cap."""


# ---------------------------------------------------------------------------
# Factors
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Factor:
    """One axis of the grid.

    ``affects_measurement`` is the field that matters. A factor marked True changes what the
    resulting numbers mean, so cells differing on it get different measurement versions and L5
    will refuse to compare them. Marked False, the factor changes only cost or presentation and
    cells remain comparable.

    Getting this backwards is silent: the grid still runs, the report still renders, and two
    incomparable numbers sit in the same table.
    """

    name: str
    levels: Tuple[str, ...]
    affects_measurement: bool = True
    isolates: str = ""  # which research question this axis answers

    def __post_init__(self) -> None:
        if not self.levels:
            raise AblationError(f"factor {self.name!r} has no levels")
        if len(set(self.levels)) != len(self.levels):
            raise AblationError(f"factor {self.name!r} repeats a level")


# The grid from architecture section 12. Levels are names; the runner maps them onto
# configuration. Kept here so the declared grid is code rather than prose.
DEFAULT_FACTORS: Tuple[Factor, ...] = (
    Factor("judge_model", ("gpt", "claude", "gemini"), True, "model dependence, self-preference"),
    Factor("panel", ("1x1", "1x5", "3x1", "3x5"), True, "diversity vs replication"),
    Factor("protocol", ("pointwise", "pairwise"), True, "protocol reliability gap"),
    Factor("reference_mode", ("evidence", "gold", "both", "none"), True, "RQ3"),
    Factor("rationale", ("before", "after", "none"), True, "chain-of-thought contribution"),
    Factor("rubric", ("anchored", "unanchored", "single_score"), True, "value of anchoring"),
    Factor("corpus_state", ("corrupted", "repaired"), True, "RQ5"),
    Factor("persona", ("blue", "river"), False, "style sensitivity"),
)


# ---------------------------------------------------------------------------
# Cells
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Cell:
    """One combination of factor levels."""

    levels: Tuple[Tuple[str, str], ...]  # sorted (factor, level) pairs

    @property
    def as_dict(self) -> Dict[str, str]:
        return dict(self.levels)

    @property
    def cell_id(self) -> str:
        """Stable identity, so a resumed grid recognises what it already ran."""
        return stable_hash(dict(self.levels), length=12)

    @property
    def label(self) -> str:
        return " · ".join(f"{name}={level}" for name, level in self.levels)

    def level_of(self, factor: str) -> str:
        values = self.as_dict
        if factor not in values:
            raise AblationError(f"cell has no factor {factor!r}")
        return values[factor]

    def to_dict(self) -> Dict[str, object]:
        return {"cell_id": self.cell_id, "levels": self.as_dict, "label": self.label}


def panel_shape(level: str) -> Tuple[int, int]:
    """Parse a panel level such as ``3x5`` into ``(judges, samples)``."""
    try:
        judges, samples = level.lower().split("x")
        return (int(judges), int(samples))
    except (ValueError, AttributeError) as exc:
        raise AblationError(f"panel level {level!r} is not of the form <judges>x<samples>") from exc


# ---------------------------------------------------------------------------
# The grid
# ---------------------------------------------------------------------------
@dataclass
class Grid:
    """A declared set of factors, and the cells they generate."""

    factors: Tuple[Factor, ...]
    fixed: Dict[str, str] = field(default_factory=dict)
    include_only: Optional[Sequence[Dict[str, str]]] = None

    def __post_init__(self) -> None:
        if not self.factors:
            raise AblationError("a grid needs at least one factor")
        names = [f.name for f in self.factors]
        if len(set(names)) != len(names):
            raise AblationError("factor names must be distinct")
        for name, level in self.fixed.items():
            factor = self.factor(name)
            if level not in factor.levels:
                raise AblationError(
                    f"cannot fix {name!r} at {level!r}; levels are {list(factor.levels)}"
                )

    def factor(self, name: str) -> Factor:
        for candidate in self.factors:
            if candidate.name == name:
                return candidate
        raise AblationError(f"no factor named {name!r}")

    @property
    def varying(self) -> List[Factor]:
        return [f for f in self.factors if f.name not in self.fixed]

    def cells(self) -> List[Cell]:
        """Every combination, in a deterministic order.

        Sorted by factor name inside a cell and generated in factor order, so two runs of the
        same config produce the same cells in the same sequence - which is what makes a resumed
        grid line up with the ledger it is resuming from.
        """
        if self.include_only is not None:
            return [self._cell_from(dict(self.fixed, **partial)) for partial in self.include_only]

        axes = []
        for factor in self.factors:
            if factor.name in self.fixed:
                axes.append([(factor.name, self.fixed[factor.name])])
            else:
                axes.append([(factor.name, level) for level in factor.levels])
        return [Cell(levels=tuple(sorted(combo))) for combo in itertools.product(*axes)]

    def _cell_from(self, values: Dict[str, str]) -> Cell:
        missing = [f.name for f in self.factors if f.name not in values]
        if missing:
            raise AblationError(f"cell is missing factor(s) {missing}")
        for name, level in values.items():
            if level not in self.factor(name).levels:
                raise AblationError(f"{name}={level!r} is not a declared level")
        return Cell(levels=tuple(sorted(values.items())))

    def __len__(self) -> int:
        return len(self.cells())

    def measurement_version(
        self,
        cell: Cell,
        base: MeasurementVersion,
        judge_sets: Optional[Dict[str, Tuple[str, ...]]] = None,
    ) -> MeasurementVersion:
        """The measurement version for a cell, derived from the factors that change meaning.

        Only factors marked ``affects_measurement`` contribute. Two cells differing solely on a
        presentation factor keep the same version and stay comparable; two differing on the
        rubric do not, and L5 will refuse to put them in the same comparison.
        """
        meaningful = {
            name: level
            for name, level in cell.levels
            if self.factor(name).affects_measurement
        }

        updates: Dict[str, Any] = {}
        if "panel" in meaningful:
            judges, samples = panel_shape(meaningful["panel"])
            updates["k"] = samples
            if judge_sets and meaningful.get("judge_model") in judge_sets:
                available = judge_sets[meaningful["judge_model"]]
                updates["judge_set"] = tuple(sorted(available[:judges]))
            else:
                # Without a concrete roster, encode the shape so cells still differ correctly.
                updates["judge_set"] = tuple(
                    sorted(f"{meaningful.get('judge_model', 'judge')}-{i}" for i in range(judges))
                )
        elif "judge_model" in meaningful:
            updates["judge_set"] = (meaningful["judge_model"],)

        # Everything else that changes meaning is folded into the rubric and prompt hashes, since
        # those are exactly what a rubric variant or a rationale placement changes.
        rubric_factors = {k: v for k, v in meaningful.items() if k in ("rubric", "corpus_state")}
        prompt_factors = {
            k: v for k, v in meaningful.items()
            if k in ("protocol", "reference_mode", "rationale")
        }
        if rubric_factors:
            updates["rubric_hash"] = stable_hash(
                {"base": base.rubric_hash, **rubric_factors}
            )
        if prompt_factors:
            updates["prompt_hash"] = stable_hash(
                {"base": base.prompt_hash, **prompt_factors}
            )

        return base.model_copy(update=updates)


# ---------------------------------------------------------------------------
# Cost
# ---------------------------------------------------------------------------
@dataclass
class CostModel:
    """What a cell costs, before it is run.

    Deliberately crude and deliberately early. The point is to refuse a grid that would obviously
    exhaust the account, not to bill anyone - real spend comes from the usage each response
    reports, tracked by the panel runner.
    """

    usd_per_judge_call: float = 0.0006
    n_items: int = 60

    def calls_for(self, cell: Cell) -> int:
        values = cell.as_dict
        judges, samples = panel_shape(values.get("panel", "1x1"))
        calls = judges * samples * self.n_items
        # Pairwise runs both presentation orders, which is what makes position bias measurable.
        if values.get("protocol") == "pairwise":
            calls *= 2
        return calls

    def cost_for(self, cell: Cell) -> float:
        return self.calls_for(cell) * self.usd_per_judge_call

    def estimate(self, cells: Sequence[Cell]) -> Dict[str, object]:
        per_cell = [(cell, self.cost_for(cell)) for cell in cells]
        total = sum(cost for _, cost in per_cell)
        most_expensive = max(per_cell, key=lambda pair: pair[1]) if per_cell else None
        return {
            "n_cells": len(cells),
            "total_calls": sum(self.calls_for(cell) for cell in cells),
            "total_usd": round(total, 4),
            "mean_usd_per_cell": round(total / len(cells), 6) if cells else 0.0,
            "most_expensive_cell": most_expensive[0].label if most_expensive else None,
            "most_expensive_usd": round(most_expensive[1], 4) if most_expensive else 0.0,
        }


# ---------------------------------------------------------------------------
# Resumability
# ---------------------------------------------------------------------------
@dataclass
class CellResult:
    """What one completed cell recorded."""

    cell_id: str
    levels: Dict[str, str]
    spent_usd: float
    ok: bool
    detail: Dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return {
            "cell_id": self.cell_id,
            "levels": self.levels,
            "spent_usd": self.spent_usd,
            "ok": self.ok,
            "detail": self.detail,
        }


class GridLedger:
    """Append-only record of completed cells, so a grid can be resumed.

    Failed cells are recorded too, with ``ok=False``. They are NOT skipped on resume - a cell
    that failed on a rate limit should be retried - but they are visible, so a cell failing for a
    real reason does not disappear into a partially complete grid.
    """

    def __init__(self, path: str) -> None:
        self.path = path

    def exists(self) -> bool:
        return os.path.exists(self.path)

    def append(self, result: CellResult) -> None:
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(self.path, "a", encoding="utf-8", newline="") as handle:
            handle.write(
                json.dumps(result.to_dict(), sort_keys=True, ensure_ascii=False,
                           separators=(",", ":"))
            )
            handle.write("\n")

    def load(self) -> List[CellResult]:
        if not self.exists():
            return []
        results: List[CellResult] = []
        with open(self.path, "r", encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    results.append(
                        CellResult(
                            cell_id=row["cell_id"],
                            levels=row["levels"],
                            spent_usd=row["spent_usd"],
                            ok=row["ok"],
                            detail=row.get("detail", {}),
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    raise AblationError(f"{self.path} line {number} is unreadable: {exc}")
        return results

    def completed_ids(self) -> set:
        """Only cells that succeeded. A failed cell is retried on resume."""
        return {r.cell_id for r in self.load() if r.ok}

    def spent(self) -> float:
        return sum(r.spent_usd for r in self.load())


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------
CellRunner = Callable[[Cell, MeasurementVersion], Dict[str, object]]


@dataclass
class GridRun:
    """The outcome of running a grid."""

    completed: List[CellResult] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    failed: List[CellResult] = field(default_factory=list)
    stopped_early: bool = False
    stop_reason: str = ""
    spent_usd: float = 0.0

    def to_dict(self) -> Dict[str, object]:
        return {
            "grid_version": GRID_VERSION,
            "n_completed": len(self.completed),
            "n_skipped": len(self.skipped),
            "n_failed": len(self.failed),
            "stopped_early": self.stopped_early,
            "stop_reason": self.stop_reason,
            "spent_usd": round(self.spent_usd, 6),
            "failed_cells": [r.levels for r in self.failed],
        }


def run_grid(
    grid: Grid,
    base_version: MeasurementVersion,
    runner: CellRunner,
    ledger: GridLedger,
    cost_model: Optional[CostModel] = None,
    budget_usd: Optional[float] = None,
    judge_sets: Optional[Dict[str, Tuple[str, ...]]] = None,
    stop_on_failure: bool = False,
) -> GridRun:
    """Run every cell not already completed, stopping if the budget would be exceeded.

    The budget check happens BEFORE each cell, using the projected cost, and the run stops
    cleanly rather than aborting mid-cell. Everything completed so far stays in the ledger, so
    raising the cap and re-running picks up exactly where it stopped.
    """
    costs = cost_model or CostModel()
    already_done = ledger.completed_ids()
    run = GridRun(spent_usd=ledger.spent())

    for cell in grid.cells():
        if cell.cell_id in already_done:
            run.skipped.append(cell.cell_id)
            continue

        projected = costs.cost_for(cell)
        if budget_usd is not None and run.spent_usd + projected > budget_usd:
            run.stopped_early = True
            run.stop_reason = (
                f"stopping before {cell.label}: ${run.spent_usd:.2f} spent, ${projected:.2f} "
                f"projected for this cell, cap ${budget_usd:.2f}. Everything completed so far "
                "is in the ledger; raise the cap and re-run to continue."
            )
            break

        version = grid.measurement_version(cell, base_version, judge_sets)
        try:
            detail = runner(cell, version)
            spent = float(detail.get("spent_usd", projected))
            result = CellResult(cell.cell_id, cell.as_dict, spent, ok=True, detail=detail)
        except Exception as exc:  # noqa: BLE001 - a failed cell is data, not a crash
            result = CellResult(
                cell.cell_id, cell.as_dict, 0.0, ok=False,
                detail={"error": f"{type(exc).__name__}: {exc}"},
            )

        ledger.append(result)
        run.spent_usd += result.spent_usd
        if result.ok:
            run.completed.append(result)
        else:
            run.failed.append(result)
            if stop_on_failure:
                run.stopped_early = True
                run.stop_reason = f"stopping after {cell.label} failed"
                break

    return run


def check_budget(
    grid: Grid,
    budget_usd: float,
    cost_model: Optional[CostModel] = None,
) -> Dict[str, object]:
    """Refuse a grid whose projected cost exceeds the cap, before anything runs.

    Raises rather than warns. A warning at the top of a long run is read after the money is
    gone.
    """
    costs = cost_model or CostModel()
    estimate = costs.estimate(grid.cells())
    if estimate["total_usd"] > budget_usd:
        raise BudgetRefused(
            f"this grid projects ${estimate['total_usd']:.2f} across {estimate['n_cells']} "
            f"cells ({estimate['total_calls']:,} judge calls), over the ${budget_usd:.2f} cap. "
            "Fix a factor, cut the panel size, or raise the cap deliberately."
        )
    return estimate
