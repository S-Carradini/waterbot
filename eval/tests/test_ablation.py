"""Tests for the ablation grid.

Milestone 12's acceptance check is one sentence: the grid runs from one config file, is
resumable, and stays under budget. All three are tested here, along with the quiet failure that
would matter most - a factor changing what a number means without changing its measurement
version, which would let the report compare two incomparable cells in the same table.

Network-free: running a cell is an injected callable.
"""

from __future__ import annotations

import pytest

from eval.judge.ablation import (
    DEFAULT_FACTORS,
    AblationError,
    BudgetRefused,
    Cell,
    CellResult,
    CostModel,
    Factor,
    Grid,
    GridLedger,
    check_budget,
    panel_shape,
    run_grid,
)
from eval.judge.schemas import MeasurementVersion


def a_version(**kw) -> MeasurementVersion:
    payload = {
        "corpus_fingerprint": "08527fbdf140f811",
        "rubric_hash": "r" * 16,
        "prompt_hash": "p" * 16,
        "judge_set": ("gpt-x",),
        "aggregation_version": "1.0.0",
        "k": 5,
        "temperature": 0.3,
    }
    payload.update(kw)
    return MeasurementVersion(**payload)


def small_grid() -> Grid:
    return Grid(
        factors=(
            Factor("panel", ("1x1", "3x5"), True),
            Factor("rubric", ("anchored", "unanchored"), True),
            Factor("persona", ("blue", "river"), False),
        )
    )


def fixed_at(**levels) -> Grid:
    """The full declared grid with everything pinned except what is named."""
    fixed = {f.name: f.levels[0] for f in DEFAULT_FACTORS if f.name not in levels}
    return Grid(DEFAULT_FACTORS, fixed=fixed)


# ---------------------------------------------------------------------------
# Factors and cells
# ---------------------------------------------------------------------------
def test_a_factor_needs_levels():
    with pytest.raises(AblationError, match="no levels"):
        Factor("empty", ())


def test_a_factor_cannot_repeat_a_level():
    with pytest.raises(AblationError, match="repeats a level"):
        Factor("dupes", ("a", "a"))


def test_the_grid_is_the_product_of_its_factors():
    assert len(small_grid()) == 2 * 2 * 2


def test_cells_are_generated_deterministically():
    """A resumed grid has to line up with the ledger it is resuming from."""
    first = [c.cell_id for c in small_grid().cells()]
    second = [c.cell_id for c in small_grid().cells()]
    assert first == second


def test_a_cell_id_does_not_depend_on_factor_ordering():
    a = Cell(levels=tuple(sorted({"panel": "1x1", "rubric": "anchored"}.items())))
    b = Cell(levels=tuple(sorted({"rubric": "anchored", "panel": "1x1"}.items())))
    assert a.cell_id == b.cell_id


def test_different_cells_have_different_ids():
    ids = {c.cell_id for c in small_grid().cells()}
    assert len(ids) == len(small_grid())


def test_fixing_a_factor_collapses_that_axis():
    grid = Grid(small_grid().factors, fixed={"persona": "blue"})
    assert len(grid) == 4
    assert all(c.level_of("persona") == "blue" for c in grid.cells())


def test_fixing_a_factor_at_an_undeclared_level_is_refused():
    with pytest.raises(AblationError, match="cannot fix"):
        Grid(small_grid().factors, fixed={"persona": "purple"})


def test_an_explicit_cell_list_can_replace_the_full_product():
    grid = Grid(
        small_grid().factors,
        include_only=[
            {"panel": "1x1", "rubric": "anchored", "persona": "blue"},
            {"panel": "3x5", "rubric": "anchored", "persona": "blue"},
        ],
    )
    assert len(grid) == 2


def test_an_incomplete_explicit_cell_is_refused():
    grid = Grid(small_grid().factors, include_only=[{"panel": "1x1"}])
    with pytest.raises(AblationError, match="missing factor"):
        grid.cells()


def test_duplicate_factor_names_are_refused():
    with pytest.raises(AblationError, match="distinct"):
        Grid((Factor("a", ("x",)), Factor("a", ("y",))))


@pytest.mark.parametrize("level,expected", [("1x1", (1, 1)), ("3x5", (3, 5)), ("2X4", (2, 4))])
def test_panel_shapes_parse(level, expected):
    assert panel_shape(level) == expected


def test_a_malformed_panel_level_is_refused():
    with pytest.raises(AblationError, match="not of the form"):
        panel_shape("three-by-five")


# ---------------------------------------------------------------------------
# Measurement versions: the quiet failure
# ---------------------------------------------------------------------------
def test_a_factor_that_changes_meaning_changes_the_measurement_version():
    grid = small_grid()
    anchored, unanchored = [
        c for c in grid.cells()
        if c.level_of("panel") == "1x1" and c.level_of("persona") == "blue"
    ]
    base = a_version()
    assert (
        grid.measurement_version(anchored, base).version_id
        != grid.measurement_version(unanchored, base).version_id
    )


