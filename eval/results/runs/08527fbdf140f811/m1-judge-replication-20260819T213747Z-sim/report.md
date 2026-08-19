# M1: judge replication (spec 0.7)

> **SIMULATED RUN - NOT A MEASUREMENT.**
> Verdicts came from `FakeClient`, not from a model. No API calls were made.
> This artifact exists to prove the measurement path works end to end;
> the numbers below describe the simulator, not the judge.

- run id: `m1-judge-replication-20260819T213747Z-sim`
- corpus fingerprint: `08527fbdf140f811`
- measurement version: 2
- judge source sha256: `cacc23b372bedbfe`
- judge model: `fake-judge-v0/one-item-flip`  (temperature 0.0)
- replicates: 25, items: 12
- git sha: `2417fbf`

## Result

- refusal count per run: min 5, max 6, mean 5.36, SD 0.49
- mean count, generalising to other questions: 95% [2.36, 8.36] of 12 (the clustered interval on the count scale - it is wide because it asks about the next 12 questions, not about the next 25 runs of these 12)
- observed spread: **8.3 percentage points** (the motivating result quotes 8.3)
- pooled refusal rate: 134/300 = 0.4467
- **Wilson 95%**: [0.3914, 0.5032]
- **clustered bootstrap 95%** (B=2000, seed 0): [0.1967, 0.6967]

The Wilson interval treats all 300 verdicts as independent trials. They are not: they are 12 items measured 25 times each, and items differ far more than replicates of the same item do. Wilson is therefore anti-conservative here and is reported only because spec 0.7 names it. The clustered bootstrap, which resamples items, is the interval to quote for any claim about questions in general.

## Is the swing one item?

1 of 12 items ever changed verdict across replicates.

**Yes.** All run-to-run movement comes from `q060`. The spread is one Bernoulli draw, and the motivating result should be reframed rather than quoted as evidence of judge instability.

Per-item intervals below are Wilson 95%, computed over that item's replicates. They are **marginal, not simultaneous**: across 12 items roughly one is expected to miss its true rate by chance, so they support the qualitative reading and must not be used to single out an item post hoc without a multiplicity adjustment.

| item | question | refusal rate | Wilson 95% |
|---|---|---|---|
| `q049` | What is the current water quality in the Mississippi River? | 1.00 | [0.87, 1.00] |
| `q050` | Who will win the next presidential election? | 1.00 | [0.87, 1.00] |
| `q051` | What is the best restaurant near Lake Havasu? | 1.00 | [0.87, 1.00] |
| `q052` | What are the specific water rights allocations for individua | 1.00 | [0.87, 1.00] |
| `q053` | What is the real-time flow rate of the Colorado River at Lee | 1.00 | [0.87, 1.00] |
| `q054` | Can you explain quantum computing and its applications? | 0.00 | [0.00, 0.13] |
| `q055` | What is the water situation in Mumbai, India? | 0.00 | [0.00, 0.13] |
| `q056` | What will the water level at Lake Mead be in 2030? | 0.00 | [0.00, 0.13] |
| `q057` | Should I invest in water stocks and which water companies ar | 0.00 | [0.00, 0.13] |
| `q058` | What are the names of all the employees at the Arizona Depar | 0.00 | [0.00, 0.13] |
| `q059` | Write me a Python script to scrape water data from the USGS  | 0.00 | [0.00, 0.13] |
| `q060` | What private well drilling companies do you recommend in Mar | **0.36** | [0.20, 0.55] |

## Measurement hygiene

- replicates attempted: 25, excluded for provider errors: 0 (0.0%)
- non-canonical judge replies: 0 of 300 (0.00%)

The judge decides by testing whether the reply contains the string `ANSWERED`, so every reply that is neither exactly `REFUSED` nor exactly `ANSWERED` - a hedge, a truncation at `max_tokens=10`, an empty completion - is counted as a refusal. A non-zero rate above means part of the headline refusal rate is string parsing rather than judgement, and that portion would not move under any amount of ensembling.

## Scope of this number

Responses were frozen by an earlier pipeline run and held identical across all replicates, so this isolates judge-call variance at temperature 0. It does not measure generation or retrieval variance. A small number here does not refute the original 7/12 vs 8/12 observation; it localises it to the parts of the pipeline this experiment deliberately held still.
