# Aegis-Bench run report

- Commit: `2c0321d4a59c3dce4a0287ed9f00e7ccd738b576` (dirty: yes)
- Platform: Linux-6.18.54.1-microsoft-standard-WSL2-x86_64-with-glibc2.39
- Python: 3.12.3
- Runs: 1

Token and tool-call figures are **self-reported by the adapter**; the harness cannot observe them independently. Pass/fail and case counts are measured.

| profile | agent | task | runs | pass | success rate | wall s (mean±sd) | tokens (mean) | tool calls (mean) |
|---|---|---|---|---|---|---|---|---|
| baseline | stub | rolling-token-v1 | 1 | 0/1 | 0% | 4.82±0.00 | n/a | 1.0 |

## Failures

| agent | task | stage | reason |
|---|---|---|---|
| stub | rolling-token-v1 | hidden | 73/73 case(s) failed |
