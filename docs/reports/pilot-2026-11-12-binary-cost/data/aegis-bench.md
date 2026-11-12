# Aegis-Bench run report

- Commit: `6ddca5a2febec3224dafd3c800028a794ed10776` (dirty: no)
- Platform: Linux-6.18.54.1-microsoft-standard-WSL2-x86_64-with-glibc2.39
- Python: 3.12.3
- Machine: `1a4f52c2f4c7` (salted hash; no host or user name is recorded)
- Runs: 10

Pass/fail, case counts, wall clock and oracle queries are measured by the harness. Token and tool-call figures are **self-reported by the adapter** and cannot be corroborated. Pass rates carry a Wilson 95% interval; cost deltas carry an interval only when both groups have at least two runs. A run row states which budgets were enforced.

- Adapters: `openai-deepseek-v4-pro 2db70bc80cf3`

- Access: `binary`

- Calibration: `packed-record-v1` [binary] = comparison-ready (deepseek-v4-pro, 0.2, N=5)

A binary-recovery row records an **access mode**. Under `oracle` the workspace holds only a shim and the probe stays with the harness broker, which counts every query and enforces `budgets.oracle_queries` when the manifest sets one. Under `binary` the workspace holds the stripped probe itself, so the agent can execute and disassemble it; queries are then **not counted** (the JSONL says `null`, not `0`). Neither mode is a sandbox: an adapter that reaches the artifact cache directly is not counted either way, and real runs need process isolation. Each row records the probe's SHA-256 and size; its build log is in the JSONL row.

| profile | artifact level | artifact `.text` | sha256 (12) |
|---|---|---|---|
| aegis-level3 | 3 | 6070 | `b4234b74dc75` |
| baseline | 0 | 3922 | `f87131322a7f` |

## By (profile, agent, task)

| profile | agent | task | runs | pass | pass rate (95% CI) | wall s (mean±sd) | tokens (self-rep) | oracle queries (mean) |
|---|---|---|---|---|---|---|---|---|
| aegis-level3 | openai-deepseek-v4-pro | packed-record-v1 | 5 | 0/5 | 0% [0%-43%] | 1400.35±252.95 | 1008253 | n/a |
| baseline | openai-deepseek-v4-pro | packed-record-v1 | 5 | 0/5 | 0% [0%-43%] | 1418.62±275.96 | 474665 | n/a |

## By (agent, profile), across tasks

| agent | profile | tasks | runs | pass | pass rate (95% CI) | wall s (mean±sd) | tokens (self-rep) | oracle queries (total) |
|---|---|---|---|---|---|---|---|---|
| openai-deepseek-v4-pro | aegis-level3 | 1 | 5 | 0/5 | 0% [0%-43%] | 1400.35±252.95 | 1008253 | n/a |
| openai-deepseek-v4-pro | baseline | 1 | 5 | 0/5 | 0% [0%-43%] | 1418.62±275.96 | 474665 | n/a |

## Cost delta vs baseline

Positive means the protected profile cost more. Wall-clock and oracle-query deltas are measured; the token delta is self-reported.

| agent | task | cell | Δ wall s (95% CI) | Δ oracle queries | Δ tokens (self-rep) |
|---|---|---|---|---|---|
| openai-deepseek-v4-pro | packed-record-v1 | baseline → aegis-level3 | -18.28 [-385.14, +348.59] s | n/a | +533588 [+260480, +806697] |


## Failures

| agent | task | stage | reason |
|---|---|---|---|
| openai-deepseek-v4-pro | packed-record-v1 | hidden | 76/76 case(s) failed |
| openai-deepseek-v4-pro | packed-record-v1 | hidden | 76/76 case(s) failed |
| openai-deepseek-v4-pro | packed-record-v1 | hidden | 73/76 case(s) failed |
| openai-deepseek-v4-pro | packed-record-v1 | build | candidate build failed: /tmp/aegis-grade-kazlm8x7/candidate/target.cpp:3:52: error: stray '#' in program
    3 | <｜｜DSML｜｜parameter name="source" string="true">#include <cstddef>
      |                                                    ^
/tmp/aegis-grade-kazlm8x7/candidate/target.cpp:1:1: error: expected unqualified-id before '<' token
    1 | <｜｜DSML｜｜tool_calls>
      | ^
