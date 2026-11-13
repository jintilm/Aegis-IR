# Aegis-Bench run report

- Commit: `92c375e0e99c41187d2c3f27a6a797645bc397d3` (dirty: no)
- Platform: Linux-6.18.54.1-microsoft-standard-WSL2-x86_64-with-glibc2.39
- Python: 3.12.3
- Machine: `1a4f52c2f4c7` (salted hash; no host or user name is recorded)
- Runs: 1

Token and tool-call figures are **self-reported by the adapter**; the harness cannot corroborate them.

Tool calls are **measured by the harness-owned broker** for every costed run that used tools; workspace reads, probe executions, disassembly and submissions pass through its policy and budget checks.

Pass/fail, case counts, wall clock and oracle queries are always measured by the harness. Pass rates carry a Wilson 95% interval; cost deltas carry an interval only when both groups have at least two runs. A run row states which budgets were enforced.

- Adapters: `broker-stub builtin-test-double-v1`

- Campaigns: `process-sandbox-smoke` (harness-validation, manifest `fb15d95536b8`)

- Adapter isolation: `process`; 1/1 row(s) record a sandbox

- Access: `n/a`

## By (profile, agent, task)

| profile | agent | task | runs | pass | pass rate (95% CI) | wall s (mean±sd) | tokens (self-rep) | oracle queries (mean) |
|---|---|---|---|---|---|---|---|---|
| baseline | broker-stub | rolling-token-v1 | 1 | 0/1 | 0% [0%-79%] | 4.12±0.00 | n/a | n/a |

## By (agent, profile), across tasks

| agent | profile | tasks | runs | pass | pass rate (95% CI) | wall s (mean±sd) | tokens (self-rep) | oracle queries (total) |
|---|---|---|---|---|---|---|---|---|
| broker-stub | baseline | 1 | 1 | 0/1 | 0% [0%-79%] | 4.12±0.00 | n/a | n/a |


## Failures

| agent | task | stage | reason |
|---|---|---|---|
| broker-stub | rolling-token-v1 | hidden | 73/73 case(s) failed |
