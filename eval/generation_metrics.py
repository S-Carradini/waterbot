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


def load_benchmark_dataset(include_excluded: bool = False) -> List[Dict[str, Any]]:
    """Load benchmark questions, skipping quarantined ones by default.

    Questions flagged excluded_from_scoring have no corpus document that
    genuinely sources them, so grading an answer against them measures a known
    dataset gap rather than the system. Skipping also avoids paying for LLM
    calls that produce an uninterpretable score.
    """
    dataset_path = os.path.join(_script_dir, "benchmark_dataset.json")
    with open(dataset_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    questions = data.get("questions", [])
    if include_excluded:
        return questions
    return [q for q in questions if not q.get("excluded_from_scoring")]


async def judge_hallucination(
    question: str, answer: str, llm_adapter: OpenAIAdapter
) -> tuple:
    """
    Use an LLM to determine if the bot hallucinated on an out-of-scope question.
    Returns (hallucinated, usage) where hallucinated is True if the bot tried
    to answer, False if it correctly REFUSED.

    Usage is returned so judge calls are included in the run's cost. They were
    previously uncounted, along with all RAGAS grading calls, which made the
    reported spend a small fraction of the real one.
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
        usage = {}
        if getattr(response, "usage", None):
            usage = {
                "prompt_tokens": response.usage.prompt_tokens or 0,
                "completion_tokens": response.usage.completion_tokens or 0,
            }
        return "ANSWERED" in verdict, usage
    except Exception:
        # Fallback to keyword matching if LLM judge fails
        return _keyword_hallucination_check(answer), {}


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

    # Cost tracking, split by which subsystem spent the tokens. The previous
    # single counter only covered pipeline generation and therefore reported a
    # small fraction of the true run cost — RAGAS grading is usually the
    # largest line item.
    cost_buckets = {
        "pipeline": {"prompt_tokens": 0, "completion_tokens": 0},
        "judge": {"prompt_tokens": 0, "completion_tokens": 0},
        "grading": {"prompt_tokens": 0, "completion_tokens": 0},
    }

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
        #
        # CRITICAL: get_llm_body() has no user_query parameter — it builds
        # messages as [system_prompt(kb_data)] + chat_history. The question
        # reaches the model ONLY via chat_history. Production does this by
        # passing the real session history (main.py: get_session_history_all),
        # which already contains the user turn.
        #
        # Passing chat_history=[] here meant the model received a system prompt
        # and NO question at all, so every generation metric was scoring an
        # answer to nothing. Mirror production's message shape instead.
        chat_history = [{"role": "user", "content": question}]
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
            cost_buckets["pipeline"]["prompt_tokens"] += usage.get("prompt_tokens", 0)
            cost_buckets["pipeline"]["completion_tokens"] += usage.get("completion_tokens", 0)

        # Check negative hallucination with LLM judge
        if category == "out_of_scope_negative":
            total_negatives += 1
            hallucinated, judge_usage = await judge_hallucination(question, answer, llm_adapter)
            cost_buckets["judge"]["prompt_tokens"] += judge_usage.get("prompt_tokens", 0)
            cost_buckets["judge"]["completion_tokens"] += judge_usage.get("completion_tokens", 0)
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
    
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    from ragas.llms import LangchainLLMWrapper
    from ragas.embeddings import LangchainEmbeddingsWrapper
    
    eval_llm = LangchainLLMWrapper(ChatOpenAI(model=model_id))
    eval_embeddings = LangchainEmbeddingsWrapper(OpenAIEmbeddings())
    
    # RAGAS grading is normally the dominant cost of a run: four metrics x N
    # questions, each a separate LLM call. Attribute it with a callback handler
    # built on langchain_core.
    #
    # The obvious choice, langchain_community's get_openai_callback, is not
    # usable here: langchain_community.callbacks fails to import against
    # langchain-core >= 1.0 (it reaches for langchain_core.tracers.langchain_v1,
    # which was removed). Since langchain_community is only present as a ragas
    # dependency, relying on it for cost measurement would silently report
    # "not measured" on exactly the setups the suite actually runs on.
    # BaseCallbackHandler is stable core API, so this works across versions.
    grading_tokens = {"prompt_tokens": 0, "completion_tokens": 0}

    try:
        from langchain_core.callbacks.base import BaseCallbackHandler

        class _TokenCounter(BaseCallbackHandler):
            """Accumulate token usage reported by the grading model."""

            def on_llm_end(self, response, **kwargs):
                usage = {}
                # Newer LangChain surfaces usage per-generation; older versions
                # put it in llm_output. Check both so this doesn't go quiet.
                if getattr(response, "llm_output", None):
                    usage = response.llm_output.get("token_usage") or {}
                if not usage:
                    for gen_list in getattr(response, "generations", []) or []:
                        for gen in gen_list:
                            message = getattr(gen, "message", None)
                            meta = getattr(message, "usage_metadata", None) if message else None
                            if meta:
                                grading_tokens["prompt_tokens"] += meta.get("input_tokens", 0)
                                grading_tokens["completion_tokens"] += meta.get("output_tokens", 0)
                    return
                grading_tokens["prompt_tokens"] += usage.get("prompt_tokens", 0)
                grading_tokens["completion_tokens"] += usage.get("completion_tokens", 0)

        token_counter = _TokenCounter()
        eval_llm = LangchainLLMWrapper(ChatOpenAI(model=model_id, callbacks=[token_counter]))
        cost_measurable = True
    except ImportError:
        print("WARN: langchain_core callbacks unavailable — grading cost not measured.")
        cost_measurable = False

    result = evaluate(
        ragas_dataset,
        metrics=[
            faithfulness,
            answer_correctness,
            context_precision,
            context_recall
        ],
        llm=eval_llm,
        embeddings=eval_embeddings,
    )

    if cost_measurable and (grading_tokens["prompt_tokens"] or grading_tokens["completion_tokens"]):
        cost_buckets["grading"] = grading_tokens
    else:
        # Report honestly rather than counting zero as if it were measured.
        if cost_measurable:
            print("WARN: grading token usage was not reported by the model wrapper.")
        cost_buckets["grading"] = None

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

    # Estimate cost per bucket
    cost_info = MODEL_COST_PER_1K.get(model_id, {"prompt": 0.0, "completion": 0.0})

    def _bucket_cost(bucket: dict) -> float:
        return (
            (bucket["prompt_tokens"] / 1000) * cost_info["prompt"] +
            (bucket["completion_tokens"] / 1000) * cost_info["completion"]
        )

    measured = {k: v for k, v in cost_buckets.items() if v is not None}
    total_prompt_tokens = sum(b["prompt_tokens"] for b in measured.values())
    total_completion_tokens = sum(b["completion_tokens"] for b in measured.values())
    estimated_cost = sum(_bucket_cost(b) for b in measured.values())

    # RAGAS aggregates: exclude out_of_scope_negative questions.
    #
    # Negatives have no gold context by construction, so context_precision is
    # 0.0 for every one of them and context_recall is meaningless. Averaging
    # them into the headline dragged all four metrics down and made the gate
    # measure "how many negatives are in the dataset" as much as answer
    # quality. Negatives are scored by the refusal judge instead, which is the
    # metric that actually applies to them.
    NEGATIVE_CATEGORY = "out_of_scope_negative"
    metric_cols = ["faithfulness", "answer_correctness", "context_precision", "context_recall"]
    scored_df = ragas_df[ragas_df["category"] != NEGATIVE_CATEGORY]

    def _means(df) -> dict:
        out = {}
        for col in metric_cols:
            if col in df.columns and len(df) > 0:
                value = df[col].mean()
                if value == value:  # filter NaN
                    out[col] = float(value)
        return out

    serializable_result = _means(scored_df)
    all_questions_result = _means(ragas_df)

    summary = {
        "total_questions": len(dataset),
        "scored_questions": int(len(scored_df)),
        "model_id": model_id,
        # Headline metrics — positives only.
        "metrics": serializable_result,
        # Retained for continuity with historical runs, which averaged over
        # everything. Not comparable to `metrics`.
        "metrics_including_negatives": all_questions_result,
        "negatives_excluded_from_metrics": True,
        "by_category": by_category,
        "hallucination_on_negatives_rate": hallucination_rate,
        "hallucinated_negatives_count": hallucinations_on_negatives,
        "total_negatives_count": total_negatives,
        "cost": {
            "by_bucket": {
                k: {**v, "estimated_usd": round(_bucket_cost(v), 4)}
                for k, v in measured.items()
            },
            "grading_measured": cost_buckets["grading"] is not None,
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
            "estimated_usd": round(estimated_cost, 4),
            # Embedding spend (retrieval queries + RAGAS answer_correctness
            # similarity) is not included; it is small relative to grading but
            # non-zero, so this figure is a close lower bound, not exact.
            "excludes": ["embeddings"],
        }
    }
    
    json_path = os.path.join(results_dir, "generation_summary.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("\nSUCCESS: Generation Evaluation Complete!")
    print(f"Results saved to: {csv_path}")
    print(f"Summary saved to: {json_path}")
    print(f"\n--- Overall (model={model_id}, {len(scored_df)} scored questions, "
          f"{total_negatives} negatives excluded) ---")
    for k, v in serializable_result.items():
        print(f"  {k}: {v:.4f}")
    print(f"  hallucination_on_negatives: {hallucination_rate:.4f} ({hallucinations_on_negatives}/{total_negatives})")
    print(f"\n--- By Category ---")
    for cat, cat_metrics in by_category.items():
        n = cat_metrics.get("n", 0)
        faith = cat_metrics.get("faithfulness", 0)
        correct = cat_metrics.get("answer_correctness", 0)
        marker = "  (judged by refusal rate, not RAGAS)" if cat == NEGATIVE_CATEGORY else ""
        print(f"  {cat:25s}  n={n:2d}  faithfulness={faith:.4f}  correctness={correct:.4f}{marker}")
    print(f"\n--- Cost ---")
    for bucket_name, bucket in measured.items():
        print(f"  {bucket_name:9s}  prompt={bucket['prompt_tokens']:>7,}  "
              f"completion={bucket['completion_tokens']:>6,}  "
              f"${_bucket_cost(bucket):.4f}")
    if cost_buckets["grading"] is None:
        print("  grading    NOT MEASURED (langchain_community unavailable)")
    print(f"  {'TOTAL':9s}  prompt={total_prompt_tokens:>7,}  "
          f"completion={total_completion_tokens:>6,}  ${estimated_cost:.4f}")
    print("  (excludes embedding spend)")

    return summary


if __name__ == "__main__":
    asyncio.run(run_generation_evaluation())