def test_a_presentation_factor_leaves_cells_comparable():
    """Persona changes the answer's style, not what the score means."""
    grid = fixed_at(persona=None)
    blue, river = grid.cells()
    base = a_version()
    assert (
        grid.measurement_version(blue, base).version_id
        == grid.measurement_version(river, base).version_id
    )


def test_panel_size_flows_into_k():
    grid = fixed_at(panel=None)
    base = a_version()
    for cell in grid.cells():
        judges, samples = panel_shape(cell.level_of("panel"))
        version = grid.measurement_version(cell, base)
        assert version.k == samples
        assert len(version.judge_set) == judges


def test_a_judge_roster_is_used_when_supplied():
    grid = fixed_at(panel=None)
    rosters = {"gpt": ("gpt-a", "gpt-b", "gpt-c")}
    cell = next(c for c in grid.cells() if c.level_of("panel") == "3x5")
    version = grid.measurement_version(cell, a_version(), judge_sets=rosters)
    assert set(version.judge_set) <= set(rosters["gpt"])
    assert len(version.judge_set) == 3


def test_the_protocol_changes_the_prompt_hash():
    grid = fixed_at(protocol=None)
    base = a_version()
    hashes = {grid.measurement_version(c, base).prompt_hash for c in grid.cells()}
    assert len(hashes) == 2


def test_the_corpus_state_changes_the_rubric_hash():
    """RQ5 compares corrupted against repaired; they must not pool."""
    grid = fixed_at(corpus_state=None)
    base = a_version()
    versions = [grid.measurement_version(c, base) for c in grid.cells()]
    assert versions[0].version_id != versions[1].version_id


def test_every_declared_factor_states_whether_it_affects_measurement():
    for factor in DEFAULT_FACTORS:
        assert isinstance(factor.affects_measurement, bool)
        assert factor.isolates, f"{factor.name} does not say which question it answers"


# ---------------------------------------------------------------------------
# Cost
# ---------------------------------------------------------------------------
def test_a_bigger_panel_costs_more():
    costs = CostModel()
    small = Cell(tuple(sorted({"panel": "1x1", "protocol": "pointwise"}.items())))
    large = Cell(tuple(sorted({"panel": "3x5", "protocol": "pointwise"}.items())))
    assert costs.cost_for(large) == pytest.approx(15 * costs.cost_for(small))


def test_pairwise_doubles_the_calls():
    """Both presentation orders, which is what makes position bias measurable."""
    costs = CostModel()
    pointwise = Cell(tuple(sorted({"panel": "1x1", "protocol": "pointwise"}.items())))
    pairwise = Cell(tuple(sorted({"panel": "1x1", "protocol": "pairwise"}.items())))
    assert costs.calls_for(pairwise) == 2 * costs.calls_for(pointwise)


def test_the_estimate_names_the_most_expensive_cell():
    estimate = CostModel().estimate(small_grid().cells())
    assert "3x5" in estimate["most_expensive_cell"]
    assert estimate["n_cells"] == 8


def test_an_over_budget_grid_is_refused_before_anything_runs():
    """A warning at the top of a long run is read after the money is gone."""
    with pytest.raises(BudgetRefused, match="over the"):
        check_budget(Grid(DEFAULT_FACTORS), budget_usd=10.0)


def test_an_affordable_grid_returns_its_estimate():
    estimate = check_budget(small_grid(), budget_usd=1000.0)
    assert estimate["total_usd"] > 0


def test_the_full_declared_grid_is_not_affordable_by_default():
    """A real finding about the design, not a test of arithmetic.

    The grid in architecture section 12 is 3,456 cells and nearly two million judge calls. It has
    to be sliced per research question, which is what the fixed-factor mechanism is for.
    """
    estimate = CostModel().estimate(Grid(DEFAULT_FACTORS).cells())
    assert estimate["n_cells"] > 3000
    assert estimate["total_usd"] > 500


def test_a_single_research_question_slice_is_affordable():
    rq2 = fixed_at(panel=None, judge_model=None)
    estimate = CostModel().estimate(rq2.cells())
    assert estimate["total_usd"] < 20


# ---------------------------------------------------------------------------
# The ledger and resumability
# ---------------------------------------------------------------------------
def a_result(cell_id="abc", ok=True, spent=1.0):
    return CellResult(cell_id=cell_id, levels={"panel": "1x1"}, spent_usd=spent, ok=ok)


def test_the_ledger_round_trips(tmp_path):
    ledger = GridLedger(str(tmp_path / "grid.jsonl"))
    ledger.append(a_result())
    assert ledger.load()[0].cell_id == "abc"


