import os
import sys
import json
import csv
import math
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
from eval.corpus_identity import CanonicalResolver, build_resolver
from langchain_openai import OpenAIEmbeddings
from managers.pgvector_store import PgVectorStore


def load_benchmark_dataset(include_excluded: bool = False) -> List[Dict[str, Any]]:
    """Load benchmark questions, skipping quarantined ones by default.

    Questions flagged excluded_from_scoring have no corpus document that
    genuinely sources them. Scoring them would contribute guaranteed zeros to
    every retrieval average — depressing the headline number for a known
    dataset gap rather than for any retrieval failure.
    """
    dataset_path = os.path.join(_script_dir, "benchmark_dataset.json")
    with open(dataset_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    questions = data.get("questions", [])
    if include_excluded:
        return questions
    return [q for q in questions if not q.get("excluded_from_scoring")]


def calculate_metrics(
    retrieved_sources: List[str],
    gold_sources: List[str],
    k_values: List[int],
    retrieved_texts: List[str] = None,
    gold_passage_keywords: List[str] = None,
    resolver: CanonicalResolver = None,
) -> Dict[str, float]:
    """Calculate Recall@k, Precision@k, MRR, NDCG@k, and chunk keyword hit rate.

    Uses set-based matching: if multiple chunks from the same source document
    are retrieved, they count as one hit (not multiple). This ensures recall
    stays in [0, 1] and precision reflects unique document relevance.

    NDCG@k measures ranking quality: it penalizes relevant documents appearing
    lower in the results more than those at the top. This is the industry-standard
    metric used by Google, Bing, and most serious IR systems.

    Chunk keyword matching (optional): if gold_passage_keywords is provided,
    checks whether the expected keywords actually appear in the retrieved chunk
    text, giving passage-level validation instead of just document-level.

    Document identity (`resolver`): both sides are mapped to canonical document
    ids before comparison. The corpus contains the same document under several
    filenames, so a raw string join scored correct retrievals as misses. See
    corpus_identity.py. Passing resolver=None preserves the old raw-name
    behaviour, which the unit tests rely on to pin the metric maths itself.
    """
    metrics = {}

    if resolver is not None:
        gold_sources = resolver.resolve_all(gold_sources)
        # Order and multiplicity must be preserved here: MRR and NDCG are
        # rank-sensitive, so this maps in place rather than deduplicating.
        retrieved_sources = resolver.resolve_all(retrieved_sources)

    gold_set = set(gold_sources)

    # If there are no gold sources (e.g., out_of_scope_negative), metrics don't apply
    if not gold_set:
        return metrics

    # Mean Reciprocal Rank (MRR) -- first relevant hit position
    mrr = 0.0
    seen_for_mrr = set()
    for i, source in enumerate(retrieved_sources):
        if source in gold_set and source not in seen_for_mrr:
            mrr = 1.0 / (i + 1)
            break
        seen_for_mrr.add(source)
    metrics["mrr"] = mrr

    # Recall@k, Precision@k, and NDCG@k
    for k in k_values:
        top_k_sources = retrieved_sources[:k]
        unique_relevant = gold_set.intersection(set(top_k_sources))
        
        recall = len(unique_relevant) / len(gold_set)
        precision = len(unique_relevant) / k
        
        metrics[f"recall@{k}"] = recall
        metrics[f"precision@{k}"] = precision

        # NDCG@k: binary relevance, credited ONCE PER DOCUMENT.
        #
        # Retrieval returns chunks, and several chunks commonly come from the
        # same document. Counting each of them as a separate relevant hit
        # makes DCG exceed the ideal DCG and pushes NDCG above 1.0 — e.g. four
        # chunks of a single gold document scored 2.56. Recall already avoids
        # this by matching on the set of documents; NDCG did not, so the two
        # metrics disagreed about what a "hit" is.
        #
        # Each gold document is therefore credited at the rank where it FIRST
        # appears. That bounds DCG by IDCG (at most min(|gold|, k) distinct
        # gold documents can appear, and the best case puts them in the top
        # positions, which is exactly IDCG), so NDCG lands in [0, 1] again.
        dcg = 0.0
        credited = set()
        for i, source in enumerate(top_k_sources):
            if source in gold_set and source not in credited:
                credited.add(source)
                dcg += 1.0 / math.log2(i + 2)  # i+2 because log2(1) = 0

        # Ideal DCG: all relevant docs at the top
        ideal_relevant = min(len(gold_set), k)
        idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_relevant))

        ndcg = dcg / idcg if idcg > 0 else 0.0
        metrics[f"ndcg@{k}"] = ndcg

    # Chunk-level keyword matching (passage-level validation)
    if gold_passage_keywords and retrieved_texts:
        keywords_found = 0
        for keyword in gold_passage_keywords:
            keyword_lower = keyword.lower()
            for text in retrieved_texts:
                if keyword_lower in text.lower():
                    keywords_found += 1
                    break
        metrics["keyword_hit_rate"] = keywords_found / len(gold_passage_keywords)

    return metrics


