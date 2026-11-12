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

### Task calibration

A task's usefulness depends on how hard its **unprotected** baseline is, and on
which number is being read:

- at the **floor** (baseline never succeeds) there is no headroom, and neither
  a success-rate nor a cost delta is interpretable — the agent fails for reasons
  unrelated to protection;
- at the **ceiling** (baseline always succeeds) a success-rate delta is
  saturated and uninterpretable, but a **cost** delta still is: the success
  criterion is held fixed across both arms, which is exactly the benchmark's
  primary metric;
- **comparison-ready** (baseline passes sometimes) supports both.

Every binary-recovery task therefore carries a `calibration` record in its
manifest, one per access mode:

```json
"calibration": {
  "oracle": {
    "status": "floor",            // uncalibrated | floor | ceiling | comparison-ready
    "model": "deepseek-v4.1-flash",
    "baseline_pass_rate": 0.0,
    "runs": 3,
    "date": "2026-11-11"
  },
  "binary": {
    "status": "comparison-ready",
    "model": "deepseek-v4-pro",
    "baseline_pass_rate": 0.5,
    "runs": 2,
    "date": "2026-11-12"
  }
}
```

- One record per **access mode**, because the same task can be at the floor for
  a black-box agent and solvable for one that can read the binary. A single
  flat record would silently describe only one of those runs.
- `floor` means the baseline never passed, `ceiling` that it always did, and
  `comparison-ready` that it landed strictly between. The loader rejects a
  label that contradicts its own rate, and rejects a calibrated record without
  a model, a date and a run count. A `ceiling` task can still be used for a
  cost comparison; the reports say which kind of number is interpretable.
- Calibration is **model- and access-specific**: the same task can be at the
  floor for a small model under `oracle` access and comparison-ready for a
  larger one under `binary` access. Recalibrate when either changes; a run's
  rows carry the calibration record that was in force.
- The record is measurement metadata, not task semantics: it sits outside
  `content_hash` and does not require a new task id.
- Reports of binary-recovery runs print the calibration and warn when a
  comparison was run on a task that is not comparison-ready.

### Submission rate and cost conditioning

A run whose agent never calls `submit_solution` has no candidate, no grade and
no token ledger. Reports therefore keep two things apart:

- **Submission rate is reported next to pass rate.** "0/5 passed" and "0/5
  passed, 2/5 submitted" describe different agents, and only the second set of
  runs has a cost.
- **Cost is conditioned on submission.** Token and wall means cover only the
  runs that submitted. When the two arms' submission rates differ, part of the
  cost difference is a capability difference, and the report has to say so
  rather than presenting the delta as a protection cost.

Several tasks in this set are **bimodal** for a given agent: it either
reconstructs the function completely or produces nothing usable. A mean over
such a set is misleading — with half the runs in the non-submission mode, the
mean describes which runs existed, not how much recovery cost. Report the
per-run outcome distribution, and if more than a fifth of runs fail to submit,
treat the configuration as miscalibrated (step budget, task difficulty or
agent policy) instead of computing a delta from it.

### Statistical power: which number carries the result

Success is a **Bernoulli per run**, and the per-run outcome is bimodal — an
agent either reconstructs the function or gets a handful of cases. Measured
under `binary` access on one task with one model
(`packed-record-v1` × `deepseek-v4-pro`, three independent runs, 12 attempts per
arm):

| arm | passes | token mean (submitted runs) |
|---|---|---|
| baseline | 5/12 (42%) | 562 k |
| aegis-level3 | 2/12 (17%) | 869 k |

- **A success-rate comparison cannot be resolved at any repetition count we can
  afford.** Fisher's exact test on 5/12 vs 2/12 gives p = 0.19; reaching
  α = 0.05 with 80% power against a 42% → 17% shift needs roughly **50 runs per
  arm**, i.e. ~23 h of single-relay model time for one two-arm comparison.
  `N >= 5` in the [matrix](#matrix) is a **floor for reporting a number with an
  interval**, not a claim of sufficiency; no success-rate effect may be asserted
  below the powered count.
- **A case-level secondary metric does not help.** Across those runs the
  per-run `success_rate` takes values 0.0, ≈0.03, or 1.0 — there are no
  near-misses to score partially. It is recorded in every row (`cases_passed`,
  `cases_total`, `success_rate`) and reported, but it buys no resolution.
- **Token cost is the metric that resolves.** The level-3 / baseline ratio was
  **1.91×, 2.06×, 1.33×** in the three independent runs — same direction every
  time, from different adapter revisions and step budgets. This is a *lower
  bound* on the protection cost: runs that never submit contribute no ledger,
  and those are precisely the attempts that burned the most budget.
- **Wall clock is not a cost signal here.** In the same data the level-3
  median wall time (595 s) is *below* the baseline (840 s) while its token cost
  is 1.5× higher, because a protected listing produces more restarts and more
  early terminations. Report it as latency, never as cost.

Practically: a pilot may report "level 3 costs ~1.7× the tokens (per-run ratios
1.3–2.1×; pooled means 562 k → 869 k) with no success-rate change
distinguishable at this N". It may not report that level 3 *reduced* success —
that requires the powered count above.

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

`N >= 5` is the minimum for reporting a number with a confidence interval, not
a count that can resolve a success-rate effect — see
[statistical power](#statistical-power-which-number-carries-the-result). A
success-rate claim needs the powered count (~50 per arm for the effect sizes
measured so far); a cost claim can be made from the pilot counts, labelled as a
lower bound.

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