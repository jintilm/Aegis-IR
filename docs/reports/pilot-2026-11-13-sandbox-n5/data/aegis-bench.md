# Aegis-Bench run report

- Commit: `07cfecf45eac90f5b034d9c8365cba2fc9050e8f` (dirty: no)
- Platform: Linux-6.18.54.1-microsoft-standard-WSL2-x86_64-with-glibc2.39
- Python: 3.12.3
- Machine: `1a4f52c2f4c7` (salted hash; no host or user name is recorded)
- Runs: 10

Token figures are **measured**: each run went through a harness-owned metering proxy and the totals are the provider's own `usage` report. Tool-call figures remain self-reported by the adapter.

Tool calls are **measured by the harness-owned broker** for every costed run that used tools; workspace reads, probe executions, disassembly and submissions pass through its policy and budget checks.

Pass/fail, case counts, wall clock and oracle queries are always measured by the harness. Pass rates carry a Wilson 95% interval; cost deltas carry an interval only when both groups have at least two runs. A run row states which budgets were enforced.

- Adapters: `openai-deepseek-v4-pro 3cfa0466724c`

- Campaigns: `pilot-pilot-2026-11-13-sandbox-n5` (pilot, manifest `a4c5be805dba`)

- Adapter isolation: `process`; 10/10 row(s) record a sandbox

- Access: `binary`

- Calibration: `packed-record-v1` [binary] = comparison-ready (deepseek-v4-pro, 0.25, N=12)

A binary-recovery row records an **access mode**. Under `oracle` the workspace holds only a shim and the probe stays with the harness broker, which counts every query and enforces `budgets.oracle_queries` when the manifest sets one. Under `binary` the workspace holds the stripped probe itself, so the agent can execute and disassemble it; queries are then **not counted** (the JSONL says `null`, not `0`). Neither mode is a sandbox: an adapter that reaches the artifact cache directly is not counted either way, and real runs need process isolation. Each row records the probe's SHA-256 and size; its build log is in the JSONL row.

| profile | artifact level | artifact `.text` | sha256 (12) |
|---|---|---|---|
| aegis-level3 | 3 | 6070 | `b4234b74dc75` |
| baseline | 0 | 3922 | `f87131322a7f` |

## By (profile, agent, task)

| profile | agent | task | runs | pass | pass rate (95% CI) | wall s (mean±sd) | tokens (metered) | oracle queries (mean) |
|---|---|---|---|---|---|---|---|---|
| aegis-level3 | openai-deepseek-v4-pro | packed-record-v1 | 5 | 0/5 | 0% [0%-43%] | 607.55±74.41 | 506361 | n/a |
| baseline | openai-deepseek-v4-pro | packed-record-v1 | 5 | 0/5 | 0% [0%-43%] | 683.26±68.64 | 301468 | n/a |

## By (agent, profile), across tasks

| agent | profile | tasks | runs | pass | pass rate (95% CI) | wall s (mean±sd) | tokens (metered) | oracle queries (total) |
|---|---|---|---|---|---|---|---|---|
| openai-deepseek-v4-pro | aegis-level3 | 1 | 5 | 0/5 | 0% [0%-43%] | 607.55±74.41 | 506361 | n/a |
| openai-deepseek-v4-pro | baseline | 1 | 5 | 0/5 | 0% [0%-43%] | 683.26±68.64 | 301468 | n/a |

## Cost delta vs baseline

Positive means the protected profile cost more. Wall-clock and oracle-query deltas and the token delta come from the provider's own usage report, captured by the harness metering proxy.

| agent | task | cell | Δ wall s (95% CI) | Δ oracle queries | Δ tokens (metered) |
|---|---|---|---|---|---|
| openai-deepseek-v4-pro | packed-record-v1 | baseline → aegis-level3 | -75.71 [-174.91, +23.50] s | n/a | +204893 [+3668, +406117] |


## Failures

| agent | task | stage | reason |
|---|---|---|---|
| openai-deepseek-v4-pro | packed-record-v1 | hidden | 76/76 case(s) failed |
| openai-deepseek-v4-pro | packed-record-v1 | hidden | 76/76 case(s) failed |
| openai-deepseek-v4-pro | packed-record-v1 | hidden | 76/76 case(s) failed |
| openai-deepseek-v4-pro | packed-record-v1 | hidden | 76/76 case(s) failed |
| openai-deepseek-v4-pro | packed-record-v1 | hidden | 76/76 case(s) failed |
| openai-deepseek-v4-pro | packed-record-v1 | hidden | 76/76 case(s) failed |
| openai-deepseek-v4-pro | packed-record-v1 | hidden | 76/76 case(s) failed |
| openai-deepseek-v4-pro | packed-record-v1 | hidden | 76/76 case(s) failed |
| openai-deepseek-v4-pro | packed-record-v1 | hidden | 76/76 case(s) failed |
| openai-deepseek-v4-pro | packed-record-v1 | hidden | 76/76 case(s) failed |
