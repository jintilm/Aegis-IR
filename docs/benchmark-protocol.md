# Benchmark protocol

Status: harness implemented (`tools/aegis-bench`); binary-recovery tasks and
artifact profiles are implemented and tested offline; four public tasks
(`rolling-token-v1`, `rolling-token-v2`, `packed-record-v1`,
`lane-shift-v1`); four real-model pilots are published under `docs/reports/`.
They are pilots, not effectiveness claims. Every number in future reports must
be traceable to a commit, a model version, and a date.

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
- an experiment-use class, difficulty, input domain and declared tool policy;
- a unique ID and content hash.

Task manifests use schema version 2. The loader still accepts version 1 for
frozen historical tasks and labels those rows with a legacy tool policy.
Schema version 2 requires `experiment_use`, `protectability`, `tool_policy` and
`input_domain`; these fields are copied into every run row as `task_protocol`
so a report can be audited without reopening a possibly changed manifest.

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
adapters and a harness self-check. Four real-model pilots are published under
`docs/reports/`; all are pilots, and the oracle-access run cannot show a
protection effect — see below.

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
under `binary` access on one task with one model at one step budget
(`packed-record-v1` × `deepseek-v4-pro`, 30 steps, three independent runs, 23
attempts total, one infrastructure timeout excluded):

| arm | passes | token mean (every run) |
|---|---|---|
| baseline | 3/12 (25%) | 457 k |
| aegis-level3 | 2/11 (18%) | 935 k |

