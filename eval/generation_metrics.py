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


def load_benchmark_dataset() -> List[Dict[str, Any]]:
    dataset_path = os.path.join(_script_dir, "benchmark_dataset.json")
    with open(dataset_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("questions", [])


def check_hallucination_on_negative(answer: str) -> bool:
    """
    Check if the model hallucinated on a negative query (i.e. answered it instead of refusing).
    Returns True if it HALLUCINATED, False if it correctly REFUSED.
    """
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
        "available at az.gov"
    ]
    # If any refusal phrase is in the answer, we assume it correctly refused (did not hallucinate)
    for phrase in refusal_phrases:
        if phrase in answer_lower:
            return False
    # If no refusal phrase is found, it probably hallucinated an answer
    return True


async def run_generation_evaluation(db_url: str = None) -> None:
    print("START: Starting Generation Evaluation (with RAGAS)...")
    
    db_url = resolve_db_url(db_url)

    print(f"Connecting to vector store and initializing pipeline...")
    # The production system uses OpenAIEmbeddings and gpt-4.1
    # Note: If gpt-4.1 is not a valid OpenAI model name on your account, change to gpt-4 or gpt-4-turbo
    from langchain_openai import OpenAIEmbeddings
    embeddings = OpenAIEmbeddings()
    vector_store = PgVectorStore(db_url=db_url, embedding_function=embeddings)
    rag_manager = RAGManager(vector_store)
    
    # We use gpt-3.5-turbo here to match standard fallback if gpt-4.1 fails, 
    # but we can use whatever ADAPTERS uses. In main.py it uses "gpt-4.1". 
    # Usually OpenAI models are "gpt-4" or "gpt-4o". We will stick to the adapter class defaults.
    llm_adapter = OpenAIAdapter(model_id="gpt-3.5-turbo") # safe fallback

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
        chat_history = []  # No history for this benchmark
        llm_body = await llm_adapter.get_llm_body(
            chat_history=chat_history,
            kb_data=kb_data,
            temperature=0.0, # Zero temp for reproducible eval
            endpoint_type="default"
        )
        answer = await llm_adapter.generate_response(llm_body)
        # Strip the HTML breaks the bot adds for UI
        answer = answer.replace("<br>", "\n").replace("</p><p>", "\n\n")
        
        # Check negative hallucination manually
        if category == "out_of_scope_negative":
            total_negatives += 1
            if check_hallucination_on_negative(answer):
                hallucinations_on_negatives += 1

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
    
    # Add our custom metadata to the dataframe to save out
    ragas_df["id"] = ids
    ragas_df["category"] = categories
    
    csv_path = os.path.join(results_dir, "generation_metrics.csv")
    ragas_df.to_csv(csv_path, index=False)

    hallucination_rate = hallucinations_on_negatives / total_negatives if total_negatives > 0 else 0.0

    summary = {
        "total_questions": len(dataset),
        "metrics": result,
        "hallucination_on_negatives_rate": hallucination_rate,
        "hallucinated_negatives_count": hallucinations_on_negatives,
        "total_negatives_count": total_negatives
    }
    
    json_path = os.path.join(results_dir, "generation_summary.json")
    with open(json_path, "w", encoding="utf-8") as f:
        # Convert RAGAS result (which is a dict-like object) to standard dict
        serializable_result = {k: float(v) for k, v in result.items()}
        json.dump({
            "total_questions": len(dataset),
            "metrics": serializable_result,
            "hallucination_on_negatives_rate": hallucination_rate,
            "hallucinated_negatives_count": hallucinations_on_negatives,
            "total_negatives_count": total_negatives
        }, f, indent=2)

    print("\nSUCCESS: Generation Evaluation Complete!")
    print(f"Results saved to: {csv_path}")
    print(f"Summary saved to: {json_path}")
    print("\n--- Summary Metrics ---")
    for k, v in summary["metrics"].items():
        print(f"{k}: {v:.4f}")
    print(f"Hallucination on Negatives Rate: {hallucination_rate:.4f} ({hallucinations_on_negatives}/{total_negatives})")

    return summary


if __name__ == "__main__":
    asyncio.run(run_generation_evaluation())
