# Aegis-Bench run report

- Commit: `724fb74abd9d0d6eedb37bf0bae7409b610ef23b` (dirty: no)
- Platform: Linux-6.18.54.1-microsoft-standard-WSL2-x86_64-with-glibc2.39
- Python: 3.12.3
- Machine: `1a4f52c2f4c7` (salted hash; no host or user name is recorded)
- Runs: 1

Pass/fail, case counts, wall clock and oracle queries are measured by the harness. Token and tool-call figures are **self-reported by the adapter** and cannot be corroborated. Pass rates carry a Wilson 95% interval; cost deltas carry an interval only when both groups have at least two runs. A run row states which budgets were enforced.

Binary-recovery runs place only an **oracle shim** in the agent workspace; the probe itself stays with the harness broker, which counts every query and enforces `budgets.oracle_queries` when the manifest sets one. This is accounting, not a sandbox: an adapter that reaches the artifact cache directly is not counted. Each row records the probe's SHA-256 and size; its build log is in the JSONL row.

| profile | artifact level | artifact `.text` | sha256 (12) |
|---|---|---|---|
| baseline | 0 | 4334 | `ef0dea649feb` |

## By (profile, agent, task)

| profile | agent | task | runs | pass | pass rate (95% CI) | wall s (mean±sd) | tokens (self-rep) | oracle queries (mean) |
|---|---|---|---|---|---|---|---|---|
| baseline | ground-truth-replay | rolling-token-v2 | 1 | 1/1 | 100% [21%-100%] | 5.51±0.00 | n/a | 0.0 |

## By (agent, profile), across tasks

| agent | profile | tasks | runs | pass | pass rate (95% CI) | wall s (mean±sd) | tokens (self-rep) | oracle queries (total) |
|---|---|---|---|---|---|---|---|---|
| ground-truth-replay | baseline | 1 | 1 | 1/1 | 100% [21%-100%] | 5.51±0.00 | n/a | 0 |

