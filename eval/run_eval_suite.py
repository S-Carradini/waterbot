import os
import sys
import json
import asyncio
import datetime

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

async def run_suite():
    print("START: Starting RAG Evaluation Suite")
    
    db_url = resolve_db_url()
            
    # Load thresholds
    thresholds_path = os.path.join(_script_dir, "thresholds.yaml")
    with open(thresholds_path, "r", encoding="utf-8") as f:
        thresholds = yaml.safe_load(f)
        
    print(f"Loaded Thresholds: {thresholds}")
    
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
        "metrics": {
            "faithfulness": f_score,
            "answer_correctness": ac_score,
            "retrieval_recall_at_4": r_score,
            "hallucination_on_negatives_rate": hallucination_rate
        }
    }
    
    # Regression detection: compare against last N runs
    regression_threshold = 0.05  # Warn if any metric drops by more than 5%
    history_lookback = 3  # Compare against last 3 runs
    
    if os.path.exists(history_path):
        with open(history_path, "r", encoding="utf-8") as f:
            history_lines = f.readlines()
        
        if history_lines:
            recent_runs = []
            for line in history_lines[-history_lookback:]:
                try:
                    recent_runs.append(json.loads(line.strip()))
                except json.JSONDecodeError:
                    continue
            
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
    asyncio.run(run_suite())

