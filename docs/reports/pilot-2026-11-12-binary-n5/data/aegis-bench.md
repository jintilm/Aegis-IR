# Aegis-Bench run report

- Commit: `2b48dca2fa331d8d5c33f838c190eaa5e1a8ae4a` (dirty: no)
- Platform: Linux-6.18.54.1-microsoft-standard-WSL2-x86_64-with-glibc2.39
- Python: 3.12.3
- Machine: `1a4f52c2f4c7` (salted hash; no host or user name is recorded)
- Runs: 10

Pass/fail, case counts, wall clock and oracle queries are measured by the harness. Token and tool-call figures are **self-reported by the adapter** and cannot be corroborated. Pass rates carry a Wilson 95% interval; cost deltas carry an interval only when both groups have at least two runs. A run row states which budgets were enforced.

- Adapters: `openai-deepseek-v4-pro d070ac18c0bc`

- Access: `binary`

- Calibration: `packed-record-v1` [binary] = ceiling (deepseek-v4-pro, 1.0, N=2)

**Calibration.** At least one task is not `comparison-ready` for this agent and access mode. What that costs the reader depends on which number is being read: at the **floor** (baseline never succeeds) there is no headroom and neither a success nor a cost delta is interpretable; at the **ceiling** (baseline always succeeds) a *success-rate* delta is uninterpretable but a **cost** delta still is, because the success criterion is held fixed across both arms; with no record at all, treat both as descriptive. Recalibrate before citing anything here as an effect.

A binary-recovery row records an **access mode**. Under `oracle` the workspace holds only a shim and the probe stays with the harness broker, which counts every query and enforces `budgets.oracle_queries` when the manifest sets one. Under `binary` the workspace holds the stripped probe itself, so the agent can execute and disassemble it; queries are then **not counted** (the JSONL says `null`, not `0`). Neither mode is a sandbox: an adapter that reaches the artifact cache directly is not counted either way, and real runs need process isolation. Each row records the probe's SHA-256 and size; its build log is in the JSONL row.

| profile | artifact level | artifact `.text` | sha256 (12) |
|---|---|---|---|
| aegis-level3 | 3 | 6070 | `b4234b74dc75` |
| baseline | 0 | 3922 | `f87131322a7f` |

## By (profile, agent, task)

| profile | agent | task | runs | pass | pass rate (95% CI) | wall s (mean±sd) | tokens (self-rep) | oracle queries (mean) |
|---|---|---|---|---|---|---|---|---|
| aegis-level3 | openai-deepseek-v4-pro | packed-record-v1 | 5 | 0/5 | 0% [0%-43%] | 662.84±192.66 | 900452 | n/a |
| baseline | openai-deepseek-v4-pro | packed-record-v1 | 5 | 1/5 | 20% [4%-62%] | 763.07±180.50 | 437030 | n/a |

## By (agent, profile), across tasks

| agent | profile | tasks | runs | pass | pass rate (95% CI) | wall s (mean±sd) | tokens (self-rep) | oracle queries (total) |
|---|---|---|---|---|---|---|---|---|
| openai-deepseek-v4-pro | aegis-level3 | 1 | 5 | 0/5 | 0% [0%-43%] | 662.84±192.66 | 900452 | n/a |
| openai-deepseek-v4-pro | baseline | 1 | 5 | 1/5 | 20% [4%-62%] | 763.07±180.50 | 437030 | n/a |

## Cost delta vs baseline

Positive means the protected profile cost more. Wall-clock and oracle-query deltas are measured; the token delta is self-reported.

| agent | task | cell | Δ wall s (95% CI) | Δ oracle queries | Δ tokens (self-rep) |
|---|---|---|---|---|---|
| openai-deepseek-v4-pro | packed-record-v1 | baseline → aegis-level3 | -100.23 [-358.95, +158.50] s | n/a | +463422 [+382812, +544031] |


## Failures

| agent | task | stage | reason |
|---|---|---|---|
| openai-deepseek-v4-pro | packed-record-v1 | agent | adapter error: model produced no solution (step limit) |
| openai-deepseek-v4-pro | packed-record-v1 | agent | adapter error: path escapes the workspace: /proc/self/maps |
| openai-deepseek-v4-pro | packed-record-v1 | agent | adapter error: model produced no solution (step limit) |
| openai-deepseek-v4-pro | packed-record-v1 | hidden | 74/76 case(s) failed |
| openai-deepseek-v4-pro | packed-record-v1 | hidden | 74/76 case(s) failed |
| openai-deepseek-v4-pro | packed-record-v1 | hidden | 73/76 case(s) failed |
| openai-deepseek-v4-pro | packed-record-v1 | agent | adapter error: model produced no solution (step limit) |
| openai-deepseek-v4-pro | packed-record-v1 | agent | adapter error: model produced no solution (step limit) |
| openai-deepseek-v4-pro | packed-record-v1 | agent | adapter error: model produced no solution (step limit) |
