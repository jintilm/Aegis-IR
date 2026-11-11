# Benchmark protocol

Status: harness implemented (`tools/aegis-bench`); binary-recovery tasks and
artifact profiles are implemented and tested offline; four public tasks
(`rolling-token-v1`, `rolling-token-v2`, `packed-record-v1`,
`lane-shift-v1`), no run against a real model published yet. Every number in future reports must be
traceable to a commit, a model version, and a date.

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

### Task types

- **`reimplement`** (default): the agent sees a written brief, the interface
  and sample I/O, and writes an implementation from the specification.
- **`binary-recovery`**: the runner also builds a **stripped probe** from the
  ground truth and places it behind an **oracle broker**: the workspace gets a
  shim that forwards queries to the broker, which holds the probe, counts each
  query, and enforces an optional `budgets.oracle_queries`. The agent may use
  it as an oracle, but must still deliver a standalone implementation; the
  interface, driver and scoring are identical to `reimplement`.

A binary-recovery manifest adds an artifact recipe:

```json
"task_type": "binary-recovery",
"artifact": {
  "source": "ground_truth/target.cpp",
  "probe": "grader/driver.cpp",
  "include_dirs": ["include"],
  "profiles": {
    "baseline": {"level": 0},
    "aegis-level1": {"level": 1, "policy": "grader/policies/level1.json"},
    "aegis-level2": {"level": 2, "policy": "grader/policies/level2.json"},
    "aegis-level3": {"level": 3, "policy": "grader/policies/level3.json"}
  }
}
```

`source` must be the same file as `ground_truth`, so the binary the agent
reverses and the reference the grader tests are built from one source. Level
0 is a plain `default<O2>` build; levels 1–3 run
`aegis-policy, aegis-decoys[, aegis-cff], default<O2>, aegis-verify` on
frontend IR. The builder records the probe's SHA-256, file size, `.text` size
and build log in every run row. Policy files are validated at task load: a
level-3 profile whose policy selects level-1 functions fails before a run.

Agents must produce an executable candidate implementation (or a structured
semantic answer). Scoring:

1. re-executability against hidden property tests,
2. differential fuzz agreement with ground truth,
3. double-blind human rubric sampling for descriptive tasks.

Implementation status: (1) and (2) are implemented and tested; (3) is not,
and descriptive tasks are therefore not accepted yet. Binary-recovery artifact
building is implemented for levels 0–3, tested offline with deterministic
adapters and a harness self-check. One real-model pilot has been run; it used
**oracle access**, which cannot show a protection effect — see below.

### Access modes

A binary-recovery run records how much of the artifact the agent gets
(`--access`, stamped in every row):

| Mode | Workspace holds | Queries | What it can measure |
|---|---|---|---|
| `oracle` (default) | a shim that forwards to the harness broker | counted, capped by `budgets.oracle_queries` | how much an agent can recover from I/O alone, and the oracle-budget curve |
| `binary` | the stripped probe itself, executable | **not counted** | the cost of recovering semantics from the artifact — the only mode in which a protection transform can matter |

The distinction is not cosmetic. Under `oracle` access the agent sees a shim
whose behaviour is byte-identical in every artifact profile: it cannot inspect
code, section layout or control flow, so levels 1–3 present exactly the same
information as the baseline. **A level-vs-baseline cost delta measured under
`oracle` access is zero by construction**; whatever variance appears is noise.
Reports generated for `oracle` rows say this next to the numbers, and those
rows cannot support an effectiveness claim. Protection comparisons require
`binary` access, where the agent has what the task contract promises and what
the threat model assumes (a binary it can execute and disassemble).

The trade is explicit: with the probe in the workspace there is no honest way
to count queries, so `oracle.queries` is recorded as `null` — not `0` — and a
manifest that sets `budgets.oracle_queries` is rejected under `binary` access
rather than silently unenforced. Counting under binary access needs
process-level execution accounting, which this harness does not yet have.

### Integrity rules the harness enforces

- The agent workspace contains only the manifest's `visible` entries; ground
  truth, hidden cases and the grader are never copied in (asserted by test).
- A task whose files changed after `content_hash` was recorded fails to load.
- Candidate source names are whitelisted and sanitised; a name with a path
  separator or traversal segment is rejected, not written.
