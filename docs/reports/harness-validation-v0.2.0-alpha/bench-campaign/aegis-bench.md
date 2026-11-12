# Aegis-Bench run report

- Commit: `114cd4f4f7e2b31ba17289b791ee087525cbb1d6` (dirty: no)
- Platform: Linux-6.18.54.1-microsoft-standard-WSL2-x86_64-with-glibc2.39
- Python: 3.12.3
- Machine: `1a4f52c2f4c7` (salted hash; no host or user name is recorded)
- Runs: 1

Token and tool-call figures are **self-reported by the adapter**; the harness cannot corroborate them.

Tool calls are **measured by the harness-owned broker** for every costed run that used tools; workspace reads, probe executions, disassembly and submissions pass through its policy and budget checks.

Pass/fail, case counts, wall clock and oracle queries are always measured by the harness. Pass rates carry a Wilson 95% interval; cost deltas carry an interval only when both groups have at least two runs. A run row states which budgets were enforced.

- Adapters: `ground-truth-replay builtin-test-double-v1`

- Campaigns: `offline-harness-smoke` (harness-validation, manifest `bb5b4148a7ff`)

- Access: `n/a`

## By (profile, agent, task)

| profile | agent | task | runs | pass | pass rate (95% CI) | wall s (mean±sd) | tokens (self-rep) | oracle queries (mean) |
|---|---|---|---|---|---|---|---|---|
| baseline | ground-truth-replay | rolling-token-v1 | 1 | 1/1 | 100% [21%-100%] | 3.85±0.00 | n/a | n/a |

## By (agent, profile), across tasks

| agent | profile | tasks | runs | pass | pass rate (95% CI) | wall s (mean±sd) | tokens (self-rep) | oracle queries (total) |
|---|---|---|---|---|---|---|---|---|
| ground-truth-replay | baseline | 1 | 1 | 1/1 | 100% [21%-100%] | 3.85±0.00 | n/a | n/a |

