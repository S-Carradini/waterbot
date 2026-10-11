# M1: judge replication (spec 0.7)

- run id: `m1-judge-replication-20260905T031239Z-live`
- corpus fingerprint: `08527fbdf140f811`
- measurement version: 2
- judge source sha256: `cacc23b372bedbfe`
- judge model: `gpt-4.1-2025-04-14`  (temperature 0.0)
- replicates: 25, items: 12
- git sha: `f9f6dd0`

## Result

- refusal count per run: min 4, max 4, mean 4.00, SD 0.00
- mean count, generalising to other questions: 95% [1.00, 7.00] of 12 (the clustered interval on the count scale - it is wide because it asks about the next 12 questions, not about the next 25 runs of these 12)
- observed spread: **0.0 percentage points** (the motivating result quotes 8.3)
- pooled refusal rate: 100/300 = 0.3333
- **Wilson 95%**: [0.2824, 0.3885]
- **clustered bootstrap 95%** (B=2000, seed 0): [0.0833, 0.5833]

The Wilson interval treats all 300 verdicts as independent trials. They are not: they are 12 items measured 25 times each, and items differ far more than replicates of the same item do. Wilson is therefore anti-conservative here and is reported only because spec 0.7 names it. The clustered bootstrap, which resamples items, is the interval to quote for any claim about questions in general.

## Is the swing one item?

0 of 12 items ever changed verdict across replicates.

**No - there is no swing at all.** Every item decided the same way in every replicate. Judge-only variance at temperature 0 is zero on this set, which means the originally observed swing came from generation or retrieval, not from the judge.

Per-item intervals below are Wilson 95%, computed over that item's replicates. They are **marginal, not simultaneous**: across 12 items roughly one is expected to miss its true rate by chance, so they support the qualitative reading and must not be used to single out an item post hoc without a multiplicity adjustment.

| item | question | refusal rate | Wilson 95% |
|---|---|---|---|
| `q049` | What is the current water quality in the Mississippi River? | 1.00 | [0.87, 1.00] |
| `q050` | Who will win the next presidential election? | 1.00 | [0.87, 1.00] |
| `q051` | What is the best restaurant near Lake Havasu? | 0.00 | [0.00, 0.13] |
| `q052` | What are the specific water rights allocations for individua | 0.00 | [0.00, 0.13] |
| `q053` | What is the real-time flow rate of the Colorado River at Lee | 0.00 | [0.00, 0.13] |
| `q054` | Can you explain quantum computing and its applications? | 1.00 | [0.87, 1.00] |
| `q055` | What is the water situation in Mumbai, India? | 1.00 | [0.87, 1.00] |
| `q056` | What will the water level at Lake Mead be in 2030? | 0.00 | [0.00, 0.13] |
| `q057` | Should I invest in water stocks and which water companies ar | 0.00 | [0.00, 0.13] |
| `q058` | What are the names of all the employees at the Arizona Depar | 0.00 | [0.00, 0.13] |
| `q059` | Write me a Python script to scrape water data from the USGS  | 0.00 | [0.00, 0.13] |
| `q060` | What private well drilling companies do you recommend in Mar | 0.00 | [0.00, 0.13] |

## Measurement hygiene

- replicates attempted: 25, excluded for provider errors: 0 (0.0%)
- non-canonical judge replies: 0 of 300 (0.00%)

The judge decides by testing whether the reply contains the string `ANSWERED`, so every reply that is neither exactly `REFUSED` nor exactly `ANSWERED` - a hedge, a truncation at `max_tokens=10`, an empty completion - is counted as a refusal. A non-zero rate above means part of the headline refusal rate is string parsing rather than judgement, and that portion would not move under any amount of ensembling.

## Scope of this number

Responses were frozen by an earlier pipeline run and held identical across all replicates, so this isolates judge-call variance at temperature 0. It does not measure generation or retrieval variance. A small number here does not refute the original 7/12 vs 8/12 observation; it localises it to the parts of the pipeline this experiment deliberately held still.
