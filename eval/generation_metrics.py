import os
import sys
import json
import csv
import asyncio
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

try:
    from datasets import Dataset
    from ragas import evaluate
    from ragas.metrics import faithfulness, answer_correctness, context_precision, context_recall
except ImportError:
    print("ERROR: RAGAS or datasets is not installed. Please run: pip install -r eval/requirements-eval.txt")
    sys.exit(1)

from managers.pgvector_store import PgVectorStore
from managers.rag_manager import RAGManager
from adapters.openai import OpenAIAdapter

# Approximate cost per 1K tokens (USD) for common models.
# Update these if pricing changes.
MODEL_COST_PER_1K = {
    "gpt-3.5-turbo": {"prompt": 0.0005, "completion": 0.0015},
    "gpt-4": {"prompt": 0.03, "completion": 0.06},
    "gpt-4-turbo": {"prompt": 0.01, "completion": 0.03},
    "gpt-4o": {"prompt": 0.005, "completion": 0.015},
    "gpt-4.1": {"prompt": 0.002, "completion": 0.008},
}

# Default model to use for evaluation. Override via EVAL_MODEL_ID env var.
DEFAULT_EVAL_MODEL = "gpt-4.1"


def load_benchmark_dataset() -> List[Dict[str, Any]]:
    dataset_path = os.path.join(_script_dir, "benchmark_dataset.json")
    with open(dataset_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("questions", [])


async def judge_hallucination(question: str, answer: str, llm_adapter: OpenAIAdapter) -> bool:
    """
    Use an LLM to determine if the bot hallucinated on an out-of-scope question.
    Returns True if the bot HALLUCINATED (tried to answer), False if it correctly REFUSED.
    """
    judge_prompt = (
        "You are evaluating a chatbot that is only supposed to answer questions about "
        "Arizona water resources and policy. It should refuse to answer out-of-scope questions.\n\n"
        f"User Question: {question}\n\n"
        f"Bot Response: {answer}\n\n"
        "Did the bot correctly refuse to answer (because the question is outside its scope), "
        "or did it attempt to provide a substantive answer?\n\n"
        "Respond with exactly one word: REFUSED or ANSWERED"
    )
    try:
        import asyncio
        response = await asyncio.to_thread(
            llm_adapter.client.chat.completions.create,
            model=llm_adapter.model_id,
            messages=[{"role": "user", "content": judge_prompt}],
            temperature=0.0,
            max_tokens=10,
        )
        verdict = response.choices[0].message.content.strip().upper()
        return "ANSWERED" in verdict
    except Exception:
        # Fallback to keyword matching if LLM judge fails
        return _keyword_hallucination_check(answer)


def _keyword_hallucination_check(answer: str) -> bool:
    """Fallback keyword-based check if LLM judge is unavailable."""
    answer_lower = answer.lower()
    refusal_phrases = [
        "i don't have information",
        "i do not have information",
        "i focus on water",
        "i specialize in water",
        "i can only help with",
        "i don't have access",
        "i cannot predict",
        "i provide information about water",
        "i'm designed to answer",
        "i am designed to answer",
        "i don't provide recommendations",
        "i do not provide recommendations",
        "available at az.gov",
        "outside my area",
        "not able to help with that",
        "falls outside",
        "i'm not equipped",
        "beyond my scope",
    ]
    for phrase in refusal_phrases:
        if phrase in answer_lower:
            return False
    return True


async def run_generation_evaluation(db_url: str = None) -> None:
    # Determine which model to use
    model_id = os.environ.get("EVAL_MODEL_ID", DEFAULT_EVAL_MODEL)
    print(f"START: Starting Generation Evaluation (model={model_id})")
    
    db_url = resolve_db_url(db_url)

    print(f"Connecting to vector store and initializing pipeline...")
    from langchain_openai import OpenAIEmbeddings
    embeddings = OpenAIEmbeddings()
    vector_store = PgVectorStore(db_url=db_url, embedding_function=embeddings)
    rag_manager = RAGManager(vector_store)
    llm_adapter = OpenAIAdapter(model_id=model_id)

    dataset = load_benchmark_dataset()
    if not dataset:
        print("ERROR: Failed to load benchmark dataset or dataset is empty.")
        sys.exit(1)

    print(f"Loaded {len(dataset)} questions from benchmark dataset.")

    questions = []
    answers = []
    contexts = []
    ground_truths = []
    categories = []
    ids = []

    hallucinations_on_negatives = 0
    total_negatives = 0

    # Cost tracking
    total_prompt_tokens = 0
    total_completion_tokens = 0

    for idx, q_data in enumerate(dataset):
        q_id = q_data["id"]
        question = q_data["question"]
        gold_answer = q_data["gold_answer"]
        category = q_data["category"]
        
        print(f"[{idx+1}/{len(dataset)}] Q: {question[:50]}...")
        
        # 1. Retrieval
        retrieval_payload = await rag_manager.ann_search(question, k=4)
        retrieved_docs = retrieval_payload.get("documents", [])
        kb_data = await rag_manager.knowledge_to_string(retrieval_payload)
        
        # 2. Generation
        chat_history = []
        llm_body = await llm_adapter.get_llm_body(
            chat_history=chat_history,
            kb_data=kb_data,
            temperature=0.0,
            endpoint_type="default"
        )
        answer = await llm_adapter.generate_response(llm_body)
        answer = answer.replace("<br>", "\n").replace("</p><p>", "\n\n")

        # Track token usage if the adapter exposes it
        if hasattr(llm_adapter, "last_usage"):
            usage = llm_adapter.last_usage or {}
            total_prompt_tokens += usage.get("prompt_tokens", 0)
            total_completion_tokens += usage.get("completion_tokens", 0)
        
        # Check negative hallucination with LLM judge
        if category == "out_of_scope_negative":
            total_negatives += 1
            hallucinated = await judge_hallucination(question, answer, llm_adapter)
            if hallucinated:
                hallucinations_on_negatives += 1
                print(f"  -> HALLUCINATION detected on {q_id}")

        questions.append(question)
        answers.append(answer)
        contexts.append([doc.page_content for doc in retrieved_docs])
        ground_truths.append(gold_answer)
        categories.append(category)
        ids.append(q_id)

    print("Running RAGAS metrics... this will make calls to OpenAI.")
    data = {
        "question": questions,
        "answer": answers,
        "contexts": contexts,
        "ground_truth": ground_truths
    }
    
    ragas_dataset = Dataset.from_dict(data)
    
    result = evaluate(
        ragas_dataset,
        metrics=[
            faithfulness,
            answer_correctness,
            context_precision,
            context_recall
        ],
    )
    
    ragas_df = result.to_pandas()
    
    results_dir = os.path.join(_script_dir, "results")
    os.makedirs(results_dir, exist_ok=True)
    
    # Add our custom metadata to the dataframe
    ragas_df["id"] = ids
    ragas_df["category"] = categories
    
    csv_path = os.path.join(results_dir, "generation_metrics.csv")
    ragas_df.to_csv(csv_path, index=False)

    hallucination_rate = hallucinations_on_negatives / total_negatives if total_negatives > 0 else 0.0

    # Per-category breakdown from RAGAS results
    by_category = {}
    for cat in set(categories):
        cat_mask = ragas_df["category"] == cat
        cat_df = ragas_df[cat_mask]
        if len(cat_df) > 0:
            cat_summary = {}
            for metric_col in ["faithfulness", "answer_correctness", "context_precision", "context_recall"]:
                if metric_col in cat_df.columns:
                    cat_summary[metric_col] = round(cat_df[metric_col].mean(), 4)
            cat_summary["n"] = int(len(cat_df))
            by_category[cat] = cat_summary

    # Estimate cost
    cost_info = MODEL_COST_PER_1K.get(model_id, {"prompt": 0.0, "completion": 0.0})
    estimated_cost = (
        (total_prompt_tokens / 1000) * cost_info["prompt"] +
        (total_completion_tokens / 1000) * cost_info["completion"]
    )

    serializable_result = {k: float(v) for k, v in result.items()}

    summary = {
        "total_questions": len(dataset),
        "model_id": model_id,
        "metrics": serializable_result,
        "by_category": by_category,
        "hallucination_on_negatives_rate": hallucination_rate,
        "hallucinated_negatives_count": hallucinations_on_negatives,
        "total_negatives_count": total_negatives,
        "cost": {
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
            "estimated_usd": round(estimated_cost, 4)
        }
    }
    
    json_path = os.path.join(results_dir, "generation_summary.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("\nSUCCESS: Generation Evaluation Complete!")
    print(f"Results saved to: {csv_path}")
    print(f"Summary saved to: {json_path}")
    print(f"\n--- Overall (model={model_id}) ---")
    for k, v in serializable_result.items():
        print(f"  {k}: {v:.4f}")
    print(f"  hallucination_on_negatives: {hallucination_rate:.4f} ({hallucinations_on_negatives}/{total_negatives})")
    print(f"\n--- By Category ---")
    for cat, cat_metrics in by_category.items():
        n = cat_metrics.get("n", 0)
        faith = cat_metrics.get("faithfulness", 0)
        correct = cat_metrics.get("answer_correctness", 0)
        print(f"  {cat:25s}  n={n:2d}  faithfulness={faith:.4f}  correctness={correct:.4f}")
    print(f"\n--- Cost ---")
    print(f"  Prompt tokens: {total_prompt_tokens}")
    print(f"  Completion tokens: {total_completion_tokens}")
    print(f"  Estimated cost: ${estimated_cost:.4f}")

    return summary


if __name__ == "__main__":
    asyncio.run(run_generation_evaluation())