/tmp/aegis-grade-kazlm8x7/candidate/target.cpp:8:40: error: 'size_t' has not been declared
    8 | uint32_t pr_flags(const uint8_t *data, size_t len) {
      |                                        ^~~~~~
/tmp/aegis-grade-kazlm8x7/candidate/target.cpp: In function 'uint32_t pr_flags(const uint8_t*, int)':
/tmp/aegis-grade-kazlm8x7/candidate/target.cpp:10:10: error: 'size_t' was not declared in this scope
   10 |     for (size_t i = 0; i < 4; ++i) {
      |          ^~~~~~
/tmp/aegis-grade-kazlm8x7/candidate/target.cpp:5:1: note: 'size_t' is defined in header '<cstddef>'; did you forget to '#include <cstddef>'?
    4 | #include <cstdint>
  +++ |+#include <cstddef>
    5 | 
/tmp/aegis-grade-kazlm8x7/candidate/target.cpp:10:24: error: 'i' was not declared in this scope
   10 |     for (size_t i = 0; i < 4; ++i) {
      |                        ^
/tmp/aegis-grade-kazlm8x7/candidate/target.cpp: At global scope:
/tmp/aegis-grade-kazlm8x7/candidate/target.cpp:21:39: error: 'size_t' has not been declared
   21 | uint64_t pr_fold(const uint8_t *data, size_t len) {
      |                                       ^~~~~~
/tmp/aegis-grade-kazlm8x7/candidate/target.cpp: In function 'uint64_t pr_fold(const uint8_t*, int)':
/tmp/aegis-grade-kazlm8x7/candidate/target.cpp:23:10: error: 'size_t' was not declared in this scope
   23 |     for (size_t i = 0; i < len; ++i) {
      |          ^~~~~~
/tmp/aegis-grade-kazlm8x7/candidate/target.cpp:23:10: note: 'size_t' is defined in header '<cstddef>'; did you forget to '#include <cstddef>'?
/tmp/aegis-grade-kazlm8x7/candidate/target.cpp:23:24: error: 'i' was not declared in this scope
   23 | |
| openai-deepseek-v4-pro | packed-record-v1 | hidden | 73/76 case(s) failed |
| openai-deepseek-v4-pro | packed-record-v1 | build | candidate build failed: /tmp/aegis-grade-vx3ujbgw/candidate/target.cpp:3:52: error: stray '#' in program
    3 | <｜｜DSML｜｜parameter name="source" string="true">#include <cstddef>
      |                                                    ^
/tmp/aegis-grade-vx3ujbgw/candidate/target.cpp:1:1: error: expected unqualified-id before '<' token
    1 | <｜｜DSML｜｜tool_calls>
      | ^
/tmp/aegis-grade-vx3ujbgw/candidate/target.cpp:8:40: error: 'size_t' has not been declared
    8 | uint32_t pr_flags(const uint8_t *data, size_t len) {
      |                                        ^~~~~~
/tmp/aegis-grade-vx3ujbgw/candidate/target.cpp: In function 'uint32_t pr_flags(const uint8_t*, int)':
/tmp/aegis-grade-vx3ujbgw/candidate/target.cpp:10:10: error: 'size_t' was not declared in this scope
   10 |     for (size_t i = 0; i < len && i < 4; ++i) {
      |          ^~~~~~
/tmp/aegis-grade-vx3ujbgw/candidate/target.cpp:5:1: note: 'size_t' is defined in header '<cstddef>'; did you forget to '#include <cstddef>'?
    4 | #include <cstdint>
  +++ |+#include <cstddef>
    5 | 
/tmp/aegis-grade-vx3ujbgw/candidate/target.cpp:10:24: error: 'i' was not declared in this scope
   10 |     for (size_t i = 0; i < len && i < 4; ++i) {
      |                        ^
/tmp/aegis-grade-vx3ujbgw/candidate/target.cpp: At global scope:
/tmp/aegis-grade-vx3ujbgw/candidate/target.cpp:38:39: error: 'size_t' has not been declared
   38 | uint64_t pr_fold(const uint8_t *data, size_t len) {
      |                                       ^~~~~~
/tmp/aegis-grade-vx3ujbgw/candidate/target.cpp: In function 'uint64_t pr_fold(const uint8_t*, int)':
/tmp/aegis-grade-vx3ujbgw/candidate/target.cpp:41:10: error: 'size_t' was not declared in this scope
   41 |     for (size_t i = 0; i < len; ++i) {
      |          ^~~~~~
/tmp/aegis-grade-vx3ujbgw/candidate/target.cpp:41:10: note: 'size_t' is defined in header '<cstddef>'; did you forget to '#include <cstddef>'?
/tmp/aegis-grade-vx3ujbgw/candidate/target.cpp:41:24: error: 'i' was not declared |
| openai-deepseek-v4-pro | packed-record-v1 | agent | adapter error: adapter exceeded its 1800s wall-clock budget |
| openai-deepseek-v4-pro | packed-record-v1 | hidden | 76/76 case(s) failed |
| openai-deepseek-v4-pro | packed-record-v1 | hidden | 74/76 case(s) failed |
| openai-deepseek-v4-pro | packed-record-v1 | hidden | 74/76 case(s) failed |
