"""Command line entry point for the judge pipeline.

`CLAUDE.md` has referenced `python -m eval.judge.cli` since the project began; until 2026-09-05
the file did not exist, which is why `TECHNICAL_WORKFLOWS.md` told readers to drive the modules
directly. This is that entry point.

Four subcommands, in the order they must run:

    freeze     L1  ask a system the gold-set questions once and store the answers immutably
    panel      L2  run the judge panel over a frozen response set
    aggregate  L3  collapse panel votes into scores with intervals
    report     L5  publish, with the measurement version and the limitations attached

Every subcommand that can spend money refuses to do so without `--confirm-spend`, and every
one of them takes a budget cap that the runner enforces per call rather than checking at the end.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional, Sequence

DEFAULT_CONFIG = os.path.join("configs", "panel.yaml")
POINTWISE_V1 = "pointwise_v1"
DEFAULT_RUBRIC = os.path.join("eval", "judge", "rubric.yaml")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
def load_config(path: str) -> Dict[str, Any]:
    import yaml

    if not os.path.exists(path):
        raise SystemExit(f"no panel config at {path}")
    with open(path, encoding="utf-8") as fh:
        config = yaml.safe_load(fh) or {}
    judges = [j["model_id"] for j in config.get("panel", {}).get("judges", [])]
    if not judges:
        raise SystemExit(f"{path} defines no judges")
    if len(set(judges)) != len(judges):
        raise SystemExit(f"{path} repeats a judge model id: {judges}")
    return config


def describe_panel(config: Dict[str, Any]) -> str:
    panel = config["panel"]
    judges = [j["model_id"] for j in panel["judges"]]
    lines = [
        "PANEL AS CONFIGURED",
        f"  judges      : {len(judges)}",
    ]
    for judge in panel["judges"]:
        model_id = judge["model_id"]
        provider = str(judge.get("provider", "openai"))
        # An OpenAI snapshot ends in -YYYY-MM-DD. A Hugging Face repo id is stable but can be
        # updated in place, so it counts as pinned only once its revision is in the manifest.
        parts = model_id.rsplit("-", 3)
        dated = len(parts) == 4 and all(p.isdigit() for p in parts[1:])
        mark = ("PINNED SNAPSHOT" if dated
                else "REPO ID (pin revision in manifest)" if provider != "openai"
                else "*** ALIAS ***")
        lines.append(f"      {model_id:32} {provider:12} {mark}")

    providers = {str(j.get("provider", "openai")).lower() for j in panel["judges"]}
    lines += [
        f"  vendors     : {len(providers)}  ({', '.join(sorted(providers))})",
        f"  samples (k) : {panel['samples']}",
        f"  temperature : {panel['temperature']}",
        f"  rubric      : {config.get('rubric', {}).get('path', DEFAULT_RUBRIC)}",
        f"  prompt      : {config.get('prompt', {}).get('template', POINTWISE_V1)}",
        f"  budget cap  : ${config['budget']['cap_usd']:.2f} "
        f"({'rates VERIFIED' if config['budget'].get('rates_verified') else 'rates ASSUMED, not verified'})",
        "",
    ]
    if len(providers) == 1:
        lines += [
            "  LIMITATION: every judge is from ONE company. Error decorrelation across model",
            "  families is the mechanism a panel relies on, and this panel cannot provide it.",
        ]
    else:
        lines += [
            f"  Judges span {len(providers)} vendors, so panel agreement carries error-decorrelation",
            "  weight that a single-vendor panel does not.",
        ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# show-panel
# ---------------------------------------------------------------------------
def cmd_show_panel(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    print(describe_panel(config))
    from eval.judge.rubric import load_rubric

    rubric = load_rubric(config.get("rubric", {}).get("path") or DEFAULT_RUBRIC)
    print()
    print(f"  rubric      : v{rubric.version}")
    print(f"  status      : {rubric.status}")
    print(f"  in force    : {rubric.is_in_force} "
          f"(piloted={rubric.is_piloted}, selected={rubric.selected})")
    return 0


# ---------------------------------------------------------------------------
# freeze
# ---------------------------------------------------------------------------
CORPORA = {
    # name -> the .env key holding its connection string
    "waterbot": "EVAL_DATABASE_URL",
    "realwater": "REALWATER_DATABASE_URL",
}


def cmd_freeze(args: argparse.Namespace) -> int:
    """L1: ask the system the gold-set questions once, against one corpus, and store it."""
    import time

    from eval.gold_set import load_gold_set
    from eval.judge.corpus_retriever import (OpenAIEmbedder, PgVectorExactRetriever,
                                             corpus_fingerprint_for)
    from eval.judge.freeze import BenchmarkItem, freeze_run, make_run_id
    from eval.judge.generator import WaterBotGenerator
    from eval.judge.gold import benchmark_items
    from eval.judge.realwater_generator import RealWaterGenerator
    from eval.judge.schemas import MeasurementVersion
    from eval.judge.store import ResponseStore

    env_key = CORPORA.get(args.corpus)
    if env_key is None:
        raise SystemExit(f"unknown corpus {args.corpus!r}; expected one of {sorted(CORPORA)}")
    db_url = os.environ.get(env_key)
    if not db_url:
        raise SystemExit(f"{env_key} is not set in .env, so corpus {args.corpus!r} is unreachable")

    if args.questions:
        # A question set with no gold answers. The qualitative round asks whether the JUDGE's
        # reasoning is intelligible, which needs no reference answer - so requiring one would
        # mean inventing gold text nobody verified, and this project has already been bitten by
        # unverified gold answers once.
        items = _items_from_workbook(args.questions, category=args.category)
        dataset_version = os.path.basename(args.questions)
    else:
        gold = load_gold_set(args.gold)
        items = list(benchmark_items(gold))
        dataset_version = os.path.basename(args.gold)
    print(f"corpus     : {args.corpus}  ({db_url.split('@')[-1].split('/')[0]})")
    print(f"items      : {len(items)}  (from {dataset_version})")

    print("computing corpus fingerprint (exact, from the database)...", flush=True)
    fingerprint = corpus_fingerprint_for(db_url)
    print(f"fingerprint: {fingerprint}")

    config = load_config(args.config)
    panel_cfg = config["panel"]
    measurement = MeasurementVersion(
        corpus_fingerprint=fingerprint,
        rubric_hash=args.rubric_hash,
        prompt_hash=args.prompt_hash,
        judge_set=tuple(sorted(j["model_id"] for j in panel_cfg["judges"])),
        aggregation_version="1",
        k=int(panel_cfg["samples"]),
        temperature=float(panel_cfg["temperature"]),
    )

    run_id = args.run_id or make_run_id(prefix=f"freeze-{args.corpus}")
    store = ResponseStore(corpus_fingerprint=fingerprint, run_id=run_id, runs_dir=args.runs_dir)
    print(f"run id     : {run_id}")
    print(f"writing to : {store.path}")

    if not args.confirm_spend:
        print(f"\nDRY RUN. Would make {len(items)} embedding calls and {len(items)} generation "
              f"calls against {args.corpus}.")
        print("Re-run with --confirm-spend to execute.")
        return 0

    embedder = OpenAIEmbedder()
    retriever = PgVectorExactRetriever(db_url=db_url, embedder=embedder, locale=args.locale)
    # Retrieval is always THIS repo's own retriever, against whichever corpus --corpus selected -
    # the judge must see the same passages the generator saw, so one retrieval path assigns the
    # evidence numbering for both systems. Only the GENERATION call is system-specific: each
    # corpus's own real chatbot code answers using those same retrieved passages. Before
    # 2026-09-09 there was no RealWaterGenerator, so a "realwater" freeze silently ran WaterBot's
    # generation code over RealWaterBot's corpus - see decisions.md for the entry this replaces.
    if args.corpus == "realwater":
        generator = RealWaterGenerator(model_id=args.model, temperature=0.0, locale=args.locale)
    else:
        generator = WaterBotGenerator(model_id=args.model, temperature=0.0)

    started = time.perf_counter()
    try:
        responses = freeze_run(
            store=store,
            items=items,
            retriever=retriever,
            generator=generator,
            system=args.system,
            persona=args.persona,
            dataset_version=dataset_version,
            measurement_version=measurement,
            k=args.k,
            seed=0,
            notes=(f"L1 freeze of the {len(items)}-item gold set against the {args.corpus} "
                   f"corpus. Exact kNN with the ivfflat index scan disabled."),
            overwrite=args.overwrite,
        )
    finally:
        retriever.close()

    empty = [r.item_id for r in responses if not r.answer.strip()]
    print(f"\nfrozen     : {len(responses)} responses in "
          f"{time.perf_counter() - started:.0f}s")
    print(f"passages   : {sum(len(r.passages) for r in responses)} total")
    if empty:
        print(f"WARNING    : {len(empty)} empty answer(s): {empty}")
    print(f"fingerprint: {fingerprint}")
    print(f"run id     : {run_id}")
    print(f"\nNEXT: pass --fingerprint {fingerprint} --run-id {run_id} to the panel command.")
    return 0


def _items_from_workbook(path: str, category: str = "general_policy"):
    """Read questions from the evaluator workbook, or a plain JSON list.

    The workbook is the authority for what the humans will see, so the questions are read from
    it directly rather than transcribed. Transcribing is how a question set silently drifts from
    the sheet it is supposed to match.
    """
    from eval.judge.freeze import BenchmarkItem

    if path.lower().endswith((".xlsx", ".xlsm")):
        import openpyxl

        ws = openpyxl.load_workbook(path)["Response Evaluation"]
        header_row = next(
            r for r in range(1, ws.max_row + 1)
            if str(ws.cell(row=r, column=3).value or "").strip().lower() == "test question"
        )
        items = []
        for r in range(header_row + 1, ws.max_row + 1):
            number = ws.cell(row=r, column=1).value
            question = ws.cell(row=r, column=3).value
            # The workbook carries a Summary block below the questions whose column A holds
            # labels like "Average Score". A question row is one whose number really is a number.
            if question is None or not str(question).strip():
                continue
            try:
                number = int(number)
            except (TypeError, ValueError):
                continue
            items.append(
                BenchmarkItem(
                    item_id=f"Q{number:02d}",
                    question=str(question).strip(),
                    category=category,
                    # None of these ten is an out-of-scope question, and the qualitative rubric
                    # scores every dimension on every item regardless.
                    should_refuse=False,
                )
            )
        if not items:
            raise SystemExit(f"no questions found in {path}")
        return items

    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    return [
        BenchmarkItem(
            item_id=str(row["id"]),
            question=str(row["question"]),
            category=str(row.get("category", category)),
            should_refuse=bool(row.get("should_refuse", False)),
        )
        for row in raw
    ]


def _build_client(judge: Dict[str, Any]):
    """One judge from its config entry. `provider` decides which client, and it is explicit.

    Defaulting an unrecognised provider to OpenAI would silently run a single-vendor panel while
    the config claimed otherwise, which is precisely the drift that made decision 040 necessary.
    """
    provider = str(judge.get("provider", "openai")).lower()
    model_id = judge["model_id"]

    if provider == "openai":
        from eval.judge.clients.openai_panel import OpenAIPanelClient

        return OpenAIPanelClient(model_id=model_id)

    if provider in ("huggingface", "hf"):
        from eval.judge.clients.huggingface_panel import (DEFAULT_BASE_URL,
                                                          HuggingFacePanelClient)

        return HuggingFacePanelClient(
            model_id=model_id,
            base_url=os.environ.get("HF_BASE_URL") or DEFAULT_BASE_URL,
            structured_mode=str(judge.get("structured_mode", "json_object")),
        )

    raise SystemExit(
        f"judge {model_id!r} declares provider {provider!r}, which is not implemented. "
        f"Expected 'openai' or 'huggingface'."
    )


# ---------------------------------------------------------------------------
# panel
# ---------------------------------------------------------------------------
def cmd_panel(args: argparse.Namespace) -> int:
    from eval.judge.panel import Budget, PanelRunner, Pricing
    from eval.judge.rubric import load_rubric
    from eval.judge.schemas import Response
    from eval.judge.store import ResponseStore

    config = load_config(args.config)
    panel_cfg, budget_cfg = config["panel"], config["budget"]
    print(describe_panel(config))
    print()

    # --samples overrides the config's k for THIS run only. The config file is not touched, so
    # every other run against it keeps using the value it was piloted/measured at.
    samples = int(args.samples) if args.samples is not None else int(panel_cfg["samples"])
    if args.samples is not None:
        print(f"  !! k OVERRIDDEN for this run: config says {panel_cfg['samples']}, "
              f"using {samples}")
        print()

    rubric = load_rubric(config.get("rubric", {}).get("path") or DEFAULT_RUBRIC)
    require_in_force = config.get("rubric", {}).get("require_in_force", True)
    if require_in_force and not rubric.is_in_force:
        raise SystemExit(
            f"rubric is not in force (piloted={rubric.is_piloted}, selected={rubric.selected}); "
            "refusing to produce scores that cannot be interpreted"
        )

    # `PanelRunner` enforces its own unpiloted-rubric gate, independently of the check above.
    # Setting `require_in_force: false` in a config IS the deliberate override the runner asks
    # for, so it has to be passed through - otherwise the config flag looks honoured here and
    # the run still dies inside the runner.
    #
    # Announced loudly rather than passed quietly. An unpiloted rubric produces scores no human
    # has ever validated, and a reader of this output should not have to open the config to
    # discover that.
    allow_unpiloted = not require_in_force
    if allow_unpiloted and not rubric.is_piloted:
        print("  !! UNPILOTED RUBRIC. No human annotator has ever applied these anchors, so")
        print("     these scores are EXPLORATORY and carry no measured reliability. Proceeding")
        print("     because the config sets require_in_force: false.")
        print()

    store = ResponseStore(
        corpus_fingerprint=args.fingerprint, run_id=args.run_id, runs_dir=args.runs_dir)
    responses: List[Response] = list(store.load_responses(args.system, args.persona))
    if not responses:
        raise SystemExit(
            f"no frozen responses for system={args.system!r} persona={args.persona!r} in "
            f"{args.runs_dir}/{args.fingerprint}/{args.run_id}. Run `freeze` first."
        )
    print(f"frozen responses loaded : {len(responses)}  (system={args.system}, "
          f"persona={args.persona})")

    if args.items:
        known = {r.item_id for r in responses}
        missing = [i for i in args.items if i not in known]
        if missing:
            raise SystemExit(f"no frozen response for item(s): {missing}")
        responses = [r for r in responses if r.item_id in set(args.items)]
        print(f"filtered to {len(responses)} named item(s): {sorted(r.item_id for r in responses)}")
    elif args.limit:
        responses = responses[: args.limit]
        print(f"limited to the first {len(responses)} item(s): "
              f"{sorted(r.item_id for r in responses)}")

    if not args.confirm_spend:
        n_calls = len(responses) * len(panel_cfg["judges"]) * samples
        print(f"\nDRY RUN. Would make up to {n_calls} judge calls "
              f"({len(responses)} items x {len(panel_cfg['judges'])} judges x "
              f"k={samples}).")
        print("Re-run with --confirm-spend to execute.")
        return 0

    rates = Pricing(prompt=budget_cfg["prompt_per_1k"],
                    completion=budget_cfg["completion_per_1k"],
                    cached_prompt=budget_cfg["cached_prompt_per_1k"])
    clients = [_build_client(j) for j in panel_cfg["judges"]]
    runner = PanelRunner(
        clients=clients,
        rubric=rubric,
        # The rubric's OWN hash, not the CLI label. A hand-written string made a qualitative run
        # and a factual run carry the same rubric_hash, so MeasurementVersion - whose entire job
        # is refusing to compare things measured differently - would have pooled them silently.
        rubric_hash=rubric.rubric_hash,
        corpus_fingerprint=args.fingerprint,
        pricing={c.model_id: rates for c in clients},
        budget=Budget(cap_usd=float(args.budget or budget_cfg["cap_usd"])),
        temperature=float(panel_cfg["temperature"]),
        samples=samples,
        max_tokens=max(
            int(panel_cfg.get("max_tokens", 1500)),
            # A reasoning model that emits a trace before its verdict needs headroom, and the
            # runner applies one max_tokens to every judge. Taking the largest configured value
            # is the only safe reconciliation: too small truncates a verdict into a hard failure.
            *(int(j.get("max_tokens", 0)) for j in panel_cfg["judges"]),
        ),
        template_name=config.get("prompt", {}).get("template", POINTWISE_V1),
        allow_unpiloted_rubric=allow_unpiloted,
    )

    # Written per CALL, not per item and not at the end. Two earlier versions of this loop lost
    # work: dumping at the end meant a budget stop produced an empty file, and flushing per item
    # meant a single-item run showed nothing for fourteen minutes and then everything at once.
    # Per-call also means a rejected verdict is visible the moment it happens rather than being
    # inferred from a short file afterwards.
    import time

    from eval.judge.panel import BudgetExceeded, VerdictRejected

    # A gateway timeout (HF's router returning a bare 504) or a similar transient provider
    # error is not a budget stop and not a verdict problem - it is the network having a bad
    # moment. Retrying the ONE call a couple of times with backoff, rather than aborting the
    # whole 60-call run, is what a single 504 cost this run on 2026-09-09.
    MAX_TRANSIENT_RETRIES = 2

    # Default now writes INSIDE the run directory, beside manifest.json and responses/, rather
    # than a loose file at the repo root. Ten stray verdicts_*.jsonl smoke files accumulated
    # there before this. --out still overrides for a one-off.
    if args.out:
        out = args.out
    else:
        out = os.path.join(args.runs_dir, args.fingerprint, args.run_id, "verdicts",
                           f"panel_{args.persona}.jsonl")
        os.makedirs(os.path.dirname(out), exist_ok=True)
    verdicts = []
    stopped_early: Optional[str] = None
    total_calls = len(responses) * len(clients) * samples
    done = 0

    with open(out, "w", encoding="utf-8") as fh:
        for response in responses:
            for client in clients:
                for sample_index in range(samples):
                    done += 1
                    label = (f"[{done}/{total_calls}] {response.item_id} "
                             f"{client.model_id.split('/')[-1][:22]:22} s{sample_index}")
                    verdict = None
                    attempt = 0
                    while True:
                        try:
                            verdict = runner.judge_once(response, client, sample_index)
                            break
                        except VerdictRejected as exc:
                            # Counted, reported, and NOT fatal: one judge failing validation on
                            # one sample should not discard the other opinions on the same item.
                            print(f"  {label}  REJECTED  {str(exc)[-110:]}", flush=True)
                            break
                        except BudgetExceeded as exc:
                            stopped_early = f"{type(exc).__name__}: {exc}"
                            print(f"\nSTOPPED at {label}: {stopped_early}")
                            break
                        except Exception as exc:  # noqa: BLE001 - transient provider failure
                            attempt += 1
                            if attempt > MAX_TRANSIENT_RETRIES:
                                msg = f"{label}: gave up after {attempt - 1} retries - {exc}"
                                runner.stats.failures.append(msg)
                                print(f"  {label}  SKIPPED  {str(exc)[-110:]}", flush=True)
                                break
                            wait = 10 * attempt
                            print(f"  {label}  transient error ({type(exc).__name__}), "
                                  f"retry {attempt}/{MAX_TRANSIENT_RETRIES} in {wait}s",
                                  flush=True)
                            time.sleep(wait)
                    if stopped_early:
                        break
                    if verdict is None:
                        continue
                    fh.write(json.dumps(verdict.model_dump(mode="json"), sort_keys=True) + "\n")
                    fh.flush()
                    verdicts.append(verdict)
                    print(f"  {label}  ok  ${runner.budget.spent_usd:.4f}", flush=True)
                if stopped_early:
                    break
            if stopped_early:
                break

    if stopped_early:
        print(f"\nPARTIAL RUN. {len(verdicts)} verdicts over "
              f"{len({v.item_id for v in verdicts})} items were written to {out} and are usable.")
        print("Re-run with a higher --budget to finish, or aggregate what you have.")

    if runner.stats.failures:
        print()
        print(f"REJECTED: {len(runner.stats.failures)} of {total_calls} verdicts failed "
              f"validation twice, including after a repair attempt. Reasons:")
        for message in runner.stats.failures[:12]:
            print(f"  - {message[:220]}")
        if len(runner.stats.failures) > 12:
            print(f"  ... and {len(runner.stats.failures) - 12} more")

    print(f"\nverdicts : {len(verdicts)} -> {out}")
    print(f"calls    : {runner.stats.called}   repaired: {runner.stats.repaired}   "
          f"rejected: {runner.stats.rejected}")
    print(f"spend    : ${runner.budget.spent_usd:.4f} of ${runner.budget.cap_usd:.2f} cap "
          f"(at ASSUMED rates)")
    return 0


# ---------------------------------------------------------------------------
# aggregate
# ---------------------------------------------------------------------------
def cmd_aggregate(args: argparse.Namespace) -> int:
    from eval.judge.aggregate import aggregate_dimension, votes_for
    from eval.judge.schemas import Verdict

    verdicts: List[Verdict] = []
    for path in args.verdicts:
        if not os.path.exists(path):
            raise SystemExit(f"no verdict file at {path}")
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    verdicts.append(Verdict.model_validate_json(line))
    if not verdicts:
        raise SystemExit("no verdicts to aggregate")

    by_item: Dict[str, List[Verdict]] = {}
    for v in verdicts:
        by_item.setdefault(v.item_id, []).append(v)

    dimensions = sorted({d for v in verdicts for d in v.dimensions})
    expected = args.expected_votes
    rows = []
    print(f"{'item':8} {'dimension':26} {'median':>7} {'IQR':>6} {'entropy':>8} "
          f"{'votes':>6} {'abst':>5}  escalation")
    print("-" * 96)
    for item_id in sorted(by_item):
        for dimension in dimensions:
            votes = votes_for(by_item[item_id], dimension)
            if not votes:
                continue
            agg = aggregate_dimension(
                response_id=item_id, dimension=dimension, votes=votes,
                expected_votes=expected)
            rows.append(agg.to_dict() if hasattr(agg, "to_dict") else {
                "response_id": item_id, "dimension": dimension,
                "median": agg.median, "iqr": agg.iqr, "entropy": agg.entropy,
                "n_votes": agg.n_votes, "n_abstained": agg.n_abstained,
                "escalate": agg.escalate, "escalation_reason": agg.escalation_reason,
            })
            med = "-" if agg.median is None else f"{agg.median:.2f}"
            iqr = "-" if agg.iqr is None else f"{agg.iqr:.2f}"
            ent = "-" if agg.entropy is None else f"{agg.entropy:.3f}"
            print(f"{item_id:8} {dimension:26} {med:>7} {iqr:>6} {ent:>8} "
                  f"{agg.n_votes:>6} {agg.n_abstained:>5}  {agg.escalation_reason or ''}")

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, indent=2)
    n_esc = sum(1 for r in rows if r.get("escalate"))
    n_abst = sum(r.get("n_abstained", 0) for r in rows)
    print()
    print(f"aggregates : {len(rows)} -> {args.out}")
    print(f"escalated  : {n_esc}   total abstentions: {n_abst}")
    print("NOTE: every IQR above is computed over the samples that DID score. Abstention counts "
          "travel with it (decision 038).")
    return 0


def cmd_sheet(args: argparse.Namespace) -> int:
    """Build the human-evaluator workbook from panel verdicts."""
    from eval.judge.qualitative_sheet import build, chatbot_answers_from, load_verdicts

    verdicts = load_verdicts(args.verdicts)

    answers = None
    responses_path = args.responses
    if not responses_path and args.fingerprint and args.run_id:
        responses_path = os.path.join(
            args.runs_dir, args.fingerprint, args.run_id, "responses",
            f"{args.system}__{args.persona}.jsonl")
    if responses_path:
        if not os.path.exists(responses_path):
            raise SystemExit(f"no frozen responses at {responses_path}")
        answers = chatbot_answers_from(responses_path)
        print(f"chatbot answers: {len(answers)} loaded from {responses_path}")

    result = build(
        template=args.template,
        out=args.out,
        verdicts=verdicts,
        include_scores=args.include_scores,
        chatbot_answers=answers,
    )

    print(f"verdicts read : {len(verdicts)}")
    print(f"rows written  : {result['rows']}  (one per question x judge)")
    print(f"scores shown  : {args.include_scores}")
    print()
    print("judge labels (BLIND in the sheet; this mapping is the key):")
    for model_id, label in sorted(result["judges"].items(), key=lambda kv: kv[1]):
        print(f"  {label}  =  {model_id}")

    key_path = os.path.splitext(args.out)[0] + "_key.json"
    with open(key_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2)
    print()
    print(f"wrote {args.out}")
    print(f"wrote {key_path}  (judge identities and the scores behind each row)")
    print()
    print("The raters see a judgement and the ten criteria. They do NOT see which model wrote")
    print("it, and they do not see the panel's own scores unless --include-scores was set.")
    return 0


# ---------------------------------------------------------------------------
# tripwire
# ---------------------------------------------------------------------------
def cmd_tripwire(args: argparse.Namespace) -> int:
    """Re-judge the same answers with the evidence removed (or swapped), and compare.

    The point is validity, not score. If a judge scores an answer just as highly with NO
    evidence in front of it, the grounding number was never measuring grounding - it was
    rewarding fluent prose. A large drop, or mass abstention, is the metric passing.
    """
    import time

    from eval.judge.panel import (Budget, BudgetExceeded, PanelRunner, Pricing, VerdictRejected,
                                  evaluate_tripwire, parametric_reliance, strip_evidence,
                                  withhold_evidence)
    from eval.judge.rubric import load_rubric
    from eval.judge.schemas import Response, Verdict
    from eval.judge.store import ResponseStore

    config = load_config(args.config)
    panel_cfg, budget_cfg = config["panel"], config["budget"]
    print(describe_panel(config))
    print()

    rubric = load_rubric(config.get("rubric", {}).get("path") or DEFAULT_RUBRIC)
    require_in_force = config.get("rubric", {}).get("require_in_force", True)
    if require_in_force and not rubric.is_in_force:
        raise SystemExit("rubric is not in force; refusing to produce scores")

    store = ResponseStore(
        corpus_fingerprint=args.fingerprint, run_id=args.run_id, runs_dir=args.runs_dir)
    responses: List[Response] = list(store.load_responses(args.system, args.persona))
    if not responses:
        raise SystemExit(f"no frozen responses in {args.runs_dir}/{args.fingerprint}/{args.run_id}")

    if args.items:
        responses = [r for r in responses if r.item_id in set(args.items)]
    elif args.limit:
        responses = responses[: args.limit]
    if len(responses) < 2 and args.mode == "withhold":
        raise SystemExit("withhold mode needs at least 2 items - one has to donate its evidence")
    print(f"tripwire mode : {args.mode}   items: {len(responses)} "
          f"({', '.join(r.item_id for r in responses)})")

    # Build the altered condition.
    altered: List[Response] = []
    for index, response in enumerate(responses):
        if args.mode == "strip":
            altered.append(strip_evidence(response))
        else:
            donor = responses[(index + 1) % len(responses)]
            altered.append(withhold_evidence(response, donor))

    samples = int(args.samples) if args.samples is not None else int(panel_cfg["samples"])
    n_calls = len(altered) * len(panel_cfg["judges"]) * samples
    if not args.confirm_spend:
        print(f"\nDRY RUN. Would make {n_calls} judge calls "
              f"({len(altered)} items x {len(panel_cfg['judges'])} judges x k={samples}).")
        print("Re-run with --confirm-spend to execute.")
        return 0

    rates = Pricing(prompt=budget_cfg["prompt_per_1k"],
                    completion=budget_cfg["completion_per_1k"],
                    cached_prompt=budget_cfg["cached_prompt_per_1k"])
    clients = [_build_client(j) for j in panel_cfg["judges"]]
    runner = PanelRunner(
        clients=clients, rubric=rubric, rubric_hash=rubric.rubric_hash,
        corpus_fingerprint=args.fingerprint,
        pricing={c.model_id: rates for c in clients},
        budget=Budget(cap_usd=float(args.budget or budget_cfg["cap_usd"])),
        temperature=float(panel_cfg["temperature"]),
        samples=samples,
        max_tokens=max(int(panel_cfg.get("max_tokens", 1500)),
                       *(int(j.get("max_tokens", 0)) for j in panel_cfg["judges"])),
        template_name=config.get("prompt", {}).get("template", POINTWISE_V1),
        allow_unpiloted_rubric=not require_in_force,
    )

    out = args.out or os.path.join(args.runs_dir, args.fingerprint, args.run_id, "verdicts",
                                   f"tripwire_{args.mode}_{args.persona}.jsonl")
    os.makedirs(os.path.dirname(out), exist_ok=True)

    stripped_verdicts: List[Verdict] = []
    done = 0
    with open(out, "w", encoding="utf-8") as fh:
        for response in altered:
            for client in clients:
                for sample_index in range(samples):
                    done += 1
                    label = (f"[{done}/{n_calls}] {response.item_id} "
                             f"{client.model_id.split('/')[-1][:22]:22} s{sample_index}")
                    try:
                        verdict = runner.judge_once(response, client, sample_index)
                    except VerdictRejected as exc:
                        print(f"  {label}  REJECTED  {str(exc)[-100:]}", flush=True)
                        continue
                    except BudgetExceeded as exc:
                        print(f"\nSTOPPED at {label}: {exc}")
                        break
                    except Exception as exc:  # noqa: BLE001
                        print(f"  {label}  SKIPPED  {str(exc)[-100:]}", flush=True)
                        continue
                    fh.write(json.dumps(verdict.model_dump(mode="json"), sort_keys=True) + "\n")
                    fh.flush()
                    stripped_verdicts.append(verdict)
                    print(f"  {label}  ok  ${runner.budget.spent_usd:.4f}", flush=True)

    print(f"\naltered-condition verdicts : {len(stripped_verdicts)} -> {out}")
    print(f"spend : ${runner.budget.spent_usd:.4f}")

    # Compare against the main run, restricted to the same items.
    full = [Verdict.model_validate_json(line) for line in open(args.full_verdicts, encoding="utf-8")
            if line.strip()]
    keep = {r.item_id for r in responses}
    full = [v for v in full if v.item_id in keep]
    print(f"\nfull-evidence verdicts for these items : {len(full)}")

    result = evaluate_tripwire(full, stripped_verdicts, threshold=args.threshold)
    print()
    print("=" * 66)
    print("TRIPWIRE RESULT  (mode=%s)" % args.mode)
    print("=" * 66)
    print(f"  items compared            : {result.n_items}")
    print(f"  mean score WITH evidence  : "
          f"{result.full_mean if result.full_mean is None else round(result.full_mean, 3)}")
    print(f"  mean score WITHOUT        : "
          f"{result.stripped_mean if result.stripped_mean is None else round(result.stripped_mean, 3)}")
    print(f"  drop                      : "
          f"{result.drop if result.drop is None else round(result.drop, 3)}  "
          f"(threshold {result.threshold})")
    print(f"  abstention rate WITHOUT   : {result.stripped_abstention_rate:.1%}")
    print(f"  metric survived           : {result.metric_survived}")
    print(f"  verdict                   : {result.verdict}")
    if args.mode == "withhold":
        print()
        print("  parametric reliance (scored anyway on WRONG evidence):")
        for k, v in parametric_reliance(stripped_verdicts).items():
            print(f"    {k}: {v}")
    return 0


# ---------------------------------------------------------------------------
# results-sheet
# ---------------------------------------------------------------------------
def cmd_results_sheet(args: argparse.Namespace) -> int:
    """Flat, sortable review workbook of a factual panel run - generated FROM the jsonl."""
    from eval.judge.results_sheet import build

    responses_path = args.responses
    if not responses_path:
        responses_path = os.path.join(
            args.runs_dir, args.fingerprint, args.run_id, "responses",
            f"{args.system}__{args.persona}.jsonl")
    if not os.path.exists(responses_path):
        raise SystemExit(f"no frozen responses at {responses_path}; pass --responses explicitly")

    out = args.out or os.path.join(
        args.runs_dir, args.fingerprint, args.run_id, "verdicts", "panel_review.xlsx")

    result = build(verdict_paths=args.verdicts, responses_path=responses_path, out=out)
    print(f"verdicts read : {result['verdicts']}")
    print(f"items         : {result['items']}")
    print(f"judges        : {', '.join(result['judges'])}")
    print(f"rows written  : {result['rows']}  (one per item x judge x dimension)")
    print()
    print(f"wrote {result['out']}")
    print("This workbook is GENERATED from the jsonl. Do not hand-edit it - regenerate it. The")
    print("jsonl beside it is the source of truth every downstream step reads.")
    return 0


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------
LIMITATIONS = [
    "The judge panel is three generations of ONE company's models (OpenAI), NOT three different "
    "companies. M7 specifies 3+ model families because its mechanism is error decorrelation; "
    "models from one vendor share training data, post-training method, tokenizer and failure "
    "modes, so their errors are correlated. A panel that agrees may be agreeing because it is "
    "three views of one system. This is a constraint of the project's available credentials, not "
    "an oversight. Adding a second provider family is future work.",

    "The self-preference analysis (whether a judge favours its own family's output) cannot be "
    "run at all with a single-vendor panel. Future work.",

    "Dollar figures rest on an ASSUMED price table that has never been verified against "
    "published rates. Token counts are measured; the conversion to dollars is not audited.",

    "The system under test is nondeterministic and the judge is not. At temperature 0, with "
    "retrieved passages held identical, 11 of 12 negative items produced different answers "
    "across 25 runs (up to 17 distinct answers). The judge, by contrast, was perfectly stable "
    "(SD 0.00 over 25 replicates). Scores here are of ONE frozen answer per item, not of the "
    "distribution of answers the system would produce.",

    "The original 8.3-point instability is attributed to generation but not quantitatively "
    "closed. One item of twelve flipping equals 8.3 points exactly, which is consistent with the "
    "measured generation variance, but the link was not measured end to end. Future work.",

    "Panel abstention is not perfectly stable: pooled 3/100 (Wilson 95% [0.010, 0.085]) at k=20, "
    "concentrated on one item which also varied in score. Every spread statistic here is "
    "computed over the samples that scored, so abstention counts are reported alongside.",

    "The gold set is 30 items, and one of its five topic categories contains a single item. This "
    "supports overall figures only, not per-category claims. Expanding the benchmark and "
    "recruiting additional expert annotators is future work.",

    "The rubric pilot established inter-annotator agreement on two people over 12 items "
    "(28 scored units), Cohen's kappa 0.839 quadratic-weighted. Two annotators is the minimum "
    "for the statistic and a larger annotator pool is future work.",

    "citation_validity and temporal_integrity are defined in the rubric but were never exercised: "
    "the answers carry no inline citations and the gold set contains no time-sensitive items.",

    "The document corpus is knowingly incomplete, its currency is unknown, and 127 of 370 "
    "document names share content with another name. Corpus repair is deliberately out of scope.",

    "No ablation grid was run. The full grid as specified is 3,456 configurations and roughly "
    "$1,120; sizing and slicing it is future work.",
]


def cmd_report(args: argparse.Namespace) -> int:
    if not os.path.exists(args.aggregates):
        raise SystemExit(f"no aggregates at {args.aggregates}")
    with open(args.aggregates, encoding="utf-8") as fh:
        rows = json.load(fh)
    if not rows:
        raise SystemExit("aggregates file is empty")

    from eval.judge.report import reported
    from eval.stats import clustered_bootstrap_ci

    by_dimension: Dict[str, List[float]] = {}
    abstentions: Dict[str, int] = {}
    for r in rows:
        if r.get("median") is None:
            continue
        by_dimension.setdefault(r["dimension"], []).append(float(r["median"]))
        abstentions[r["dimension"]] = abstentions.get(r["dimension"], 0) + r.get("n_abstained", 0)

    lines = [
        f"# Judge panel report - {args.label}",
        "",
        "## Scores",
        "",
        "Every number carries a clustered bootstrap interval that resamples ITEMS, because the",
        "benchmark is a sample of questions. Abstention counts are reported beside each score:",
        "the interval is computed over the samples that scored.",
        "",
        "| Dimension | Items | Mean | 95% interval | Abstentions |",
        "|---|---|---|---|---|",
    ]
    # `clustered_bootstrap` hands stat_fn the RESAMPLED CLUSTERS, not flat values (see its
    # docstring). One cluster here is one question, so the statistic has to flatten before it
    # averages - summing the clusters directly is what raised
    # "unsupported operand type(s) for +: 'int' and 'list'".
    def _mean_over_clusters(clusters: Sequence[Sequence[float]]) -> float:
        flat = [v for cluster in clusters for v in cluster]
        return sum(flat) / len(flat) if flat else float("nan")

    for dimension in sorted(by_dimension):
        values = by_dimension[dimension]
        mean = sum(values) / len(values)
        if len(values) > 1:
            lo, hi = clustered_bootstrap_ci(
                [[v] for v in values], _mean_over_clusters, n_boot=2000, seed=0)
            interval = f"[{lo:.2f}, {hi:.2f}]"
        else:
            interval = "n/a (single item)"
        lines.append(f"| `{dimension}` | {len(values)} | {mean:.2f} | {interval} | "
                     f"{abstentions.get(dimension, 0)} |")

    lines += [
        "",
        "## What this panel is, stated plainly",
        "",
        "**The judge panel is three generations of ONE AI company's models, not three different",
        "companies.** The three judges are `gpt-5.4-2026-03-05`, `gpt-5.2-2025-12-11` and",
        "`gpt-4.1-2025-04-14`, all from OpenAI.",
        "",
        "This matters and is not a technicality. The reason a panel is used at all is error",
        "decorrelation: independent judges make independent mistakes, so their agreement carries",
        "information. Models from one vendor share training data, post-training method, tokenizer",
        "and failure modes. Their errors are correlated, so agreement between them is weaker",
        "evidence than agreement between genuinely independent judges would be. Every claim in",
        "this report that rests on panel agreement should be read with that discount applied.",
        "",
        "## Limitations",
        "",
    ]
    for i, limitation in enumerate(LIMITATIONS, 1):
        lines.append(f"{i}. {limitation}")
        lines.append("")

    markdown = "\n".join(lines)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(markdown)
    print(markdown)
    print(f"\nwrote {args.out}")
    return 0


# ---------------------------------------------------------------------------
def main(argv: Optional[Sequence[str]] = None) -> int:
    # Load .env once, here, for EVERY subcommand. It used to be loaded inside `freeze` only,
    # which meant `freeze` worked and `panel` died on a missing OPENAI_API_KEY after already
    # printing its config banner. Credentials are a property of the process, not of one command.
    try:
        from dotenv import load_dotenv

        load_dotenv(os.path.join(os.getcwd(), ".env"))
    except ImportError:  # pragma: no cover - python-dotenv is a declared dependency
        pass

    parser = argparse.ArgumentParser(prog="python -m eval.judge.cli")
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("show-panel", help="print the panel exactly as configured").set_defaults(
        func=cmd_show_panel)

    f = sub.add_parser("freeze", help="L1: run the gold set against one corpus, store immutably")
    f.add_argument("--corpus", required=True, choices=sorted(CORPORA))
    f.add_argument("--system", required=True, help="label recorded on every response")
    f.add_argument("--persona", default="blue")
    f.add_argument("--gold", default="gold_set.json")
    f.add_argument("--questions", default=None,
                   help="question set with no gold answers: the evaluator .xlsx, "
                        "or a JSON list of {id, question, category}")
    f.add_argument("--category", default="general_policy",
                   help="category applied to questions read via --questions")
    f.add_argument("--k", type=int, default=4, help="passages retrieved per question")
    f.add_argument("--locale", default="en")
    f.add_argument("--model", default="gpt-4.1", help="generation model for the system under test")
    f.add_argument("--run-id", default=None)
    f.add_argument("--runs-dir", default=os.path.join("eval", "results", "runs"))
    f.add_argument("--rubric-hash", default="panel-final")
    f.add_argument("--prompt-hash", default="pointwise-v1")
    f.add_argument("--overwrite", action="store_true")
    f.add_argument("--confirm-spend", action="store_true")
    f.set_defaults(func=cmd_freeze)

    p = sub.add_parser("panel", help="run the judge panel over a frozen response set")
    p.add_argument("--fingerprint", required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--system", required=True)
    p.add_argument("--persona", default="blue")
    p.add_argument("--runs-dir", default=os.path.join("eval", "results", "runs"))
    p.add_argument("--rubric-hash", default="panel-final")
    p.add_argument("--budget", type=float, default=None)
    p.add_argument("--confirm-spend", action="store_true")
    p.add_argument("--out", default=None)
    p.add_argument("--limit", type=int, default=None,
                   help="judge only the first N items - for a small batch before the full run")
    p.add_argument("--items", nargs="*", default=None,
                   help="judge only these item ids, e.g. --items q001 q009 q017")
    p.add_argument("--samples", type=int, default=None,
                   help="override k (samples per judge) for this run only, without editing "
                        "the config - e.g. a cheaper probe that does not need the config's full k")
    p.set_defaults(func=cmd_panel)

    t = sub.add_parser("tripwire",
                       help="re-judge the same answers with evidence removed/swapped, and "
                            "compare - a validity check on the grounding metric")
    t.add_argument("--fingerprint", required=True)
    t.add_argument("--run-id", required=True)
    t.add_argument("--system", required=True)
    t.add_argument("--persona", default="blue")
    t.add_argument("--runs-dir", default=os.path.join("eval", "results", "runs"))
    t.add_argument("--full-verdicts", required=True,
                   help="the main run's verdicts jsonl, to compare against")
    t.add_argument("--mode", choices=("strip", "withhold"), default="strip",
                   help="strip: no evidence at all (is the metric measuring anything?). "
                        "withhold: another item's evidence (does the judge answer from memory?)")
    t.add_argument("--items", nargs="*", default=None)
    t.add_argument("--limit", type=int, default=None,
                   help="use only the first N items - a subset is enough to make the point")
    t.add_argument("--samples", type=int, default=None, help="override k for this run only")
    t.add_argument("--threshold", type=float, default=0.5,
                   help="how far the mean must fall for the metric to count as surviving")
    t.add_argument("--budget", type=float, default=None)
    t.add_argument("--confirm-spend", action="store_true")
    t.add_argument("--out", default=None)
    t.set_defaults(func=cmd_tripwire)

    a = sub.add_parser("aggregate", help="collapse panel votes into scored aggregates")
    a.add_argument("--verdicts", nargs="+", required=True)
    a.add_argument("--expected-votes", type=int, default=None)
    a.add_argument("--out", default="aggregates.json")
    a.set_defaults(func=cmd_aggregate)

    s = sub.add_parser("sheet", help="build the human-evaluator workbook from verdicts")
    s.add_argument("--verdicts", nargs="+", required=True)
    s.add_argument("--template", default="RealWater_Qualitative_Response_Evaluation.xlsx")
    s.add_argument("--out", default="RealWater_Qualitative_FOR_EVALUATORS.xlsx")
    s.add_argument("--include-scores", action="store_true",
                   help="show the judge's 1-4 scores alongside its reasoning. Off by default: "
                        "with scores visible a rater tends to rate whether they AGREE with the "
                        "number rather than whether the reasoning holds together.")
    # The chatbot's own answers go in column D. Pass --responses directly, or let it be
    # inferred from the run dir via --fingerprint/--run-id/--system.
    s.add_argument("--responses", default=None,
                   help="path to the frozen responses jsonl; its answers fill column D")
    s.add_argument("--fingerprint", default=None)
    s.add_argument("--run-id", default=None)
    s.add_argument("--system", default="realwater")
    s.add_argument("--persona", default="blue")
    s.add_argument("--runs-dir", default=os.path.join("eval", "results", "runs"))
    s.set_defaults(func=cmd_sheet)

    rs = sub.add_parser("results-sheet",
                        help="flat review workbook of a factual panel run, from its jsonl")
    rs.add_argument("--verdicts", nargs="+", required=True)
    rs.add_argument("--fingerprint", required=True)
    rs.add_argument("--run-id", required=True)
    rs.add_argument("--system", required=True)
    rs.add_argument("--persona", default="blue")
    rs.add_argument("--runs-dir", default=os.path.join("eval", "results", "runs"))
    rs.add_argument("--responses", default=None,
                    help="path to the frozen responses jsonl; inferred from the run dir if omitted")
    rs.add_argument("--out", default=None,
                    help="xlsx path; defaults to <run dir>/verdicts/panel_review.xlsx")
    rs.set_defaults(func=cmd_results_sheet)

    r = sub.add_parser("report", help="publish scores with intervals and limitations")
    r.add_argument("--aggregates", default="aggregates.json")
    r.add_argument("--label", default="final")
    r.add_argument("--out", default="report.md")
    r.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
