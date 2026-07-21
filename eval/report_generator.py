"""
Structured report generator for the RAG evaluation suite.
Reads the JSON summaries produced by retrieval_metrics.py and generation_metrics.py,
and generates a single Markdown report with tables and per-category breakdowns.

Usage:
    python eval/report_generator.py
    
    This will read from eval/results/ and produce eval/results/evaluation_report.md
"""
import os
import sys
import json
import datetime

_script_dir = os.path.dirname(os.path.abspath(__file__))
_results_dir = os.path.join(_script_dir, "results")


def load_json(filename: str) -> dict:
    path = os.path.join(_results_dir, filename)
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def format_pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def format_float(value: float) -> str:
    return f"{value:.4f}"


def generate_report() -> str:
    retrieval = load_json("retrieval_summary.json")
    generation = load_json("generation_summary.json")
    
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    lines = []
    lines.append(f"# WaterBot RAG Evaluation Report")
    lines.append(f"")
    lines.append(f"Generated: {timestamp}")
    lines.append(f"")
    
    # Overall summary table
    lines.append("## Overall Performance")
    lines.append("")
    
    if retrieval:
        agg = retrieval.get("aggregate_metrics", {})
        lines.append(f"**Retrieval** ({retrieval.get('valid_questions', 0)} scored questions out of {retrieval.get('total_questions', 0)} total)")
        lines.append("")
        lines.append("| Metric | Score |")
        lines.append("|--------|-------|")
        lines.append(f"| Recall@4 | {format_pct(agg.get('recall@4', 0))} |")
        lines.append(f"| Precision@4 | {format_pct(agg.get('precision@4', 0))} |")
        lines.append(f"| NDCG@4 | {format_float(agg.get('ndcg@4', 0))} |")
        lines.append(f"| MRR | {format_float(agg.get('mrr', 0))} |")
        khr = agg.get("keyword_hit_rate", 0)
        if khr > 0:
            lines.append(f"| Keyword Hit Rate | {format_pct(khr)} |")
        lines.append("")
    
    if generation:
        metrics = generation.get("metrics", {})
        model_id = generation.get("model_id", "unknown")
        lines.append(f"**Generation** (model: {model_id})")
        lines.append("")
        lines.append("| Metric | Score |")
        lines.append("|--------|-------|")
        for k, v in metrics.items():
            lines.append(f"| {k} | {format_float(v)} |")
        hall_rate = generation.get("hallucination_on_negatives_rate", 0)
        hall_count = generation.get("hallucinated_negatives_count", 0)
        hall_total = generation.get("total_negatives_count", 0)
        lines.append(f"| Hallucination on Negatives | {format_pct(hall_rate)} ({hall_count}/{hall_total}) |")
        lines.append("")
        
        # Cost section
        cost = generation.get("cost", {})
        if cost.get("prompt_tokens", 0) > 0:
            lines.append("**Cost**")
            lines.append("")
            lines.append(f"- Prompt tokens: {cost.get('prompt_tokens', 0):,}")
            lines.append(f"- Completion tokens: {cost.get('completion_tokens', 0):,}")
            lines.append(f"- Estimated cost: ${cost.get('estimated_usd', 0):.4f}")
            lines.append("")
    
    # Per-category breakdowns
    lines.append("## Performance by Category")
    lines.append("")
    
    if retrieval and "by_category" in retrieval:
        lines.append("### Retrieval by Category")
        lines.append("")
        lines.append("| Category | n | Recall@4 | NDCG@4 | MRR |")
        lines.append("|----------|---|----------|--------|-----|")
        for cat, data in retrieval["by_category"].items():
            n = data.get("n", 0)
            r4 = format_pct(data.get("recall@4", 0))
            ndcg4 = format_float(data.get("ndcg@4", 0))
            mrr = format_float(data.get("mrr", 0))
            lines.append(f"| {cat} | {n} | {r4} | {ndcg4} | {mrr} |")
        lines.append("")
    
    if generation and "by_category" in generation:
        lines.append("### Generation by Category")
        lines.append("")
        lines.append("| Category | n | Faithfulness | Answer Correctness | Context Precision | Context Recall |")
        lines.append("|----------|---|-------------|-------------------|------------------|---------------|")
        for cat, data in generation["by_category"].items():
            n = data.get("n", 0)
            faith = format_float(data.get("faithfulness", 0))
            correct = format_float(data.get("answer_correctness", 0))
            ctx_prec = format_float(data.get("context_precision", 0))
            ctx_rec = format_float(data.get("context_recall", 0))
            lines.append(f"| {cat} | {n} | {faith} | {correct} | {ctx_prec} | {ctx_rec} |")
        lines.append("")
    
    # Threshold check
    thresholds_path = os.path.join(_script_dir, "thresholds.yaml")
    if os.path.exists(thresholds_path):
        try:
            import yaml
            with open(thresholds_path, "r", encoding="utf-8") as f:
                thresholds = yaml.safe_load(f)
            
            lines.append("## Threshold Gate Results")
            lines.append("")
            lines.append("| Gate | Threshold | Actual | Status |")
            lines.append("|------|-----------|--------|--------|")
            
            checks = []
            if retrieval:
                agg = retrieval.get("aggregate_metrics", {})
                r4 = agg.get("recall@4", 0)
                r4_min = thresholds.get("retrieval_recall_at_4_min", 0)
                status = "PASS" if r4 >= r4_min else "FAIL"
                lines.append(f"| Recall@4 | >= {format_pct(r4_min)} | {format_pct(r4)} | {status} |")
            
            if generation:
                metrics = generation.get("metrics", {})
                f_score = metrics.get("faithfulness", 0)
                f_min = thresholds.get("faithfulness_min", 0)
                status = "PASS" if f_score >= f_min else "FAIL"
                lines.append(f"| Faithfulness | >= {format_float(f_min)} | {format_float(f_score)} | {status} |")
                
                ac_score = metrics.get("answer_correctness", 0)
                ac_min = thresholds.get("answer_correctness_min", 0)
                status = "PASS" if ac_score >= ac_min else "FAIL"
                lines.append(f"| Answer Correctness | >= {format_float(ac_min)} | {format_float(ac_score)} | {status} |")
                
                hall_rate = generation.get("hallucination_on_negatives_rate", 0)
                h_max = thresholds.get("hallucination_on_negatives_max", 1.0)
                status = "PASS" if hall_rate <= h_max else "FAIL"
                lines.append(f"| Hallucination Rate | <= {format_pct(h_max)} | {format_pct(hall_rate)} | {status} |")
            
            lines.append("")
        except ImportError:
            pass
    
    return "\n".join(lines)


if __name__ == "__main__":
    report = generate_report()
    
    output_path = os.path.join(_results_dir, "evaluation_report.md")
    os.makedirs(_results_dir, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)
    
    print(f"Report generated: {output_path}")
    print(report)
