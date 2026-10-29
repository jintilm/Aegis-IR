# Benchmark protocol

Status: harness implemented (`tools/aegis-bench`), one public task, no run
published yet. Every number in future reports must be traceable to a commit,
a model version, and a date.

## Unit of analysis

The measured quantity is the **cost delta**: what an agent must pay (tokens,
wall-clock, tool calls, human turns) to reach a fixed success criterion on a
task, with and without a protection transform. "Can the AI be defeated" is not
a metric.

## Task format

Each task declares:

- a target binary + interface contract (signature, I/O formats, a few examples);
- ground-truth source (never shipped to the agent);
- executable property tests (the success criterion);
- hidden edge cases and a differential-fuzz input set;
- domain size and a protectability rating (same rules as `aegis-lint`);
- a unique ID and content hash.

Agents must produce an executable candidate implementation (or a structured
semantic answer). Scoring:

1. re-executability against hidden property tests,
2. differential fuzz agreement with ground truth,
3. double-blind human rubric sampling for descriptive tasks.

Implementation status: (1) and (2) are implemented and tested; (3) is not,
and descriptive tasks are therefore not accepted yet.

### Integrity rules the harness enforces

- The agent workspace contains only the manifest's `visible` entries; ground
  truth, hidden cases and the grader are never copied in (asserted by test).
- A task whose files changed after `content_hash` was recorded fails to load.
- Candidate source names are whitelisted and sanitised; a name with a path
  separator or traversal segment is rejected, not written.
- Candidate text is compiled and executed as untrusted input; the grader never
  reads adapter notes or cost claims when deciding a score.

## Budgets and controls

Per run, fixed and recorded: model id + version, system prompt, tool set,
timeouts, max tool calls, token budget, machine profile. Deviations are
reported, never silently absorbed.

The harness records the budget config and environment stamp in every row.
Token and tool-call figures are adapter self-reports and are labelled as such
in the reports; the harness currently cannot corroborate them.

## Matrix

`{baseline, release, aegis-standard, aegis-research?, Pluto/PLO control} ×
{C1, C2, C3, white-box} × {>= 2 model families} × N >= 5 repetitions`,
reporting mean, variance, and confidence intervals. Per-transform ablations
report marginal contribution.

## Oracle-budget curve

For the primary scenario (offline C++ algorithm libraries), tasks allow oracle
queries under a budget B; we report recovery accuracy as a function of B.
This curve is expected to show that small-domain functions are recoverable
regardless of obfuscation — an honest result we commit to publishing.

## Private set

A hidden task subset is stored outside the public repo, rotated by 20% per
quarter, and shared among maintainers under multi-custody. Reference sources,
oracles, and graders never enter the agent's working directory.

`benchmarks/tasks-private/` in this repository documents the layout only; the
actual contents live in external storage.

## Reporting

- Every report: timestamp, matrix cell, model versions, N, variance.
- Claims ledger: each public claim in README/docs links to a report
  (commit, model versions, date, reproduction command). Unledgered claims are
  removed.
- Model Drift Report, quarterly: re-run the previous quarter's tasks against
  new model versions; publish the decay curve.
- Negative results are published with the same prominence as positive ones.