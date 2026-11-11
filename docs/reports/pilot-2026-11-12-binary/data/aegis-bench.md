# Aegis-Bench run report

- Commit: `cc92049225f0ffa38fd2fd4150b51458273d5f84` (dirty: no)
- Platform: Linux-6.18.54.1-microsoft-standard-WSL2-x86_64-with-glibc2.39
- Python: 3.12.3
- Machine: `1a4f52c2f4c7` (salted hash; no host or user name is recorded)
- Runs: 4

Pass/fail, case counts, wall clock and oracle queries are measured by the harness. Token and tool-call figures are **self-reported by the adapter** and cannot be corroborated. Pass rates carry a Wilson 95% interval; cost deltas carry an interval only when both groups have at least two runs. A run row states which budgets were enforced.

- Adapters: `openai-deepseek-v4-pro d070ac18c0bc`

- Access: `binary`

- Calibration: `packed-record-v1` = floor (deepseek-v4.1-flash, oracle, 0.0, N=3)

**Calibration.** At least one task has no calibrated, measurable baseline for this agent: its unprotected profile is at the floor (never succeeds) or the ceiling (always succeeds), or was never calibrated. A cost delta on such a task cannot demonstrate a protection effect — at the floor there is no headroom, at the ceiling nothing left to slow down. Recalibrate the task before interpreting the deltas below.

A binary-recovery row records an **access mode**. Under `oracle` the workspace holds only a shim and the probe stays with the harness broker, which counts every query and enforces `budgets.oracle_queries` when the manifest sets one. Under `binary` the workspace holds the stripped probe itself, so the agent can execute and disassemble it; queries are then **not counted** (the JSONL says `null`, not `0`). Neither mode is a sandbox: an adapter that reaches the artifact cache directly is not counted either way, and real runs need process isolation. Each row records the probe's SHA-256 and size; its build log is in the JSONL row.

| profile | artifact level | artifact `.text` | sha256 (12) |
|---|---|---|---|
| aegis-level3 | 3 | 6070 | `b4234b74dc75` |
| baseline | 0 | 3922 | `f87131322a7f` |

## By (profile, agent, task)

| profile | agent | task | runs | pass | pass rate (95% CI) | wall s (mean±sd) | tokens (self-rep) | oracle queries (mean) |
|---|---|---|---|---|---|---|---|---|
| aegis-level3 | openai-deepseek-v4-pro | packed-record-v1 | 2 | 2/2 | 100% [34%-100%] | 532.78±4.27 | 822056 | n/a |
| baseline | openai-deepseek-v4-pro | packed-record-v1 | 2 | 2/2 | 100% [34%-100%] | 762.61±9.80 | 431386 | n/a |

## By (agent, profile), across tasks

| agent | profile | tasks | runs | pass | pass rate (95% CI) | wall s (mean±sd) | tokens (self-rep) | oracle queries (total) |
|---|---|---|---|---|---|---|---|---|
| openai-deepseek-v4-pro | aegis-level3 | 1 | 2 | 2/2 | 100% [34%-100%] | 532.78±4.27 | 822056 | n/a |
| openai-deepseek-v4-pro | baseline | 1 | 2 | 2/2 | 100% [34%-100%] | 762.61±9.80 | 431386 | n/a |

## Cost delta vs baseline

Positive means the protected profile cost more. Wall-clock and oracle-query deltas are measured; the token delta is self-reported.

| agent | task | cell | Δ wall s (95% CI) | Δ oracle queries | Δ tokens (self-rep) |
|---|---|---|---|---|---|
| openai-deepseek-v4-pro | packed-record-v1 | baseline → aegis-level3 | -229.83 [-250.77, -208.89] s | n/a | +390669 [+271485, +509853] |

