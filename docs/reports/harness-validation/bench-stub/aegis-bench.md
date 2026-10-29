# Aegis-Bench run report

- Commit: `ef7b2a799faa2ce7a9a0fecd17cfd01f93b486d9` (dirty: yes)
- Platform: Linux-6.18.54.1-microsoft-standard-WSL2-x86_64-with-glibc2.39
- Python: 3.12.3
- Runs: 1

Token and tool-call figures are **self-reported by the adapter**; the harness cannot observe them independently. Pass/fail and case counts are measured.

Binary-recovery runs place only a stripped probe in the agent workspace. Each row records the probe's SHA-256 and size; the probe's build log is in the JSONL row. Oracle queries are made by the adapter and are not observable by the harness.

| profile | artifact level | artifact `.text` | sha256 (12) |
|---|---|---|---|
| baseline | 0 | 4334 | `ef0dea649feb` |

| profile | agent | task | runs | pass | success rate | wall s (mean±sd) | tokens (mean) | tool calls (mean) |
|---|---|---|---|---|---|---|---|---|
| baseline | stub | rolling-token-v1 | 1 | 0/1 | 0% | 5.19±0.00 | n/a | 1.0 |

## Failures

| agent | task | stage | reason |
|---|---|---|---|
| stub | rolling-token-v1 | hidden | 73/73 case(s) failed |
