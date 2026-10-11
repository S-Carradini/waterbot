import os
import sys
import json
import argparse
import asyncio
import datetime

# Bump when a change alters what the metrics MEAN rather than how the system
# performs. Runs with different versions are never compared. See the comment
# on the history record in run_suite().
MEASUREMENT_VERSION = 2

# Ensure both project root and application are in Python path
_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_script_dir)
_application_dir = os.path.join(_project_root, "application")
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
if _application_dir not in sys.path:
    sys.path.insert(0, _application_dir)

from eval.config import resolve_db_url

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML is not installed. Please run: pip install pyyaml")
    sys.exit(1)

from eval.retrieval_metrics import run_retrieval_evaluation
from eval.generation_metrics import run_generation_evaluation
from eval.preflight import run_preflight, print_human

async def run_suite(skip_preflight: bool = False):
    print("START: Starting RAG Evaluation Suite")

    db_url = resolve_db_url()

    # Load thresholds
    thresholds_path = os.path.join(_script_dir, "thresholds.yaml")
    with open(thresholds_path, "r", encoding="utf-8") as f:
        thresholds = yaml.safe_load(f)

    print(f"Loaded Thresholds: {thresholds}")

    # 0. Corpus preflight — runs BEFORE any LLM spend.
    #
    # If gold documents are missing from the corpus, every downstream number
    # measures corpus completeness rather than system quality, and the whole
    # run is wasted money producing a misleading result. Fail fast instead.
    preflight = None
    if not skip_preflight:
        try:
            preflight = run_preflight(db_url=db_url)
            print_human(preflight)
        except Exception as e:
            print(f"ERROR: Preflight could not inspect the corpus: {e}")
            print("Is the database running? Use --skip-preflight to bypass (not recommended).")
            sys.exit(2)

        if not preflight["passed"]:
            missing = preflight["gold_sources"]["missing"]
            affected = len(preflight["gold_sources"]["affected_questions"])
            print(f"\nABORT: {missing} gold document(s) are absent from the corpus, "
                  f"affecting {affected} question(s).")
            print("Retrieval scores computed now would measure corpus completeness,")
            print("not retrieval quality. Fix the corpus or the benchmark first.")
            print("Override with --skip-preflight if you understand the caveat.")
            sys.exit(1)

    # 1. Run Retrieval Eval
    retrieval_summary = run_retrieval_evaluation(db_url=db_url)
    retrieval_metrics = retrieval_summary["aggregate_metrics"]
    
    # 2. Run Generation Eval
    generation_summary = await run_generation_evaluation(db_url=db_url)
    generation_metrics = generation_summary["metrics"]
    hallucination_rate = generation_summary["hallucination_on_negatives_rate"]
    
    # 3. Check Thresholds
    passed = True
    print("\n Checking Results Against Thresholds:")
    
    # Faithfulness
    f_score = generation_metrics.get("faithfulness", 0)
    f_min = thresholds.get("faithfulness_min", 0.0)
    if f_score < f_min:
        print(f"ERROR: Faithfulness: {f_score:.4f} < {f_min:.4f}")
        passed = False
    else:
        print(f"SUCCESS: Faithfulness: {f_score:.4f} >= {f_min:.4f}")
        
    # Answer Correctness
    ac_score = generation_metrics.get("answer_correctness", 0)
    ac_min = thresholds.get("answer_correctness_min", 0.0)
    if ac_score < ac_min:
        print(f"ERROR: Answer Correctness: {ac_score:.4f} < {ac_min:.4f}")
        passed = False
    else:
        print(f"SUCCESS: Answer Correctness: {ac_score:.4f} >= {ac_min:.4f}")
        
    # Retrieval Recall@4
    r_score = retrieval_metrics.get("recall@4", 0)
    r_min = thresholds.get("retrieval_recall_at_4_min", 0.0)
    if r_score < r_min:
        print(f"ERROR: Retrieval Recall@4: {r_score:.4f} < {r_min:.4f}")
        passed = False
    else:
        print(f"SUCCESS: Retrieval Recall@4: {r_score:.4f} >= {r_min:.4f}")
        
    # Hallucination Rate
    h_max = thresholds.get("hallucination_on_negatives_max", 1.0)
    if hallucination_rate > h_max:
        print(f"ERROR: Hallucination on Negatives Rate: {hallucination_rate:.4f} > {h_max:.4f}")
        passed = False
    else:
        print(f"SUCCESS: Hallucination on Negatives Rate: {hallucination_rate:.4f} <= {h_max:.4f}")
        
    # 4. Append to history and check for regressions
    results_dir = os.path.join(_script_dir, "results")
    os.makedirs(results_dir, exist_ok=True)
    history_path = os.path.join(results_dir, "eval_history.jsonl")
    
    history_record = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "passed": passed,
        # MEASUREMENT_VERSION identifies what these numbers *mean*.
        #
        # v1 runs are not comparable to v2 runs. Between them, three defects
        # were fixed that each changed the metrics' meaning rather than the
        # system's behaviour:
        #   * the benchmark question was never sent to the LLM (generation
        #     metrics were scoring answers to an empty prompt)
        #   * retrieval joined on raw filenames, so correct retrievals of
        #     aliased documents scored as misses
        #   * RAGAS aggregates included out-of-scope negatives
        #
        # Scores will jump sharply at this boundary. That jump is a
        # measurement correction, NOT a quality improvement, and the
        # regression check below refuses to compare across versions so it can
        # never be reported as a win.
        "measurement_version": MEASUREMENT_VERSION,
        "metrics": {
            "faithfulness": f_score,
            "answer_correctness": ac_score,
            "retrieval_recall_at_4": r_score,
            "hallucination_on_negatives_rate": hallucination_rate
        },
        "provenance": {
            "corpus_fingerprint": (preflight or {}).get("corpus", {}).get("fingerprint"),
            "alias_groups_active": (preflight or {}).get("aliases", {}).get("groups_active"),
            "alias_groups_unverified": (preflight or {}).get("aliases", {}).get("groups_unverified"),
            "model_id": generation_summary.get("model_id"),
            "scored_questions": generation_summary.get("scored_questions"),
            "preflight_skipped": preflight is None,
        },
    }
    
    # Regression detection: compare against last N runs
    regression_threshold = 0.05  # Warn if any metric drops by more than 5%
    history_lookback = 3  # Compare against last 3 runs
    
    if os.path.exists(history_path):
        with open(history_path, "r", encoding="utf-8") as f:
            history_lines = f.readlines()

        if history_lines:
            # Only compare against runs measured the same way. Records written
            # before the Phase 0 fixes carry a different (or absent) version
            # and describe different quantities.
            comparable = []
            skipped_versions = 0
            for line in history_lines:
                try:
                    record = json.loads(line.strip())
                except json.JSONDecodeError:
                    continue
                if record.get("measurement_version", 1) == MEASUREMENT_VERSION:
                    comparable.append(record)
                else:
                    skipped_versions += 1

            recent_runs = comparable[-history_lookback:]

            # Single header for the whole regression section, whichever
            # combination of notices applies below.
            if skipped_versions or not recent_runs:
                print(f"\n--- Regression Check ---")
            if skipped_versions:
                print(f"  Ignoring {skipped_versions} historical run(s) from an earlier "
                      f"measurement version; their numbers are not comparable.")
            if not recent_runs:
                print(f"  No comparable history at measurement_version="
                      f"{MEASUREMENT_VERSION}. This run establishes the new baseline.")

            if recent_runs:
                print(f"\n--- Regression Check (vs last {len(recent_runs)} run(s)) ---")
                
                # Compute average of recent runs for each metric
                avg_metrics = {}
                for run in recent_runs:
                    for k, v in run.get("metrics", {}).items():
                        if k not in avg_metrics:
                            avg_metrics[k] = []
                        avg_metrics[k].append(v)
                
                for k in avg_metrics:
                    avg_metrics[k] = sum(avg_metrics[k]) / len(avg_metrics[k])
                
                regressions_found = False
                current_metrics = history_record["metrics"]
                for metric_name, current_val in current_metrics.items():
                    if metric_name in avg_metrics:
                        prev_avg = avg_metrics[metric_name]
                        # For hallucination rate, regression means INCREASE; for everything else, regression means DECREASE
                        if metric_name == "hallucination_on_negatives_rate":
                            delta = current_val - prev_avg
                            if delta > regression_threshold:
                                print(f"  REGRESSION: {metric_name} increased by {delta:.4f} (now {current_val:.4f}, was avg {prev_avg:.4f})")
                                regressions_found = True
                            else:
                                print(f"  OK: {metric_name} = {current_val:.4f} (avg was {prev_avg:.4f})")
                        else:
                            delta = prev_avg - current_val
                            if delta > regression_threshold:
                                print(f"  REGRESSION: {metric_name} dropped by {delta:.4f} (now {current_val:.4f}, was avg {prev_avg:.4f})")
                                regressions_found = True
                            else:
                                print(f"  OK: {metric_name} = {current_val:.4f} (avg was {prev_avg:.4f})")
                
                if not regressions_found:
                    print("  No regressions detected.")
    
    with open(history_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(history_record) + "\n")
        
    print(f"\nHistory appended to {history_path}")
    
    # Generate report
    try:
        from eval.report_generator import generate_report
        report = generate_report()
        report_path = os.path.join(results_dir, "evaluation_report.md")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"Report generated: {report_path}")
    except Exception as e:
        print(f"WARN: Could not generate report: {e}")
    
    if passed:
        print("\nSUCCESS: All evaluation gates passed!")
        sys.exit(0)
    else:
        print("\nFAIL: Evaluation thresholds not met.")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the full RAG evaluation suite")
    parser.add_argument(
        "--skip-preflight",
        action="store_true",
        help="bypass the corpus integrity gate (not recommended — scores may "
             "reflect a missing corpus rather than retrieval quality)",
    )
    args = parser.parse_args()
    asyncio.run(run_suite(skip_preflight=args.skip_preflight))