def test_completed_ids_exclude_failures(tmp_path):
    """A cell that failed on a rate limit should be retried, not skipped forever."""
    ledger = GridLedger(str(tmp_path / "grid.jsonl"))
    ledger.append(a_result("good", ok=True))
    ledger.append(a_result("bad", ok=False))
    assert ledger.completed_ids() == {"good"}


def test_the_ledger_totals_spend(tmp_path):
    ledger = GridLedger(str(tmp_path / "grid.jsonl"))
    ledger.append(a_result("a", spent=1.5))
    ledger.append(a_result("b", spent=2.5))
    assert ledger.spent() == pytest.approx(4.0)


def test_a_corrupt_ledger_names_its_line(tmp_path):
    path = tmp_path / "grid.jsonl"
    path.write_text("not json\n", encoding="utf-8")
    with pytest.raises(AblationError, match="line 1"):
        GridLedger(str(path)).load()


def test_an_absent_ledger_is_empty(tmp_path):
    assert GridLedger(str(tmp_path / "nothing.jsonl")).load() == []


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------
def test_every_cell_runs_once(tmp_path):
    seen = []
    run = run_grid(
        small_grid(), a_version(),
        runner=lambda cell, version: seen.append(cell.cell_id) or {"spent_usd": 0.1},
        ledger=GridLedger(str(tmp_path / "grid.jsonl")),
    )
    assert len(run.completed) == 8
    assert len(set(seen)) == 8


def test_a_resumed_grid_skips_what_is_done(tmp_path):
    """Milestone 12's acceptance check: a grid that restarts from zero is one nobody finishes."""
    path = str(tmp_path / "grid.jsonl")
    grid, version = small_grid(), a_version()

    first_calls = []
    run_grid(grid, version,
             runner=lambda c, v: first_calls.append(c.cell_id) or {"spent_usd": 0.1},
             ledger=GridLedger(path), budget_usd=0.35)

    second_calls = []
    second = run_grid(grid, version,
                      runner=lambda c, v: second_calls.append(c.cell_id) or {"spent_usd": 0.1},
                      ledger=GridLedger(path))

    assert set(first_calls) & set(second_calls) == set()
    assert len(first_calls) + len(second_calls) == 8
    assert len(second.skipped) == len(first_calls)


def test_the_run_stops_before_exceeding_the_budget(tmp_path):
    run = run_grid(
        small_grid(), a_version(),
        runner=lambda cell, version: {"spent_usd": 1.0},
        ledger=GridLedger(str(tmp_path / "grid.jsonl")),
        budget_usd=2.5,
        cost_model=CostModel(usd_per_judge_call=1.0, n_items=1),
    )
    assert run.stopped_early is True
    assert "raise the cap and re-run" in run.stop_reason
    assert len(run.completed) < 8


def test_work_done_before_the_budget_stop_is_kept(tmp_path):
    path = str(tmp_path / "grid.jsonl")
    run_grid(
        small_grid(), a_version(),
        runner=lambda cell, version: {"spent_usd": 1.0},
        ledger=GridLedger(path), budget_usd=2.5,
        cost_model=CostModel(usd_per_judge_call=1.0, n_items=1),
    )
    assert len(GridLedger(path).completed_ids()) > 0


def test_a_failing_cell_is_recorded_rather_than_crashing_the_grid(tmp_path):
    def runner(cell, version):
        if cell.level_of("panel") == "3x5":
            raise RuntimeError("rate limited")
        return {"spent_usd": 0.1}

    run = run_grid(small_grid(), a_version(), runner=runner,
                   ledger=GridLedger(str(tmp_path / "grid.jsonl")))
    assert len(run.failed) == 4
    assert len(run.completed) == 4
    assert "rate limited" in run.failed[0].detail["error"]


def test_a_failing_cell_can_stop_the_grid_when_asked(tmp_path):
    run = run_grid(
        small_grid(), a_version(),
        runner=lambda cell, version: (_ for _ in ()).throw(RuntimeError("boom")),
        ledger=GridLedger(str(tmp_path / "grid.jsonl")),
        stop_on_failure=True,
    )
    assert run.stopped_early is True
    assert len(run.failed) == 1


def test_the_runner_receives_the_cell_measurement_version(tmp_path):
    versions = {}

    def runner(cell, version):
        versions[cell.cell_id] = version
        return {"spent_usd": 0.1}

    grid = small_grid()
    run_grid(grid, a_version(), runner=runner, ledger=GridLedger(str(tmp_path / "g.jsonl")))
    assert len({v.version_id for v in versions.values()}) == 4  # persona does not split


def test_the_run_summary_serialises(tmp_path):
    run = run_grid(small_grid(), a_version(),
                   runner=lambda c, v: {"spent_usd": 0.1},
                   ledger=GridLedger(str(tmp_path / "g.jsonl")))
    payload = run.to_dict()
    assert payload["n_completed"] == 8 and payload["n_failed"] == 0
