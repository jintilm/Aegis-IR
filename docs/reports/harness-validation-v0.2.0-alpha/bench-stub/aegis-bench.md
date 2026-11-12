# Aegis-Bench run report

- Commit: `114cd4f4f7e2b31ba17289b791ee087525cbb1d6` (dirty: no)
- Platform: Linux-6.18.54.1-microsoft-standard-WSL2-x86_64-with-glibc2.39
- Python: 3.12.3
- Machine: `1a4f52c2f4c7` (salted hash; no host or user name is recorded)
- Runs: 1

Token and tool-call figures are **self-reported by the adapter**; the harness cannot corroborate them.

Tool calls are **brokered for 0 of 1 runs with a broker block**. Rows with `requests: 0` bypassed the broker and retain the adapter's self-report; do not treat the two as equivalent.

Pass/fail, case counts, wall clock and oracle queries are always measured by the harness. Pass rates carry a Wilson 95% interval; cost deltas carry an interval only when both groups have at least two runs. A run row states which budgets were enforced.

- Adapters: `stub builtin-test-double-v1`

- Access: `oracle`

**Under `oracle` access a protection comparison is structurally zero.** The agent gets a shim whose observable behaviour is identical in every profile; it cannot inspect the artifact, so a transform has nothing to act on. Any level-vs-baseline difference in those rows is noise, and no effectiveness claim may cite them. Protection cost can only be measured under `binary` access.

- Calibration: `rolling-token-v2` [oracle] = uncalibrated

**Calibration.** At least one task is not `comparison-ready` for this agent and access mode. What that costs the reader depends on which number is being read: at the **floor** (baseline never succeeds) there is no headroom and neither a success nor a cost delta is interpretable; at the **ceiling** (baseline always succeeds) a *success-rate* delta is uninterpretable but a **cost** delta still is, because the success criterion is held fixed across both arms; with no record at all, treat both as descriptive. Recalibrate before citing anything here as an effect.

A binary-recovery row records an **access mode**. Under `oracle` the workspace holds only a shim and the probe stays with the harness broker, which counts every query and enforces `budgets.oracle_queries` when the manifest sets one. Under `binary` the workspace holds the stripped probe itself, so the agent can execute and disassemble it; queries are then **not counted** (the JSONL says `null`, not `0`). Neither mode is a sandbox: an adapter that reaches the artifact cache directly is not counted either way, and real runs need process isolation. Each row records the probe's SHA-256 and size; its build log is in the JSONL row.

| profile | artifact level | artifact `.text` | sha256 (12) |
|---|---|---|---|
| baseline | 0 | 4334 | `ef0dea649feb` |

## By (profile, agent, task)

| profile | agent | task | runs | pass | pass rate (95% CI) | wall s (mean±sd) | tokens (self-rep) | oracle queries (mean) |
|---|---|---|---|---|---|---|---|---|
| baseline | stub | rolling-token-v2 | 1 | 0/1 | 0% [0%-79%] | 4.03±0.00 | n/a | 0.0 |

## By (agent, profile), across tasks

| agent | profile | tasks | runs | pass | pass rate (95% CI) | wall s (mean±sd) | tokens (self-rep) | oracle queries (total) |
|---|---|---|---|---|---|---|---|---|
| stub | baseline | 1 | 1 | 0/1 | 0% [0%-79%] | 4.03±0.00 | n/a | 0 |


## Failures

| agent | task | stage | reason |
|---|---|---|---|
| stub | rolling-token-v2 | hidden | 73/73 case(s) failed |
