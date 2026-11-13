# Aegis-Bench run report

- Commit: `7b2ba67e935827a905ca56ba91af501bd955e295` (dirty: no)
- Platform: Linux-6.18.54.1-microsoft-standard-WSL2-x86_64-with-glibc2.39
- Python: 3.12.3
- Machine: `1a4f52c2f4c7` (salted hash; no host or user name is recorded)
- Runs: 20

Token figures are **measured**: each run went through a harness-owned metering proxy and the totals are the provider's own `usage` report. Tool-call figures remain self-reported by the adapter.

Tool calls are **measured by the harness-owned broker** for every costed run that used tools; workspace reads, probe executions, disassembly and submissions pass through its policy and budget checks.

Pass/fail, case counts, wall clock and oracle queries are always measured by the harness. Pass rates carry a Wilson 95% interval; cost deltas carry an interval only when both groups have at least two runs. A run row states which budgets were enforced.

- Adapters: `openai-deepseek-flash 3cfa0466724c model=deepseek-flash`, `openai-deepseek-v4-pro 3cfa0466724c model=deepseek-v4-pro`

- Campaigns: `pilot-2026-11-13-dual-model-n5` (pilot, manifest `5d67718b0ba2`)

- Adapter isolation: `process`; 20/20 row(s) record a sandbox

- Access: `binary`

- Calibration: `packed-record-v1` [binary] = uncalibrated (deepseek-flash, None); `packed-record-v1` [binary] = comparison-ready (deepseek-v4-pro, 0.25, N=12)

**Calibration.** At least one task is not `comparison-ready` for this agent and access mode. What that costs the reader depends on which number is being read: at the **floor** (baseline never succeeds) there is no headroom and neither a success nor a cost delta is interpretable; at the **ceiling** (baseline always succeeds) a *success-rate* delta is uninterpretable but a **cost** delta still is, because the success criterion is held fixed across both arms; with no record at all, treat both as descriptive. Recalibrate before citing anything here as an effect.

A binary-recovery row records an **access mode**. Under `oracle` the workspace holds only a shim and the probe stays with the harness broker, which counts every query and enforces `budgets.oracle_queries` when the manifest sets one. Under `binary` the workspace holds the stripped probe itself, so the agent can execute and disassemble it; queries are then **not counted** (the JSONL says `null`, not `0`). Neither mode is a sandbox: an adapter that reaches the artifact cache directly is not counted either way, and real runs need process isolation. Each row records the probe's SHA-256 and size; its build log is in the JSONL row.

| profile | artifact level | artifact `.text` | sha256 (12) |
|---|---|---|---|
| aegis-level3 | 3 | 6070 | `b4234b74dc75` |
| baseline | 0 | 3922 | `f87131322a7f` |

## By (profile, agent, task)

| profile | agent | task | runs | pass | pass rate (95% CI) | wall s (mean±sd) | tokens (metered) | oracle queries (mean) |
|---|---|---|---|---|---|---|---|---|
| aegis-level3 | openai-deepseek-flash | packed-record-v1 | 5 | 0/5 | 0% [0%-43%] | 583.21±131.33 | 636195 | n/a |
| aegis-level3 | openai-deepseek-v4-pro | packed-record-v1 | 5 | 1/5 | 20% [4%-62%] | 635.18±145.81 | 909318 | n/a |
| baseline | openai-deepseek-flash | packed-record-v1 | 5 | 2/5 | 40% [12%-77%] | 661.52±81.83 | 210224 | n/a |
| baseline | openai-deepseek-v4-pro | packed-record-v1 | 5 | 2/5 | 40% [12%-77%] | 728.84±182.05 | 422646 | n/a |

## By (agent, profile), across tasks

| agent | profile | tasks | runs | pass | pass rate (95% CI) | wall s (mean±sd) | tokens (metered) | oracle queries (total) |
|---|---|---|---|---|---|---|---|---|
| openai-deepseek-flash | aegis-level3 | 1 | 5 | 0/5 | 0% [0%-43%] | 583.21±131.33 | 636195 | n/a |
| openai-deepseek-flash | baseline | 1 | 5 | 2/5 | 40% [12%-77%] | 661.52±81.83 | 210224 | n/a |
| openai-deepseek-v4-pro | aegis-level3 | 1 | 5 | 1/5 | 20% [4%-62%] | 635.18±145.81 | 909318 | n/a |
| openai-deepseek-v4-pro | baseline | 1 | 5 | 2/5 | 40% [12%-77%] | 728.84±182.05 | 422646 | n/a |

## Cost delta vs baseline

Positive means the protected profile cost more. Wall-clock and oracle-query deltas and the token delta come from the provider's own usage report, captured by the harness metering proxy.

| agent | task | cell | Δ wall s (95% CI) | Δ oracle queries | Δ tokens (metered) |
|---|---|---|---|---|---|
| openai-deepseek-flash | packed-record-v1 | baseline → aegis-level3 | -78.31 [-229.95, +73.33] s | n/a | +425971 [+220499, +631442] |
| openai-deepseek-v4-pro | packed-record-v1 | baseline → aegis-level3 | -93.66 [-322.24, +134.92] s | n/a | +486672 [+308527, +664818] |


## Failures

| agent | task | stage | reason |
|---|---|---|---|
| openai-deepseek-flash | packed-record-v1 | hidden | 73/76 case(s) failed |
| openai-deepseek-v4-pro | packed-record-v1 | hidden | 74/76 case(s) failed |
| openai-deepseek-v4-pro | packed-record-v1 | hidden | 74/76 case(s) failed |
| openai-deepseek-flash | packed-record-v1 | hidden | 70/76 case(s) failed |
| openai-deepseek-v4-pro | packed-record-v1 | hidden | 74/76 case(s) failed |
| openai-deepseek-flash | packed-record-v1 | hidden | 74/76 case(s) failed |
| openai-deepseek-flash | packed-record-v1 | hidden | 74/76 case(s) failed |
| openai-deepseek-v4-pro | packed-record-v1 | hidden | 74/76 case(s) failed |
| openai-deepseek-flash | packed-record-v1 | hidden | 74/76 case(s) failed |
| openai-deepseek-flash | packed-record-v1 | hidden | 74/76 case(s) failed |
| openai-deepseek-v4-pro | packed-record-v1 | hidden | 76/76 case(s) failed |
| openai-deepseek-v4-pro | packed-record-v1 | hidden | 30/76 case(s) failed |
| openai-deepseek-flash | packed-record-v1 | hidden | 74/76 case(s) failed |
| openai-deepseek-v4-pro | packed-record-v1 | hidden | 74/76 case(s) failed |
| openai-deepseek-flash | packed-record-v1 | hidden | 74/76 case(s) failed |
