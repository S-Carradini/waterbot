import os
import sys
import json
import asyncio
import time
import random
import statistics
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


from langchain_openai import OpenAIEmbeddings
from managers.pgvector_store import PgVectorStore
from adapters.openai import OpenAIAdapter

def load_benchmark_dataset() -> List[str]:
    dataset_path = os.path.join(_script_dir, "benchmark_dataset.json")
    with open(dataset_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [q["question"] for q in data.get("questions", []) if q["category"] != "out_of_scope_negative"]

async def simulate_user(user_id: int, queries: List[str], vector_store: PgVectorStore, llm_adapter: OpenAIAdapter, num_iterations: int) -> List[Dict[str, float]]:
    metrics = []
    
    for i in range(num_iterations):
        query = random.choice(queries)
        
        t0 = time.perf_counter()
        
        # 1. Embedding
        query_embedding = vector_store.embedding_function.embed_query(query)
        t_embed = time.perf_counter()
        
        # 2. Vector Search (Simulating pgvector internal call using the pre-computed embedding)
        # We call the internal PG logic. Since similarity_search does embedding internally,
        # we will measure the whole similarity_search and subtract embed time for approx search time.
        t2 = time.perf_counter()
        docs = vector_store.similarity_search(query, k=4)
        t_search_total = time.perf_counter()
        t_search = t_search_total - t2
        
        # 3. LLM Generation
        kb_data = "\n\n".join([d.page_content for d in docs])
        llm_body = await llm_adapter.get_llm_body(
            chat_history=[],
            kb_data=kb_data,
            temperature=0.0,
            endpoint_type="default"
        )
        
        t3 = time.perf_counter()
        answer = await llm_adapter.generate_response(llm_body)
        t_llm = time.perf_counter()
        
        t_total = t_llm - t0
        
        metrics.append({
            "user_id": user_id,
            "iteration": i,
            "embed_ms": (t_embed - t0) * 1000,
            "search_ms": t_search * 1000,
            "llm_ms": (t_llm - t3) * 1000,
            "total_ms": t_total * 1000,
            "success": bool(answer)
        })
        
        # Small delay between iterations
        await asyncio.sleep(random.uniform(0.1, 0.5))
        
    return metrics

async def run_load_test(concurrent_users: int = 50, iterations_per_user: int = 3):
    print(f"️START: Starting Pipeline Load Test")
    print(f"Users: {concurrent_users} | Iterations/User: {iterations_per_user} | Total Requests: {concurrent_users * iterations_per_user}")
    
    db_url = resolve_db_url()
        
    embeddings = OpenAIEmbeddings()
    vector_store = PgVectorStore(db_url=db_url, embedding_function=embeddings)
    llm_adapter = OpenAIAdapter(model_id="gpt-3.5-turbo") # Use faster model for load test
    
    queries = load_benchmark_dataset()
    if not queries:
        print("ERROR: Could not load benchmark queries")
        sys.exit(1)
        
    print(f"Initializing {concurrent_users} concurrent async tasks...")
    
    tasks = []
    for user_id in range(concurrent_users):
        tasks.append(simulate_user(user_id, queries, vector_store, llm_adapter, iterations_per_user))
        
    start_time = time.perf_counter()
    results = await asyncio.gather(*tasks)
    end_time = time.perf_counter()
    
    print(f"Test completed in {(end_time - start_time):.2f} seconds")
    
    # Flatten results
    flat_metrics = []
    for user_results in results:
        flat_metrics.extend(user_results)
        
    # Compute Statistics
    df = pd.DataFrame(flat_metrics)
    
    stats = []
    for metric in ["embed_ms", "search_ms", "llm_ms", "total_ms"]:
        data = df[metric].tolist()
        stats.append({
            "Metric": metric.replace("_ms", " (ms)"),
            "Mean": round(statistics.mean(data), 2),
            "P50 (Median)": round(statistics.median(data), 2),
            "P95": round(statistics.quantiles(data, n=100)[94], 2),
            "P99": round(statistics.quantiles(data, n=100)[98], 2),
            "Max": round(max(data), 2)
        })
        
    stats_df = pd.DataFrame(stats)
    
    results_dir = os.path.join(_script_dir, "results")
    os.makedirs(results_dir, exist_ok=True)
    
    md_path = os.path.join(results_dir, "load_test_results.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# Load Test Results\n\n")
        f.write(f"**Concurrency**: {concurrent_users} users\n")
        f.write(f"**Total Requests**: {concurrent_users * iterations_per_user}\n\n")
        f.write(stats_df.to_markdown(index=False))
        
    print("\nSUCCESS: Load Test Complete!")
    print(stats_df.to_markdown(index=False))
    print(f"\nResults saved to {md_path}")

if __name__ == "__main__":
    users = 50
    if len(sys.argv) > 1:
        users = int(sys.argv[1])
        
    asyncio.run(run_load_test(concurrent_users=users))
