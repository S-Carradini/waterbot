import os
import sys
import json
import asyncio
import pandas as pd
from typing import List, Dict, Any

# Ensure both project root and application are in Python path
_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_script_dir)
_application_dir = os.path.join(_project_root, "application")
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
if _application_dir not in sys.path:
    sys.path.insert(0, _application_dir)

from eval.config import resolve_db_url
from eval.retrieval_metrics import run_retrieval_evaluation
from eval.generation_metrics import run_generation_evaluation

async def run_ablation(configs: List[Dict[str, str]]):
    print("START: Starting Ablation Test Suite")
    print(f"Configurations to test: {[c['name'] for c in configs]}")
    
    results = {}
    
    for config in configs:
        name = config["name"]
        db_url = config.get("db_url")
        
        if not db_url:
            print(f"WARN:  Skipping {name} due to missing DB URL")
            continue
            
        print(f"\n{'='*50}")
        print(f" Running Evaluation for Config: {name}")
        print(f"{'='*50}\n")
        
        try:
            # Run Retrieval Eval
            retrieval_summary = run_retrieval_evaluation(db_url=db_url)
            
            # Run Generation Eval
            generation_summary = await run_generation_evaluation(db_url=db_url)
            
            results[name] = {
                "retrieval": retrieval_summary["aggregate_metrics"],
                "generation": generation_summary["metrics"],
                "hallucination": {
                    "rate": generation_summary["hallucination_on_negatives_rate"],
                    "count": generation_summary["hallucinated_negatives_count"]
                }
            }
        except Exception as e:
            print(f"ERROR: Error evaluating config {name}: {e}")
            
    # Save raw results
    results_dir = os.path.join(_script_dir, "results")
    os.makedirs(results_dir, exist_ok=True)
    json_path = os.path.join(results_dir, "ablation_results.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
        
    # Generate Markdown Table Comparison
    if len(results) > 0:
        md_path = os.path.join(results_dir, "ablation_comparison.md")
        
        # Flatten metrics for pandas
        flat_results = []
        for name, data in results.items():
            row = {"Config": name}
            
            # Retrieval metrics
            for k, v in data["retrieval"].items():
                row[f"Retrieval {k}"] = round(v, 4)
                
            # Generation metrics
            for k, v in data["generation"].items():
                row[f"RAGAS {k}"] = round(v, 4)
                
            row["Hallucination Rate"] = round(data["hallucination"]["rate"], 4)
            flat_results.append(row)
            
        df = pd.DataFrame(flat_results)
        
        with open(md_path, "w", encoding="utf-8") as f:
            f.write("# Ablation Test Comparison\n\n")
            f.write(df.to_markdown(index=False))
            
        print(f"\nSUCCESS: Ablation Test Complete!")
        print(f"Results saved to: {json_path}")
        print(f"Comparison table saved to: {md_path}")
        print("\n" + df.to_markdown(index=False))

if __name__ == "__main__":
    # Expects OLD_CORPUS_DB_URL and NEW_CORPUS_DB_URL in environment or .env
    old_db = os.environ.get("OLD_CORPUS_DB_URL")
    new_db = os.environ.get("NEW_CORPUS_DB_URL")
    
    # Fallback to DATABASE_URL if explicitly set for one config
    if not new_db:
        new_db = os.environ.get("DATABASE_URL")
        
    configs = []
    if old_db:
        configs.append({"name": "pgvector_old_corpus", "db_url": old_db})
    if new_db:
        configs.append({"name": "pgvector_new_corpus", "db_url": new_db})
        
    if not configs:
        print("ERROR: No database URLs provided. Set OLD_CORPUS_DB_URL and/or NEW_CORPUS_DB_URL.")
        sys.exit(1)
        
    asyncio.run(run_ablation(configs))
