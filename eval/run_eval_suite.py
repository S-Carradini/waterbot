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
        
    # 4. Append to history
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
    
    with open(history_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(history_record) + "\n")
        
    print(f"\nHistory appended to {history_path}")
    
    if passed:
        print("\n All evaluation gates passed!")
        sys.exit(0)
    else:
        print("\n Evaluation Failed! Thresholds not met.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run_suite())