def run_retrieval_evaluation(db_url: str = None) -> None:
    print("START: Starting Retrieval Evaluation...")
    
    db_url = resolve_db_url(db_url)
    print(f"Connecting to vector store at: {db_url[:40]}...")
    embeddings = OpenAIEmbeddings()
    vector_store = PgVectorStore(db_url=db_url, embedding_function=embeddings)

    # Canonical document identity — without this, correct retrievals of a
    # document ingested under a different filename score as misses.
    resolver = build_resolver()
    if resolver.group_count:
        print(f"Alias resolution: {resolver.group_count} group(s) active, "
              f"{len(resolver.unverified_groups)} unverified.")
        if resolver.unverified_groups:
            print("  WARN: unverified alias groups affect recall. "
                  "Review eval/aliases.yaml.")

    dataset = load_benchmark_dataset()
    if not dataset:
        print("ERROR: Failed to load benchmark dataset or dataset is empty.")
        sys.exit(1)

    print(f"Loaded {len(dataset)} questions from benchmark dataset.")

    results = []
    k_values = [1, 3, 4, 5, 10]
    
    # Track aggregates (overall and per-category)
    aggregate_metrics = {f"recall@{k}": 0.0 for k in k_values}
    aggregate_metrics.update({f"precision@{k}": 0.0 for k in k_values})
    aggregate_metrics.update({f"ndcg@{k}": 0.0 for k in k_values})
    aggregate_metrics["mrr"] = 0.0
    aggregate_metrics["keyword_hit_rate"] = 0.0
    valid_questions = 0
    keyword_questions = 0

    # Per-category tracking
    category_metrics = {}  # {category: {"totals": {...}, "count": int}}

    for idx, q_data in enumerate(dataset):
        q_id = q_data["id"]
        question = q_data["question"]
        gold_sources = q_data["gold_source_ids"]
        gold_keywords = q_data.get("gold_passage_keywords", [])
        category = q_data["category"]
        
        print(f"[{idx+1}/{len(dataset)}] Q: {question[:50]}...")
        
        # We search with the maximum k we want to evaluate
        max_k = max(k_values)
        docs = vector_store.similarity_search(question, k=max_k)
        
        # Extract the source name and chunk text from metadata
        retrieved_sources = []
        retrieved_texts = []
        for doc in docs:
            meta = getattr(doc, "metadata", {}) or {}
            source_name = meta.get("name")
            if not source_name:
                source_path = meta.get("source", "")
                if source_path:
                    source_name = os.path.basename(source_path)
            
            if source_name:
                retrieved_sources.append(source_name)
            retrieved_texts.append(getattr(doc, "page_content", "") or "")
        
        # Calculate metrics (with optional passage-level keyword matching)
        metrics = calculate_metrics(
            retrieved_sources, gold_sources, k_values,
            retrieved_texts=retrieved_texts,
            gold_passage_keywords=gold_keywords if gold_keywords else None,
            resolver=resolver,
        )
        
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
                if k == "keyword_hit_rate":
                    keyword_questions += 1
                aggregate_metrics[k] = aggregate_metrics.get(k, 0.0) + metrics[k]

            # Accumulate per-category
            if category not in category_metrics:
                category_metrics[category] = {
                    "totals": {m: 0.0 for m in aggregate_metrics},
                    "count": 0,
                    # keyword_hit_rate is only defined for questions that carry
                    # gold_passage_keywords, so it needs its own denominator.
                    # Dividing it by the full category count (the previous
                    # behaviour) silently understated it and made the
                    # per-category figures incomparable with the overall one --
                    # overall reported 0.60 while every category read 0.00-0.25.
                    "keyword_count": 0,
                }
            category_metrics[category]["count"] += 1
            if "keyword_hit_rate" in metrics:
                category_metrics[category]["keyword_count"] += 1
            for k in metrics:
                category_metrics[category]["totals"][k] = category_metrics[category]["totals"].get(k, 0.0) + metrics[k]

    # Calculate overall means
    if valid_questions > 0:
        for k in aggregate_metrics:
            if k == "keyword_hit_rate":
                # Average only over questions that actually had keywords
                aggregate_metrics[k] = aggregate_metrics[k] / keyword_questions if keyword_questions > 0 else 0.0
            else:
                aggregate_metrics[k] /= valid_questions

    # Calculate per-category means
    by_category = {}
    for cat, data in category_metrics.items():
        by_category[cat] = {}
        if data["count"] > 0:
            for m in data["totals"]:
                if m == "keyword_hit_rate":
                    # Average only over questions in this category that had
                    # keywords, matching how the overall figure is computed.
                    denom = data["keyword_count"]
                    if denom == 0:
                        continue  # metric undefined for this category
                    by_category[cat][m] = round(data["totals"][m] / denom, 4)
                else:
                    by_category[cat][m] = round(data["totals"][m] / data["count"], 4)
            by_category[cat]["n"] = data["count"]
            by_category[cat]["n_with_keywords"] = data["keyword_count"]

    # Save to disk
    results_dir = os.path.join(_script_dir, "results")
    os.makedirs(results_dir, exist_ok=True)
    
    csv_path = os.path.join(results_dir, "retrieval_metrics.csv")
    json_path = os.path.join(results_dir, "retrieval_summary.json")

    # Write CSV
    if results:
        fieldnames = ["id", "category", "question", "gold_sources", "retrieved_sources", "mrr", "keyword_hit_rate"] + \
                     [f"recall@{k}" for k in k_values] + [f"precision@{k}" for k in k_values] + \
                     [f"ndcg@{k}" for k in k_values]
        with open(csv_path, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            for row in results:
                writer.writerow(row)
    
    # Write JSON summary
    summary = {
        "total_questions": len(dataset),
        "valid_questions": valid_questions,
        "questions_with_keywords": keyword_questions,
        "aggregate_metrics": aggregate_metrics,
        "by_category": by_category,
        # Provenance: recall is only interpretable against a known corpus and
        # a known alias configuration. Recording them means a score change can
        # be attributed to the retriever rather than to the measurement setup.
        "identity": {
            "alias_groups_active": resolver.group_count,
            "alias_groups_unverified": len(resolver.unverified_groups),
            "all_aliases_verified": len(resolver.unverified_groups) == 0,
        },
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("\nSUCCESS: Retrieval Evaluation Complete!")
    print(f"Results saved to: {csv_path}")
    print(f"Summary saved to: {json_path}")
    print("\n--- Overall ---")
    print(json.dumps(aggregate_metrics, indent=2))
    print("\n--- By Category ---")
    for cat, cat_metrics in by_category.items():
        n = cat_metrics.get("n", 0)
        r4 = cat_metrics.get("recall@4", 0)
        ndcg4 = cat_metrics.get("ndcg@4", 0)
        mrr = cat_metrics.get("mrr", 0)
        print(f"  {cat:25s}  n={n:2d}  recall@4={r4:.4f}  ndcg@4={ndcg4:.4f}  mrr={mrr:.4f}")
    
    return summary


if __name__ == "__main__":
    run_retrieval_evaluation()
