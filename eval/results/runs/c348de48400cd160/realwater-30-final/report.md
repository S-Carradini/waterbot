# Judge panel report - realwater-30-final

## Scores

Every number carries a clustered bootstrap interval that resamples ITEMS, because the
benchmark is a sample of questions. Abstention counts are reported beside each score:
the interval is computed over the samples that scored.

| Dimension | Items | Mean | 95% interval | Abstentions |
|---|---|---|---|---|
| `citation_validity` | 25 | 2.66 | [2.46, 2.86] | 3 |
| `correctness` | 17 | 2.76 | [2.47, 3.09] | 14 |
| `grounding` | 25 | 2.10 | [1.88, 2.36] | 3 |
| `refusal_appropriateness` | 30 | 3.22 | [2.88, 3.50] | 3 |

## What this panel is, stated plainly

**The judge panel is three generations of ONE AI company's models, not three different
companies.** The three judges are `gpt-5.4-2026-03-05`, `gpt-5.2-2025-12-11` and
`gpt-4.1-2025-04-14`, all from OpenAI.

This matters and is not a technicality. The reason a panel is used at all is error
decorrelation: independent judges make independent mistakes, so their agreement carries
information. Models from one vendor share training data, post-training method, tokenizer
and failure modes. Their errors are correlated, so agreement between them is weaker
evidence than agreement between genuinely independent judges would be. Every claim in
this report that rests on panel agreement should be read with that discount applied.

## Limitations

1. The judge panel is three generations of ONE company's models (OpenAI), NOT three different companies. M7 specifies 3+ model families because its mechanism is error decorrelation; models from one vendor share training data, post-training method, tokenizer and failure modes, so their errors are correlated. A panel that agrees may be agreeing because it is three views of one system. This is a constraint of the project's available credentials, not an oversight. Adding a second provider family is future work.

2. The self-preference analysis (whether a judge favours its own family's output) cannot be run at all with a single-vendor panel. Future work.

3. Dollar figures rest on an ASSUMED price table that has never been verified against published rates. Token counts are measured; the conversion to dollars is not audited.

4. The system under test is nondeterministic and the judge is not. At temperature 0, with retrieved passages held identical, 11 of 12 negative items produced different answers across 25 runs (up to 17 distinct answers). The judge, by contrast, was perfectly stable (SD 0.00 over 25 replicates). Scores here are of ONE frozen answer per item, not of the distribution of answers the system would produce.

5. The original 8.3-point instability is attributed to generation but not quantitatively closed. One item of twelve flipping equals 8.3 points exactly, which is consistent with the measured generation variance, but the link was not measured end to end. Future work.

6. Panel abstention is not perfectly stable: pooled 3/100 (Wilson 95% [0.010, 0.085]) at k=20, concentrated on one item which also varied in score. Every spread statistic here is computed over the samples that scored, so abstention counts are reported alongside.

7. The gold set is 30 items, and one of its five topic categories contains a single item. This supports overall figures only, not per-category claims. Expanding the benchmark and recruiting additional expert annotators is future work.

8. The rubric pilot established inter-annotator agreement on two people over 12 items (28 scored units), Cohen's kappa 0.839 quadratic-weighted. Two annotators is the minimum for the statistic and a larger annotator pool is future work.

9. citation_validity and temporal_integrity are defined in the rubric but were never exercised: the answers carry no inline citations and the gold set contains no time-sensitive items.

10. The document corpus is knowingly incomplete, its currency is unknown, and 127 of 370 document names share content with another name. Corpus repair is deliberately out of scope.

11. No ablation grid was run. The full grid as specified is 3,456 configurations and roughly $1,120; sizing and slicing it is future work.
