# Aegis-Bench run report

- Commit: `448ce541cd2dcd6f48f7298c4bad14b1b9c5c84b` (dirty: no)
- Platform: Linux-6.18.54.1-microsoft-standard-WSL2-x86_64-with-glibc2.39
- Python: 3.12.3
- Machine: `1a4f52c2f4c7` (salted hash; no host or user name is recorded)
- Runs: 6

Pass/fail, case counts, wall clock and oracle queries are measured by the harness. Token and tool-call figures are **self-reported by the adapter** and cannot be corroborated. Pass rates carry a Wilson 95% interval; cost deltas carry an interval only when both groups have at least two runs. A run row states which budgets were enforced.

- Adapters: `openai-deepseek-v4.1-flash b6a6b4fd14e8`

Binary-recovery runs place only an **oracle shim** in the agent workspace; the probe itself stays with the harness broker, which counts every query and enforces `budgets.oracle_queries` when the manifest sets one. This is accounting, not a sandbox: an adapter that reaches the artifact cache directly is not counted. Each row records the probe's SHA-256 and size; its build log is in the JSONL row.

| profile | artifact level | artifact `.text` | sha256 (12) |
|---|---|---|---|
| aegis-level3 | 3 | 6070 | `b4234b74dc75` |
| baseline | 0 | 3922 | `f87131322a7f` |

## By (profile, agent, task)

| profile | agent | task | runs | pass | pass rate (95% CI) | wall s (mean±sd) | tokens (self-rep) | oracle queries (mean) |
|---|---|---|---|---|---|---|---|---|
| aegis-level3 | openai-deepseek-v4.1-flash | packed-record-v1 | 3 | 0/3 | 0% [0%-56%] | 391.09±55.86 | 408054 | 101.0 |
| baseline | openai-deepseek-v4.1-flash | packed-record-v1 | 3 | 0/3 | 0% [0%-56%] | 418.37±43.45 | 348818 | 143.0 |

## By (agent, profile), across tasks

| agent | profile | tasks | runs | pass | pass rate (95% CI) | wall s (mean±sd) | tokens (self-rep) | oracle queries (total) |
|---|---|---|---|---|---|---|---|---|
| openai-deepseek-v4.1-flash | aegis-level3 | 1 | 3 | 0/3 | 0% [0%-56%] | 391.09±55.86 | 408054 | 303 |
| openai-deepseek-v4.1-flash | baseline | 1 | 3 | 0/3 | 0% [0%-56%] | 418.37±43.45 | 348818 | 429 |

## Cost delta vs baseline

Positive means the protected profile cost more. Wall-clock and oracle-query deltas are measured; the token delta is self-reported.

| agent | task | cell | Δ wall s (95% CI) | Δ oracle queries | Δ tokens (self-rep) |
|---|---|---|---|---|---|
| openai-deepseek-v4.1-flash | packed-record-v1 | baseline → aegis-level3 | -27.28 [-125.36, +70.79] s | -42.0 [-139.4, +55.4] | +59236 [-297136, +415609] |


## Failures

| agent | task | stage | reason |
|---|---|---|---|
| openai-deepseek-v4.1-flash | packed-record-v1 | hidden | 74/76 case(s) failed |
| openai-deepseek-v4.1-flash | packed-record-v1 | hidden | 74/76 case(s) failed |
| openai-deepseek-v4.1-flash | packed-record-v1 | agent | adapter error: model produced no solution (step limit) |
| openai-deepseek-v4.1-flash | packed-record-v1 | hidden | 74/76 case(s) failed |
| openai-deepseek-v4.1-flash | packed-record-v1 | agent | adapter error: model produced no solution (step limit) |
| openai-deepseek-v4.1-flash | packed-record-v1 | hidden | 74/76 case(s) failed |