- **A success-rate comparison cannot be resolved at any repetition count we can
  afford.** Fisher's exact test on 3/12 vs 2/11 gives p = 0.55; reaching
  α = 0.05 with 80% power against a 25% → 18% shift needs roughly **540 runs per
  arm** — ~10 days of single-relay model time for one two-arm comparison.
  Pooling the 45-step arm instead gives 5/17 vs 2/15 (29% vs 13%, p = 0.25,
  ~100 runs per arm): the estimate moves 9 points depending on which runs are
  pooled, which is itself the reason not to claim a direction.
  `N >= 5` in the [matrix](#matrix) is a **floor for reporting a number with an
  interval**, not a claim of sufficiency; no success-rate effect may be asserted
  below the powered count.
- **A case-level secondary metric does not help.** Across those runs the
  per-run `success_rate` takes values 0.0, ≈0.03, or 1.0 — there are no
  near-misses to score partially. It is recorded in every row (`cases_passed`,
  `cases_total`, `success_rate`) and reported, but it buys no resolution.
- **Token cost is the metric that resolves.** The level-3 / baseline ratio was
  **1.91×, 2.06×, 2.12×** in the three 30-step runs — same direction every time,
  across adapter revisions, and 2.05× on the pooled means. Once the
  final-answer turn is in place every run carries a ledger, so this is an
  unconditional cost rather than one conditioned on success (the 45-step arm,
  measured before every run had a ledger, gave a lower 1.33× because its
  baseline runs were more expensive).
- **Wall clock is not a cost signal here.** In the same data the level-3
  median wall time (595 s) is *below* the baseline (840 s) while its token cost
  is 2× higher, because a protected listing produces more restarts and more
  early terminations. Report it as latency, never as cost.

Practically: a pilot may report "level 3 doubles the token cost (per-run ratios
1.9–2.1×; pooled 457 k → 935 k) with no success-rate change distinguishable at
this N". It may not report that level 3 *reduced* success — that requires the
powered count above.

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
Token figures are **self-reported** unless the run went through the harness
metering proxy (§[Token metering](#token-metering)); tool-call figures are
always adapter self-reports. The row's `ledger_source` says which, and the
reports repeat it next to the numbers.

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
| Tokens | **measured** when `--meter-upstream` is given (provider `usage` via the harness proxy); otherwise adapter self-report |
| Tool calls, output tokens | **not enforced**; adapter self-report only |

A report may quote enforced numbers. Unenforced ones are labelled
`self-reported by adapter` and cannot support a cost claim on their own.

## Token metering

Token cost is the metric the benchmark exists to measure, so the harness has
to own the meter. With `--meter-upstream <relay-base-url>` — or
`meter_upstream=` on `Runner` — each run starts a loopback reverse proxy in
front of the model endpoint, exports it to the adapter as
`AEGIS_METER_BASE_URL`, and records what passed through:

- for a streaming request the proxy sets `stream_options.include_usage` on
  the way through, so the provider reports usage on the terminal chunk
  whether or not the adapter asked for it (verified against the reference
  relay: injection → `usage` present → tokens counted);
- the totals are the **provider's own** `usage` report, not a re-estimate
  of characters, which would look like evidence while being a guess;
- `metering.requests`, `metering.requests_with_usage`,
  `metering.status_counts` and byte counts are counted by the harness.

Attribution is by port: one proxy per run, so a cell cannot inherit another
cell's traffic. The block is stamped in the row as `metering`, and
`ledger_source` reads `metered by harness` only when **every** request in
the run carried provider usage. Three limits are part of the design, not
caveats to add later:

1. **It is not a sandbox.** An adapter that calls the upstream directly
   bypasses the meter. That run shows `requests: 0` and keeps the
   self-reported label — visibly unmetered rather than quietly mislabelled.
   A run that both uses and bypasses the proxy is undercounted, and the
   harness cannot detect it. Process-level isolation is still required
   before a published cost claim.
2. **The provider may ignore `include_usage`.** Then requests are counted
   but carry no usage; `requests_without_usage` says how many and
   `total_tokens` is `null`, never a zero.
3. **Deviations are detectable in one direction.** The adapter's own figure
   is kept beside the metered one; `metering.adapter_exceeds_metered` is
   true when the adapter claims more than the proxy saw, which means traffic
   left the proxy. The adapter claiming *less* is normal — aborted calls are
   estimated, never answered by the provider.
4. **Abandoned calls are not kept alive to be measured.** When the agent
   hangs up mid-stream — its reasoning watchdog fired, or it gave up on a
   step — the proxy closes the upstream call as the agent would have.
   Draining the rest of the stream instead would make the provider generate
   tokens nobody reads and then charge them to the run. That is not a
   hypothetical: an earlier version of the proxy did exactly that and
   inflated completion tokens by ~18% on one arm, in a direction set by how
   often that arm aborted — an arm-dependent bias that would have moved the
   very ratio the benchmark reports. Such calls appear as
   `metering.client_disconnects` and carry no usage, so a metered total is a
   **floor** on the true cost, never an overstatement. Their prompt tokens
   are genuinely spent and genuinely unmeasured; the adapter's
   `aborted_tokens_estimate` is the only figure that covers them, and it is
   labelled an estimate.

An adapter that ignores `AEGIS_METER_BASE_URL` is not an error: its runs
simply stay self-reported, and a comparison must not mix the two kinds of
row in one headline number.

## Matrix

`{baseline, aegis-level1, aegis-level2, aegis-level3} × {C1, C2, C3,
white-box} × {>= 2 model families} × N >= 5 repetitions`, reporting mean,
variance, and confidence intervals. Binary-recovery tasks define their profile
names in the manifest; `reimplement` tasks keep their earlier profile labels.
Per-transform ablations report marginal contribution.

`N >= 5` is the minimum for reporting a number with a confidence interval, not
a count that can resolve a success-rate effect — see
[statistical power](#statistical-power-which-number-carries-the-result). A
success-rate claim needs the powered count (100–540 runs per arm for the effect
sizes measured so far, depending on which runs are pooled); a cost claim can be
made from the pilot counts, where every run carries a ledger and, under
`--meter-upstream`, the token total comes from the provider rather than the
adapter. A matrix row that mixes metered and self-reported runs cannot report a
headline ratio.

Use `aegis-bench campaign` rather than a bespoke adapter loop. The campaign
manifest pins the matrix, ordering seed, access mode, meter requirement and
clean-tree requirement; `campaign-state.json` makes the run resumable after a
kill, and `aegis-bench audit` checks the raw JSONL against the planned cells.
See [`campaigns.md`](campaigns.md).

Campaign orchestration is not process isolation. The current adapter still
runs in-process, tool calls are self-reported, and binary-access probe
executions are uncounted. The worker/broker boundary that closes those gaps is
specified in [`isolation.md`](isolation.md); protection-effect claims require
it.

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
