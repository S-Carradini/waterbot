"""Milestone 1 / spec 0.7: how unstable is the existing refusal judge?

THE QUESTION
------------
The paper's motivating result is a 7/12 vs 8/12 swing in refusals on the
out_of_scope_negative set, reported as 8.3 percentage points. On n=12 that is
one item changing its mind. Before anything is built on top of it, run the
current judge R times over the SAME frozen responses and look at the actual
distribution.

WHAT IS HELD FIXED, AND WHY IT MATTERS
--------------------------------------
This judges responses that were already frozen by an earlier full-pipeline run,
rather than regenerating them. The bot's answers, the retrieved context and the
corpus are therefore identical across all R replicates, and the only thing that
varies is the judge call itself (temperature 0, so this is API-level
nondeterminism).

That is a narrower quantity than the original swing, which came from full
pipeline runs and so confounds judge variance with generation variance and with
retrieval drift on an approximate ivfflat index. The consequence must be stated
wherever this number is quoted:

    a small judge-only variance does NOT refute the observed swing.
    It localises it to generation or retrieval, which is a different finding.

The judge is not modified. It is imported from eval/generation_metrics.py and
driven through an injected client (see eval/judge/clients/base.py).

USAGE
-----
Rehearsal, no network, no key, no spend::

    python -m eval.experiments.m1_judge_replication --client fake

The real measurement (~300 calls, roughly $0.18 on gpt-4.1)::

    python -m eval.experiments.m1_judge_replication --client openai --confirm-spend
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import datetime
import json
import os
import subprocess
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_SCRIPT_DIR))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from eval.experiments.load_judge import load_refusal_judge  # noqa: E402
from eval.judge.clients.base import CallRecorder, FakeClient  # noqa: E402
from eval.judge.replication import Verdict, summarise  # noqa: E402

NEGATIVE_CATEGORY = "out_of_scope_negative"
DEFAULT_RUNS = 25
DEFAULT_RESPONSES = os.path.join(_PROJECT_ROOT, "eval", "results", "generation_metrics.csv")
DEFAULT_BENCHMARK = os.path.join(_PROJECT_ROOT, "eval", "benchmark_dataset.json")
DEFAULT_HISTORY = os.path.join(_PROJECT_ROOT, "eval", "results", "eval_history.jsonl")
DEFAULT_RUNS_ROOT = os.path.join(_PROJECT_ROOT, "eval", "results", "runs")

# eval/run_eval_suite.py owns this constant; imported by value rather than by
# import because that module also pulls the pipeline in.
MEASUREMENT_VERSION = 2

# Rehearsal scenarios. Each encodes one of the three qualitative outcomes the
# real run could produce, so the analysis path is exercised against known
# ground truth in every regime before it is trusted with a real number.
SIM_SCENARIOS = {
    # The reviewer's objection in spec 0.7, made literal: everything is stable
    # except one coin-flip item. Summary should report is_single_item_swing.
    "one-item-flip": {"n_always_refuse": 5, "n_never_refuse": 6, "borderline": [0.5]},
    # A perfectly stable judge. Summary should report zero spread.
    "all-stable": {"n_always_refuse": 5, "n_never_refuse": 7, "borderline": []},
    # Genuine diffuse instability spread over many items, which would make the
    # swing real and NOT reducible to one Bernoulli draw.
    "diffuse": {"n_always_refuse": 3, "n_never_refuse": 3, "borderline": [0.5] * 6},
}


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------
def load_frozen_negatives(
    responses_path: str, benchmark_path: str
) -> List[Dict[str, str]]:
    """Load the frozen bot responses for the negative set, and check them.

    Cross-checked against the benchmark so a stale or truncated response file
    cannot quietly shrink the item set - which would change every rate in the
    report while looking like a normal run.
    """
    with open(benchmark_path, "r", encoding="utf-8") as handle:
        benchmark = json.load(handle)
    expected = {
        q["id"]
        for q in benchmark.get("questions", [])
        if q.get("category") == NEGATIVE_CATEGORY and not q.get("excluded_from_scoring")
    }

    with open(responses_path, "r", encoding="utf-8") as handle:
        rows = [r for r in csv.DictReader(handle) if r.get("category") == NEGATIVE_CATEGORY]

    found = {r["id"] for r in rows}
    if found != expected:
        missing = sorted(expected - found)
        extra = sorted(found - expected)
        raise SystemExit(
            "Frozen response set does not match the benchmark negative set.\n"
            f"  missing from responses: {missing}\n"
            f"  not in benchmark:       {extra}\n"
            "Refusing to run: the denominator would be wrong."
        )

    items = [
        {"id": r["id"], "question": r["user_input"], "answer": r["response"]}
        for r in sorted(rows, key=lambda r: r["id"])
    ]
    for item in items:
        if not item["answer"].strip():
            raise SystemExit(f"Frozen response for {item['id']} is empty; refusing to judge it.")
    return items


def latest_corpus_fingerprint(history_path: str) -> Optional[str]:
    """Fingerprint of the most recent suite run, i.e. the one that froze these responses."""
    if not os.path.exists(history_path):
        return None
    fingerprint = None
    with open(history_path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            provenance = record.get("provenance") or {}
            if provenance.get("corpus_fingerprint"):
                fingerprint = provenance["corpus_fingerprint"]
    return fingerprint


def git_sha() -> Optional[str]:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return out.stdout.strip() or None
    except Exception:  # noqa: BLE001 - provenance is best effort
        return None


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------
def build_fake_client(items: Sequence[Dict[str, str]], scenario: str, seed: int) -> FakeClient:
    if scenario not in SIM_SCENARIOS:
        raise SystemExit(f"Unknown scenario {scenario!r}; choose from {sorted(SIM_SCENARIOS)}")
    spec = SIM_SCENARIOS[scenario]
    probabilities: List[float] = (
        [1.0] * spec["n_always_refuse"] + [0.0] * spec["n_never_refuse"] + list(spec["borderline"])
    )
    if len(probabilities) != len(items):
        raise SystemExit(
            f"Scenario {scenario!r} defines {len(probabilities)} items but the frozen "
            f"set has {len(items)}."
        )
    return FakeClient(
        model_id=f"fake-judge-v0/{scenario}",
        item_refusal_prob={item["question"]: p for item, p in zip(items, probabilities)},
        seed=seed,
    )


# ---------------------------------------------------------------------------
# The experiment
# ---------------------------------------------------------------------------
async def run_replicates(
    judge: Any,
    adapter: Any,
    items: Sequence[Dict[str, str]],
    runs: int,
    verbose: bool = True,
) -> Tuple[List[Verdict], List[int], Dict[str, Any]]:
    """Drive the unmodified judge ``runs`` times over ``items``.

    Returns the verdict log, the indices of contaminated replicates, and the
    aggregate call ledger.
    """
    recorder = CallRecorder(adapter)
    verdicts: List[Verdict] = []
    contaminated: List[int] = []
    totals = {"attempts": 0, "errors": 0, "prompt_tokens": 0, "completion_tokens": 0}
    error_samples: List[str] = []
    noncanonical: List[str] = []

    for run_index in range(runs):
        recorder.ledger.reset()
        run_verdicts: List[Verdict] = []
        for item in items:
            before = len(recorder.ledger.contents)
            hallucinated, _usage = await judge(item["question"], item["answer"], recorder)
            # The judge returns only a bool, so the model's actual words are
            # recovered from the ledger. Absent when the call raised and the
            # keyword fallback produced the verdict instead.
            after = recorder.ledger.contents[before:]
            run_verdicts.append(
                Verdict(
                    run_index=run_index,
                    question_id=item["id"],
                    refused=not hallucinated,
                    raw_verdict=after[-1] if after else None,
                )
            )
        ledger = recorder.ledger.snapshot()
        noncanonical.extend(ledger.noncanonical)
        verdicts.extend(run_verdicts)
        for key in totals:
            totals[key] += getattr(ledger, key)
        if ledger.contaminated:
            contaminated.append(run_index)
            error_samples.extend(ledger.error_messages[:2])

        if verbose:
            refused = sum(1 for v in run_verdicts if v.refused)
            flag = "  CONTAMINATED (keyword fallback used)" if ledger.contaminated else ""
            print(f"  run {run_index + 1:2d}/{runs}: {refused}/{len(items)} refused{flag}")

    totals["error_samples"] = error_samples[:10]
    totals["noncanonical_replies"] = len(noncanonical)
    totals["noncanonical_samples"] = noncanonical[:10]
    return verdicts, contaminated, totals


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
def plot_distribution(summary: Any, items: Sequence[Dict[str, str]], path: str, simulated: bool,
                      title_suffix: str) -> None:
    """Distribution of per-run refusal counts, with both intervals and the per-item strip."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    n_items = summary.n_items
    fig, (ax_top, ax_bottom) = plt.subplots(
        2, 1, figsize=(9.5, 8.5), gridspec_kw={"height_ratios": [1.35, 1.0]}
    )

    # --- top: the distribution -------------------------------------------
    counts = summary.run_counts
    bins = [c - 0.5 for c in range(n_items + 2)]
    ax_top.hist(counts, bins=bins, color="#4C72B0", edgecolor="white", zorder=3)
    ax_top.set_xlim(-0.5, n_items + 0.5)
    ax_top.set_xticks(range(n_items + 1))
    ax_top.set_xlabel(f"refusals per run (out of {n_items})")
    ax_top.set_ylabel(f"runs (of {summary.n_replicates})")
    ax_top.grid(axis="y", alpha=0.25, zorder=0)

    # Intervals live on the rate scale; draw them in count units so they can be
    # read against the histogram directly.
    wilson = (summary.wilson_lo * n_items, summary.wilson_hi * n_items)
    boot = (summary.boot_lo * n_items, summary.boot_hi * n_items)
    y_max = ax_top.get_ylim()[1]
    ax_top.hlines(y_max * 0.90, wilson[0], wilson[1], color="#C44E52", lw=3, zorder=4,
                  label=f"Wilson 95% (iid): [{summary.wilson_lo:.3f}, {summary.wilson_hi:.3f}]")
    ax_top.hlines(y_max * 0.78, boot[0], boot[1], color="#55A868", lw=3, zorder=4,
                  label=f"clustered bootstrap 95%: [{summary.boot_lo:.3f}, {summary.boot_hi:.3f}]")
    ax_top.axvline(summary.count_mean, color="#333333", ls="--", lw=1.2, zorder=4,
                   label=f"mean = {summary.count_mean:.2f}")
    ax_top.legend(loc="upper left", fontsize=8, framealpha=0.9)
    ax_top.set_title(
        f"Refusal count over {summary.n_replicates} replicates of the existing judge"
        f"{title_suffix}\n"
        f"observed range {summary.count_min}-{summary.count_max} of {n_items} "
        f"({summary.swing_points:.1f} points), SD = {summary.count_sd:.2f}",
        fontsize=11,
    )

    # --- bottom: which items are unstable --------------------------------
    ids = [item["id"] for item in items]
    rates = [summary.per_item_rates.get(qid, 0.0) for qid in ids]
    colours = ["#DD8452" if 0.0 < r < 1.0 else "#B0B0B0" for r in rates]
    ax_bottom.barh(range(len(ids)), rates, color=colours, zorder=3)
    ax_bottom.set_yticks(range(len(ids)))
    ax_bottom.set_yticklabels(ids, fontsize=8)
    ax_bottom.invert_yaxis()
    ax_bottom.set_xlim(0, 1)
    ax_bottom.set_xlabel("fraction of replicates judged REFUSED")
    ax_bottom.grid(axis="x", alpha=0.25, zorder=0)
    unstable = summary.unstable_items
    ax_bottom.set_title(
        f"Per-item stability - {len(unstable)} of {n_items} items ever changed verdict"
        + (f" ({', '.join(unstable)})" if unstable else ""),
        fontsize=10,
    )

    if simulated:
        fig.text(
            0.5, 0.5, "SIMULATED\nno API calls", fontsize=54, color="#C44E52",
            alpha=0.16, ha="center", va="center", rotation=28, weight="bold", zorder=10,
        )

    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def write_report(path: str, summary: Any, manifest: Dict[str, Any],
                 items: Sequence[Dict[str, str]], simulated: bool) -> None:
    lines: List[str] = []
    add = lines.append

    add("# M1: judge replication (spec 0.7)")
    add("")
    if simulated:
        add("> **SIMULATED RUN - NOT A MEASUREMENT.**")
        add("> Verdicts came from `FakeClient`, not from a model. No API calls were made.")
        add("> This artifact exists to prove the measurement path works end to end;")
        add("> the numbers below describe the simulator, not the judge.")
        add("")

    add(f"- run id: `{manifest['run_id']}`")
    add(f"- corpus fingerprint: `{manifest['corpus_fingerprint']}`")
    add(f"- measurement version: {manifest['measurement_version']}")
    add(f"- judge source sha256: `{manifest['judge_source_sha256']}`")
    add(f"- judge model: `{manifest['model_id']}`  (temperature {manifest['temperature']})")
    add(f"- replicates: {summary.n_replicates}, items: {summary.n_items}")
    add(f"- git sha: `{manifest.get('git_sha')}`")
    add("")

    add("## Result")
    add("")
    mean_lo, mean_hi = summary.count_mean_interval
    add(f"- refusal count per run: min {summary.count_min}, max {summary.count_max}, "
        f"mean {summary.count_mean:.2f}, SD {summary.count_sd:.2f}")
    add(f"- mean count, generalising to other questions: 95% [{mean_lo:.2f}, {mean_hi:.2f}] "
        f"of {summary.n_items} (the clustered interval on the count scale - it is wide "
        "because it asks about the next 12 questions, not about the next 25 runs of these 12)")
    add(f"- observed spread: **{summary.swing_points:.1f} percentage points** "
        f"(the motivating result quotes 8.3)")
    add(f"- pooled refusal rate: {summary.pooled_refusals}/{summary.pooled_trials} "
        f"= {summary.pooled_rate:.4f}")
    add(f"- **Wilson 95%**: [{summary.wilson_lo:.4f}, {summary.wilson_hi:.4f}]")
    add(f"- **clustered bootstrap 95%** (B={summary.n_boot}, seed {summary.boot_seed}): "
        f"[{summary.boot_lo:.4f}, {summary.boot_hi:.4f}]")
    add("")
    add("The Wilson interval treats all "
        f"{summary.pooled_trials} verdicts as independent trials. They are not: they are "
        f"{summary.n_items} items measured {summary.n_replicates} times each, and items "
        "differ far more than replicates of the same item do. Wilson is therefore "
        "anti-conservative here and is reported only because spec 0.7 names it. The "
        "clustered bootstrap, which resamples items, is the interval to quote for any "
        "claim about questions in general.")
    add("")

    add("## Is the swing one item?")
    add("")
    unstable = summary.unstable_items
    add(f"{len(unstable)} of {summary.n_items} items ever changed verdict across replicates.")
    add("")
    if summary.is_single_item_swing:
        add(f"**Yes.** All run-to-run movement comes from `{unstable[0]}`. The spread is one "
            "Bernoulli draw, and the motivating result should be reframed rather than quoted "
            "as evidence of judge instability.")
    elif not unstable:
        add("**No - there is no swing at all.** Every item decided the same way in every "
            "replicate. Judge-only variance at temperature 0 is zero on this set, which "
            "means the originally observed swing came from generation or retrieval, not "
            "from the judge.")
    else:
        add(f"**No.** Instability is spread across {len(unstable)} items "
            f"({', '.join(unstable)}), so the variance is a real property of the judge on "
            "this set rather than a single coin flip.")
    add("")

    add("Per-item intervals below are Wilson 95%, computed over that item's replicates. They "
        "are **marginal, not simultaneous**: across 12 items roughly one is expected to miss "
        "its true rate by chance, so they support the qualitative reading and must not be "
        "used to single out an item post hoc without a multiplicity adjustment.")
    add("")
    add("| item | question | refusal rate | Wilson 95% |")
    add("|---|---|---|---|")
    intervals = summary.per_item_intervals
    for item in items:
        rate = summary.per_item_rates.get(item["id"], 0.0)
        lo, hi = intervals.get(item["id"], (0.0, 1.0))
        unstable = 0.0 < rate < 1.0
        shown = f"**{rate:.2f}**" if unstable else f"{rate:.2f}"
        question = item["question"].replace("|", "/")[:60]
        add(f"| `{item['id']}` | {question} | {shown} | [{lo:.2f}, {hi:.2f}] |")
    add("")

    add("## Measurement hygiene")
    add("")
    add(f"- replicates attempted: {summary.attempted_replicates}, "
        f"excluded for provider errors: {len(summary.excluded_runs)} "
        f"({summary.excluded_fraction:.1%})")
    add(f"- non-canonical judge replies: {summary.noncanonical_replies} "
        f"of {summary.pooled_trials} ({summary.noncanonical_rate:.2%})")
    add("")
    add("The judge decides by testing whether the reply contains the string `ANSWERED`, so "
        "every reply that is neither exactly `REFUSED` nor exactly `ANSWERED` - a hedge, a "
        "truncation at `max_tokens=10`, an empty completion - is counted as a refusal. A "
        "non-zero rate above means part of the headline refusal rate is string parsing rather "
        "than judgement, and that portion would not move under any amount of ensembling.")
    add("")

    if summary.excluded_runs:
        add("## Excluded replicates")
        add("")
        add(f"Runs {summary.excluded_runs} recorded provider errors. The judge catches those "
            "silently and falls back to a deterministic keyword check, so those replicates "
            "mix two different measuring instruments and are dropped whole rather than "
            "partially counted.")
        add("")

    add("## Scope of this number")
    add("")
    add("Responses were frozen by an earlier pipeline run and held identical across all "
        "replicates, so this isolates judge-call variance at temperature 0. It does not "
        "measure generation or retrieval variance. A small number here does not refute the "
        "original 7/12 vs 8/12 observation; it localises it to the parts of the pipeline "
        "this experiment deliberately held still.")
    add("")

    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--client", choices=["fake", "openai"], default="fake",
                        help="fake makes no network calls and produces a SIMULATED artifact")
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS,
                        help=f"replicates (spec 0.7 asks for 20-30; default {DEFAULT_RUNS})")
    parser.add_argument("--responses", default=DEFAULT_RESPONSES)
    parser.add_argument("--benchmark", default=DEFAULT_BENCHMARK)
    parser.add_argument("--runs-root", default=DEFAULT_RUNS_ROOT)
    parser.add_argument("--fingerprint", default=None,
                        help="corpus fingerprint; defaults to the latest in eval_history.jsonl")
    parser.add_argument("--model", default=None, help="judge model id (openai client only)")
    parser.add_argument("--scenario", default="one-item-flip", choices=sorted(SIM_SCENARIOS),
                        help="fake client only: which instability regime to simulate")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--boot", type=int, default=2000)
    parser.add_argument("--confirm-spend", action="store_true",
                        help="required for --client openai; acknowledges real API spend")
    args = parser.parse_args(argv)

    if args.runs < 2:
        raise SystemExit("--runs must be at least 2; a distribution needs more than one point.")

    items = load_frozen_negatives(args.responses, args.benchmark)
    simulated = args.client == "fake"

    fingerprint = args.fingerprint or latest_corpus_fingerprint(DEFAULT_HISTORY)
    if not fingerprint:
        # Invariant 1: no result is written without a corpus fingerprint.
        raise SystemExit(
            "No corpus fingerprint available and none passed with --fingerprint. "
            "Refusing to write a result that cannot be tied to a corpus."
        )

    judge, judge_sha = load_refusal_judge()

    if simulated:
        adapter: Any = build_fake_client(items, args.scenario, args.seed)
        model_id = adapter.model_id
    else:
        if not args.confirm_spend:
            estimated = args.runs * len(items)
            raise SystemExit(
                f"--client openai would make {estimated} real API calls. "
                "Re-run with --confirm-spend to authorise the spend."
            )
        from eval.judge.clients.openai_client import DEFAULT_JUDGE_MODEL, OpenAIJudgeClient

        adapter = OpenAIJudgeClient(model_id=args.model or DEFAULT_JUDGE_MODEL)
        model_id = adapter.model_id

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"m1-judge-replication-{stamp}-{'sim' if simulated else 'live'}"
    out_dir = os.path.join(args.runs_root, fingerprint, run_id)
    if os.path.exists(out_dir):
        # Invariant 2: nothing under eval/results/runs/ is modified in place.
        raise SystemExit(f"Run directory already exists and runs are immutable: {out_dir}")
    os.makedirs(out_dir)

    print(f"M1 judge replication: {args.runs} runs x {len(items)} items "
          f"({'SIMULATED' if simulated else 'LIVE'}, model={model_id})")
    verdicts, contaminated, totals = asyncio.run(
        run_replicates(judge, adapter, items, args.runs)
    )

    summary = summarise(
        verdicts,
        [item["id"] for item in items],
        excluded_runs=contaminated,
        n_boot=args.boot,
        seed=args.seed,
        noncanonical_replies=totals["noncanonical_replies"],
    )

    manifest: Dict[str, Any] = {
        "run_id": run_id,
        "experiment": "m1_judge_replication",
        "spec_section": "0.7",
        "simulated": simulated,
        "corpus_fingerprint": fingerprint,
        "measurement_version": MEASUREMENT_VERSION,
        "dataset_version": os.path.basename(args.benchmark),
        "model_id": model_id,
        "temperature": 0.0,
        "judge_source_sha256": judge_sha,
        "judge_source_path": "eval/generation_metrics.py",
        "responses_path": os.path.relpath(args.responses, _PROJECT_ROOT).replace("\\", "/"),
        "n_items": len(items),
        "n_replicates": args.runs,
        "seed": args.seed,
        "bootstrap_resamples": args.boot,
        "scenario": args.scenario if simulated else None,
        "git_sha": git_sha(),
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "call_ledger": totals,
        "contaminated_runs": contaminated,
    }

    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
    with open(os.path.join(out_dir, "verdicts.jsonl"), "w", encoding="utf-8") as handle:
        for verdict in verdicts:
            handle.write(json.dumps(verdict.to_dict(), sort_keys=True) + "\n")
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as handle:
        json.dump(summary.to_dict(), handle, indent=2, sort_keys=True)

    suffix = f"  [SIMULATED: {args.scenario}]" if simulated else ""
    plot_distribution(summary, items, os.path.join(out_dir, "distribution.png"), simulated, suffix)
    write_report(os.path.join(out_dir, "report.md"), summary, manifest, items, simulated)

    print()
    print(f"  refusals per run: {summary.count_min}-{summary.count_max} of {summary.n_items} "
          f"(mean {summary.count_mean:.2f}, SD {summary.count_sd:.2f})")
    print(f"  spread: {summary.swing_points:.1f} points")
    print(f"  Wilson 95%     : [{summary.wilson_lo:.4f}, {summary.wilson_hi:.4f}]  (iid, too narrow)")
    print(f"  clustered 95%  : [{summary.boot_lo:.4f}, {summary.boot_hi:.4f}]")
    print(f"  unstable items : {len(summary.unstable_items)} of {summary.n_items} "
          f"{summary.unstable_items}")
    if summary.noncanonical_replies:
        print(f"  NON-CANONICAL  : {summary.noncanonical_replies} replies "
              f"({summary.noncanonical_rate:.2%}) were neither REFUSED nor ANSWERED "
              "and were counted as refusals")
    if contaminated:
        print(f"  EXCLUDED runs  : {contaminated} ({summary.excluded_fraction:.1%}, "
              "provider errors -> keyword fallback)")
    print(f"\n  artifacts: {os.path.relpath(out_dir, _PROJECT_ROOT)}")
    if simulated:
        print("\n  SIMULATED - no API calls were made. Not a measurement of the judge.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
