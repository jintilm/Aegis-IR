# Aegis-Bench run report

- Commit: `e3ea0b0e7c96c7cd1a1a4ee050de0ea3e7866edb` (dirty: yes)
- Platform: Linux-6.18.54.1-microsoft-standard-WSL2-x86_64-with-glibc2.39
- Python: 3.12.3
- Runs: 1

Token and tool-call figures are **self-reported by the adapter**; the harness cannot observe them independently. Pass/fail and case counts are measured.

| profile | agent | task | runs | pass | success rate | wall s (mean±sd) | tokens (mean) | tool calls (mean) |
|---|---|---|---|---|---|---|---|---|
| baseline | stub | rolling-token-v1 | 1 | 0/1 | 0% | 4.29±0.00 | n/a | 1.0 |

## Failures

| agent | task | stage | reason |
|---|---|---|---|
| stub | rolling-token-v1 | hidden | 73/73 case(s) failed |