- Candidate text is compiled and executed as untrusted input; the grader never
  reads adapter notes or cost claims when deciding a score.
- The candidate include path never contains the task root, and compilation and
  execution both run in a private scratch directory with a minimal
  environment, a wall-clock timeout, an address-space rlimit and an output cap.
  Absolute and parent-relative `#include`s are rejected before compilation.
- A candidate-source policy rejects (a) references to grader material,
  (b) `system`/`exec*`/`fork` calls, (c) quoted includes outside the task
  interface and the candidate's own files, and (d) sources over 256 KiB.
  These are tripwires for oracle replay, not a sandbox: a malicious adapter
  can still open sockets or walk the filesystem, so real runs must execute the
  adapter and grader inside a container or namespace.
- The workspace contains the task's visible files plus, for binary-recovery
  tasks, either the oracle **shim** (`oracle` access) or the stripped **probe**
  (`binary` access) — never ground truth, the grader, property tests or hidden
  cases (asserted by test).
- **Adapters are trusted not to read grader material.** The harness isolates
  the *workspace* it hands to an in-process adapter, but it cannot sandbox a
  malicious adapter that walks the filesystem. Real runs should execute the
  adapter in an environment whose filesystem view contains only the workspace.
- A submission must be a standalone implementation. Embedding or wrapping the
  provided probe is not a valid solution. The source policy rejects the
  obvious forms (oversized sources, `system`/`exec*`, references to grader
  paths); a determined replay that hides the blob is still not detectable, so
  human review must reject it.

## Budgets and controls

Per run, fixed and recorded: model id + version, system prompt, tool set,
timeouts, max tool calls, token budget, machine profile. Deviations are
reported, never silently absorbed. Adapters live outside this repository; their
required parameters and the recovery policy that must be identical across
profiles are specified in
[`reference-adapter.md`](reference-adapter.md).

The harness records the budget config and environment stamp in every row.
Token and tool-call figures are adapter self-reports and are labelled as such
in the reports; the harness cannot corroborate them.

Oracle queries are different: the broker counts them on the harness side, so
`oracle.queries` and `oracle.refused` are **measured**. When the manifest sets
`budgets.oracle_queries`, the broker refuses further queries; otherwise it
counts without a cap. The count is per run and is the input the oracle-budget
curve needs. An adapter that bypasses the shim — for example by executing the
cached probe directly — is not counted: the broker is accounting, not a
sandbox.

## Task versioning

Task ids are immutable once a result is published. A change to a task's
files, its interface, its artifact profiles or its visibility is a **new
task id**, never an in-place edit: `rolling-token-v1` (reimplementation) and
`rolling-token-v2` (binary-recovery) share a code base precisely so a reader
can tell which question a result answered. The content hash catches accidental
edits, but only the id carries the semantic difference.

## Enforced vs. reported budgets

Each run row records both the configured budget and whether it was enforced:

| Budget | Status |
|---|---|
| Adapter wall clock | enforced (`SIGALRM` on POSIX; watchdog elsewhere, which detects but cannot interrupt) |
| Candidate build/run time, address space, output size | enforced by the grader |
| Oracle queries | counted by the harness broker; capped when `budgets.oracle_queries` is set |
| Tool calls, output tokens | **not enforced**; adapter self-report only |

A report may quote enforced numbers; unenforced ones are labelled
`self-reported by adapter` and cannot support a cost claim on their own.

## Matrix

`{baseline, aegis-level1, aegis-level2, aegis-level3} × {C1, C2, C3,
white-box} × {>= 2 model families} × N >= 5 repetitions`, reporting mean,
variance, and confidence intervals. Binary-recovery tasks define their profile
names in the manifest; `reimplement` tasks keep their earlier profile labels.
Per-transform ablations report marginal contribution.

## Oracle-budget curve

For the primary scenario (offline C++ algorithm libraries), tasks allow oracle
queries under a budget B; we report recovery accuracy as a function of B.
The broker now counts queries and enforces B when a task sets
`budgets.oracle_queries`, so the curve is implementable; it has not been
measured yet. This curve is expected to show that small-domain functions are
recoverable regardless of obfuscation — an honest result we commit to
publishing.

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