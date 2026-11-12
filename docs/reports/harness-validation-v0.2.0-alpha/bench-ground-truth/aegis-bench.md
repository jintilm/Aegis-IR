# Aegis-Bench run report

- Commit: `bab46740cf15edbdadab6b2003c92aeaacb03e67` (dirty: no)
- Platform: Linux-6.18.54.1-microsoft-standard-WSL2-x86_64-with-glibc2.39
- Python: 3.12.3
- Machine: `1a4f52c2f4c7` (salted hash; no host or user name is recorded)
- Runs: 1

Token and tool-call figures are **self-reported by the adapter**; the harness cannot corroborate them.

Tool calls are **measured by the harness-owned broker** for every costed run that used tools; workspace reads, probe executions, disassembly and submissions pass through its policy and budget checks.

Pass/fail, case counts, wall clock and oracle queries are always measured by the harness. Pass rates carry a Wilson 95% interval; cost deltas carry an interval only when both groups have at least two runs. A run row states which budgets were enforced.

- Adapters: `ground-truth-replay builtin-test-double-v1`

- Adapter isolation: `in-process`; 0/1 row(s) record a sandbox

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
| baseline | ground-truth-replay | rolling-token-v2 | 1 | 1/1 | 100% [21%-100%] | 5.30±0.00 | n/a | 0.0 |

## By (agent, profile), across tasks

| agent | profile | tasks | runs | pass | pass rate (95% CI) | wall s (mean±sd) | tokens (self-rep) | oracle queries (total) |
|---|---|---|---|---|---|---|---|---|
| ground-truth-replay | baseline | 1 | 1 | 1/1 | 100% [21%-100%] | 5.30±0.00 | n/a | 0 |

