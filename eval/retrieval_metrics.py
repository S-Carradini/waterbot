import os
import sys
import json
import csv
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
from langchain_openai import OpenAIEmbeddings
from managers.pgvector_store import PgVectorStore


def load_benchmark_dataset() -> List[Dict[str, Any]]:
    dataset_path = os.path.join(_script_dir, "benchmark_dataset.json")
    with open(dataset_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("questions", [])


def calculate_metrics(retrieved_sources: List[str], gold_sources: List[str], k_values: List[int]) -> Dict[str, float]:
    """Calculate Recall@k, Precision@k, and MRR.
    
    Uses set-based matching: if multiple chunks from the same source document
    are retrieved, they count as one hit (not multiple). This ensures recall
    stays in [0, 1] and precision reflects unique document relevance.
    """
    metrics = {}
    gold_set = set(gold_sources)
    
    # If there are no gold sources (e.g., out_of_scope_negative), metrics don't apply
    if not gold_set:
        return metrics

    # Mean Reciprocal Rank (MRR) — first relevant hit position
    mrr = 0.0
    seen_for_mrr = set()
    for i, source in enumerate(retrieved_sources):
        if source in gold_set and source not in seen_for_mrr:
            mrr = 1.0 / (i + 1)
            break
        seen_for_mrr.add(source)
    metrics["mrr"] = mrr

    # Recall@k and Precision@k — deduplicated
    for k in k_values:
        top_k_sources = retrieved_sources[:k]
        # Unique relevant sources in top-k
        unique_relevant = gold_set.intersection(set(top_k_sources))
        
        recall = len(unique_relevant) / len(gold_set)
        precision = len(unique_relevant) / k
        
        metrics[f"recall@{k}"] = recall
        metrics[f"precision@{k}"] = precision

    return metrics


def run_retrieval_evaluation(db_url: str = None) -> None:
    print("START: Starting Retrieval Evaluation...")
    
    db_url = resolve_db_url(db_url)
    print(f"Connecting to vector store at: {db_url[:40]}...")
    embeddings = OpenAIEmbeddings()
    vector_store = PgVectorStore(db_url=db_url, embedding_function=embeddings)

    dataset = load_benchmark_dataset()
    if not dataset:
        print("ERROR: Failed to load benchmark dataset or dataset is empty.")
        sys.exit(1)

    print(f"Loaded {len(dataset)} questions from benchmark dataset.")

    results = []
    k_values = [1, 3, 4, 5, 10]
    
    # Track aggregates
    aggregate_metrics = {f"recall@{k}": 0.0 for k in k_values}
    aggregate_metrics.update({f"precision@{k}": 0.0 for k in k_values})
    aggregate_metrics["mrr"] = 0.0
    valid_questions = 0

    for idx, q_data in enumerate(dataset):
        q_id = q_data["id"]
        question = q_data["question"]
        gold_sources = q_data["gold_source_ids"]
        category = q_data["category"]
        
        print(f"[{idx+1}/{len(dataset)}] Q: {question[:50]}...")
        
        # We search with the maximum k we want to evaluate
        max_k = max(k_values)
        docs = vector_store.similarity_search(question, k=max_k)
        
        # Extract the source name from metadata
        retrieved_sources = []
        for doc in docs:
            # Metadata might contain 'name' (filename) or 'source' (full path)
            meta = getattr(doc, "metadata", {}) or {}
            source_name = meta.get("name")
            if not source_name:
                source_path = meta.get("source", "")
                if source_path:
                    source_name = os.path.basename(source_path)
            
            if source_name:
                retrieved_sources.append(source_name)
        
        # Calculate metrics
        metrics = calculate_metrics(retrieved_sources, gold_sources, k_values)
        
        # Save result row
        row = {
            "id": q_id,
            "category": category,
            "question": question,
            "gold_sources": ", ".join(gold_sources),
            "retrieved_sources": ", ".join(retrieved_sources),
        }
        row.update(metrics)
        results.append(row)

        if metrics:
            valid_questions += 1
            for k in metrics:
                aggregate_metrics[k] += metrics[k]

    # Calculate means
    if valid_questions > 0:
        for k in aggregate_metrics:
            aggregate_metrics[k] /= valid_questions

    # Save to disk
    results_dir = os.path.join(_script_dir, "results")
    os.makedirs(results_dir, exist_ok=True)
    
    csv_path = os.path.join(results_dir, "retrieval_metrics.csv")
    json_path = os.path.join(results_dir, "retrieval_summary.json")

    # Write CSV
    if results:
        fieldnames = ["id", "category", "question", "gold_sources", "retrieved_sources", "mrr"] + \
                     [f"recall@{k}" for k in k_values] + [f"precision@{k}" for k in k_values]
        with open(csv_path, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            for row in results:
                writer.writerow(row)
    
    # Write JSON summary
    summary = {
        "total_questions": len(dataset),
        "valid_questions": valid_questions,
        "aggregate_metrics": aggregate_metrics
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("\nSUCCESS: Retrieval Evaluation Complete!")
    print(f"Results saved to: {csv_path}")
    print(f"Summary saved to: {json_path}")
    print(json.dumps(aggregate_metrics, indent=2))
    
    return summary


if __name__ == "__main__":
    run_retrieval_evaluation()
