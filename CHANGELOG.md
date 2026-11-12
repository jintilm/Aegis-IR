# Changelog

All notable changes to this project. Format loosely follows Keep a Changelog;
versions follow SemVer once past alpha.

## [0.2.0-alpha] - 2026-11-12

### Added

- **Four additional public task families** - `window-parser-v1`,
  `state-fold-v1`, `ring-drain-v1` and `grid-route-v1` expand the public set
  from four to eight tasks. Each has real sample I/O, ground truth, property
  tests, hidden cases, seeded fuzz coverage, schema-v2 metadata and all four
  artifact profiles. Ground truth and every protected artifact build are
  covered by the harness test suite; the tasks remain uncalibrated for models.
- **Campaign orchestration, resume and audit** — `aegis-bench campaign` expands
  an experiment manifest into uniquely keyed cells, creates a fresh adapter per
  cell, interleaves profiles within each repetition, fingerprints the manifest,
  takes an exclusive output lock, and writes atomic reports plus
  `campaign-state.json` after every completed cell. Re-running the same command
  skips already-recorded cells; duplicate,
  foreign or missing cells are rejected. `aegis-bench audit` independently
  checks raw JSONL rows for duplicate/missing cells, commit and adapter-version
  drift, stale task hashes, mixed meter provenance, dirty worktrees,
  infrastructure failures and binary-access oracle mislabelling. The shipped
  offline campaign is covered by unit and CTest integration tests. See
  [`docs/campaigns.md`](docs/campaigns.md).
- **Task schema v2 and campaign provenance** — task manifests now declare
  `experiment_use`, `difficulty`, `input_domain`, `protectability` and a
  `tool_policy` (`allowed_tools`, `network`, `workspace_writable`). Every run row
  carries the protocol snapshot as `task_protocol`; campaign rows additionally
  carry the campaign id, purpose, primary metric, manifest SHA-256, cell key and
  global order index. Schema v1 remains readable and is labelled as a legacy,
  unspecified tool policy. The declaration is measurement metadata, not
  enforcement: the in-process adapter still does not have a sandbox.
- **`aegis-lint`** — a read-only New-PM pass that applies the same eligibility
  rules as the decoy and flattening transforms and reports selected, eligible,
  ineligible and unsupported functions before a transform pipeline runs. It
  names the fail-closed reason (`indirectbr`, EH, coroutine, inline assembly,
  convergent call, and so on) without changing IR. Covered by the
  `aegis-controlflow` CTest and a CI smoke test.
- **Isolation and tool-accounting design** — [`docs/isolation.md`](docs/isolation.md)
  specifies one disposable worker per cell, a workspace-only mount, metered-only
  egress, a harness-owned tool broker with authoritative counters, a separate
  grader process, and the isolation acceptance tests required before a
  protection-effect claim. This is explicitly design, not an implemented
  sandbox.
- **Harness-owned loopback tool broker** — each run starts a token-authenticated
  broker and exports `AEGIS_TOOL_BROKER_URL` / `AEGIS_TOOL_BROKER_TOKEN`.
  Mediated workspace reads, probe execution, disassembly and submission are
  checked against `tool_policy`, confined to the workspace, capped by
  `budgets.max_tool_calls`, and recorded in the row's `tools` block. The
  reference OpenAI-compatible adapter now prefers the broker. A bypass remains
  possible until process isolation; `tools.requests: 0` makes it visible.
- **Optional adapter process boundary** — campaigns can set
  `adapter_isolation: "process"`. The harness re-imports the adapter in a fresh
  child process and passes a workspace-only `TaskView`; the repository task
  root, grader material and object state stay in the parent. This is not yet a
  filesystem/network sandbox, and every row records that distinction.
- **Landlock worker sandbox** — `require_sandbox: true` installs a deny-by-
  default Linux filesystem policy before adapter code runs and allows TCP
  connects only to the per-cell broker/meter ports. Offline tests prove that a
  repo read and an unapproved TCP port are denied. UDP and same-port IP
  targeting remain outside Landlock's scope.
- **Seccomp worker network floor** — libseccomp denies UDP/raw/RDM/SEQPACKET
  IP socket creation before adapter code runs, closing the UDP/DNS and raw
  socket paths that Landlock does not cover. TCP remains subject to the
  broker/meter port allowlist; same-port IP targeting remains open.
- **Real-model sandbox smoke** — [`docs/reports/pilot-2026-11-13-sandbox-smoke/`](docs/reports/pilot-2026-11-13-sandbox-smoke/README.md)
  records an N=1 `packed-record-v1` baseline/level3 run through process
  isolation, Landlock/seccomp, the loopback broker and the meter. Both
  candidates reached grading; relay retries and abandoned calls are recorded.
  It is a smoke, not a comparison or effectiveness claim.
- **Atomic report writes** — JSONL, CSV and Markdown reports are written to a
  temporary file, fsynced and atomically replaced. A killed campaign therefore
  resumes from the previous complete report rather than parsing a truncated
  file.
- **Repeated provider usage chunks are counted once** — some relays repeat the
  terminal SSE usage block. The meter now accepts the first block for a
  request and ignores duplicates, preventing a silent 2x token charge; an
  offline regression test covers it.
- **Clean-tree v0.2 validation evidence** — commit `8757538` produced
  [`docs/reports/harness-validation-v0.2.0-alpha/`](docs/reports/harness-validation-v0.2.0-alpha/README.md)
  with `commit_dirty: no`, 5/5 CTest, the eight-profile differential matrix,
  positive and negative grader controls, a campaign execute/resume/audit path,
  all four artifact profiles for eight public tasks, and a process-worker
  campaign with Landlock filesystem/TCP rules, seccomp UDP/raw-socket denial
  and broker counters; both campaign audits report 0 errors and 0 warnings.
- **Harness-owned token metering** — `--meter-upstream <relay-url>` (or
  `Runner(meter_upstream=...)`) starts a per-run loopback reverse proxy in front
  of the model endpoint and exports it to the adapter as
  `AEGIS_METER_BASE_URL`. For streaming requests the proxy adds
  `stream_options.include_usage` in flight, so the provider reports usage
  whether or not the adapter asked for it; the totals in the row's `metering`
  block are then the **provider's own** report rather than the adapter's
  arithmetic, and `ledger_source` reads `metered by harness` when every request
  carried usage. Verified against the reference relay before being written down
  (injection → `usage` present → 37 prompt / 16 completion tokens counted). The
  proxy forwards status codes unchanged, because an adapter's retry ladder is
  part of the agent under measurement. Three limits are documented rather than
  papered over: it is not a sandbox (bypassing it is possible and shows up as
  `requests: 0`), a provider may ignore `include_usage` (`total_tokens` is then
  `null`, never `0`), and the two measurements are kept side by side so an
  adapter claiming more than the proxy saw is flagged
  (`metering.adapter_exceeds_metered`). 20 offline tests cover injection,
  byte-exact streaming pass-through, absent usage, forwarded 5xx, per-run
  attribution, and the runner path; **the published pilots remain
  self-reported**, since metering did not exist when they ran.
- **Fixed, found by the meter disagreeing with the adapter** — the first
  metered ladder run reported 1.4–1.65× the adapter's figure, and the whole
  gap sat in calls the agent had abandoned mid-stream. The proxy had been
  draining the upstream connection to EOF after the client hung up, which made
  the provider generate ~162 k completion tokens nobody would read (~18 % of
  that run) and charged the abandoned prompts to the run — a bias whose size
  depended on how often each arm aborted, i.e. one that would have moved the
  protection ratio itself. The proxy now closes the upstream call when the
  agent disconnects (`metering.client_disconnects`), which makes a metered
  total a **floor** rather than an overstatement. The four contaminated cells
  were discarded, not published.
- **Statistical-power rules for the benchmark's metrics** — the protocol now
  states which number can carry a result at which N, from measured data rather
  than convention. Success is a Bernoulli per run; the observed level-3 vs
  baseline difference is 3/12 vs 2/11 (Fisher p = 0.55) and resolving it needs
  ~540 runs per arm, so `N >= 5` is a **reporting floor**, not sufficiency, and
  no success-rate effect may be asserted at pilot counts. A case-level secondary
  metric adds no resolution (per-run `success_rate` is 0.0, ≈0.03 or 1.0 — the
  tasks are bimodal). The token-cost ratio is the metric that resolves: 1.91×,
  2.06×, 2.12× across three runs. Wall clock is recorded as latency, never cost,
  because it moves opposite to tokens under `binary` access.
- **Pilot reports distinguish submit calls from graded runs.** A run rescued by
  the final-answer turn has a candidate, a score and a token ledger but no
  `submit_solution` call, and a candidate that fails to compile is graded at
  stage `build`; counting only submit calls made the cost-conditioning warning
  describe runs that did have a cost. Reports now print both, take the cost
  means over graded runs, and print the baseline-relative token ratio as the
  headline number.
- **Task calibration record** — binary-recovery manifests may carry a
  `calibration` object **keyed by access mode** (`oracle`/`binary`), each with
  `status`, `model`, `baseline_pass_rate`, `runs`, `date`. One record per mode
  because a task can be at the floor for a black-box agent and solvable for one
  that can read the binary. The loader rejects a label that contradicts its own
  rate (`floor` with 0.4, `comparison-ready` with 0 or 1) or a calibrated
  record without a model/date/run count. Run rows carry it, reports print it,
  and a report warns when a comparison was run on a task whose unprotected
  baseline is at the floor, at the ceiling, or never calibrated. The record is
  deliberately outside `content_hash`: it is measurement metadata, not task
  semantics. `packed-record-v1` is recorded as `floor` under `oracle` access
  (0/3, `deepseek-v4.1-flash`).
- **`aegis-cff`** — level 2/3 control-flow transforms.
  - Level 2: an input-driven live split at the decoy guard plus 1–2
    opaque-predicate bogus edges backed by `@__aegis.cff.salt` (internal, zero,
    read only through volatile loads).
  - Level 3: level 2 plus control-flow flattening into a volatile state
    machine. PHIs and cross-block SSA values are demoted to stack slots before
    the CFG rewrite; the dispatcher state is stored/loaded through `volatile`
    so `mem2reg`/SROA cannot recover the original CFG at `-O2`.
  - Registered as `aegis-cff`; pipeline order is
    `aegis-policy,aegis-decoys,aegis-cff,default<O2>,aegis-verify`.
- **`aegis-verify` level 2/3 coverage** — salt integrity, per-function volatile
  salt loads, per-function volatile state slots, module-wide counts, and a
  build error for any level>=2 function the transform never recorded.
- **`tests/controlflow`** (CTest `aegis-controlflow`) — semantics, structural
  survival, determinism, PHI demotion, and fail-closed negative controls.
- **Two differential profiles** — `aegis-research` (level 2) and
  `aegis-flattened` (level 3); the matrix is now eight profiles.
- **Docs** — [`docs/controlflow.md`](docs/controlflow.md), updated policy,
  compatibility, threat-model (policy levels vs tier numbers), architecture,
  build profiles and claims ledger (C-003–C-005).
- **Aegis-Bench binary-recovery layer** — tasks can now present a stripped
  probe built from the ground truth at protection levels 0–3. New
  `artifact.py` builder (frontend IR → Aegis pipeline → object → stripped
  probe), per-profile artifact cache, policy/level cross-checks, and probe
  SHA-256 / `.text` / build-log provenance in every run row. `rolling-token-v1`
  is now a binary-recovery task with `baseline` and `aegis-level1..3`
  profiles; its content hash changed.
- **Task set and private custody** — two non-standard binary-recovery tasks
  (`packed-record-v1`, `lane-shift-v1`) whose algorithms are deliberately not
  standard constructions; a `private: true` manifest flag that requires
  `--allow-private`, with custody/rotation rules in
  `benchmarks/tasks-private/README.md` and a do-not-publish report banner.
- **Oracle accounting** — binary-recovery runs place an oracle **shim** in the
  workspace instead of the probe. A harness-owned broker holds the probe,
  counts every query, and enforces an optional `budgets.oracle_queries`;
  `oracle.queries` / `oracle.refused` are measured, not self-reported. This is
  accounting, not a sandbox: an adapter that executes the cached probe directly
  is not counted. It makes the protocol's oracle-budget curve implementable.
- **Report statistics** — Wilson 95% intervals on pass rates, per-(agent,
  profile) aggregates across tasks, and a cost-delta-vs-baseline table with an
  interval once both sides have at least two runs. Wall clock and oracle
  queries are measured; token deltas remain labelled self-reported.
- **Adapter provenance** — run rows carry an `adapter_version` supplied by the
  adapter (the reference adapter reports a hash of its own source), and the
  Markdown report lists the adapters used. A result can now name the exact
  agent implementation that produced it.
- **Reference adapter protocol** — [`docs/reference-adapter.md`](docs/reference-adapter.md)
  specifies the tool set, the parameters a published result must record, the
  streaming/thinking requirements seen on real relays, the recovery policy that
  must be identical across profiles, and a reproduction checklist. Adapters stay
  out of the tree.
- **Harness tests** — 47 offline tests plus shell integration covering
  artifact builds, workspace isolation, missing-plugin failure, level-3
  ground-truth scoring, candidate-source policy, adapter timeouts, oracle
  counting/refusal, and report statistics.
- **Task versioning** — `rolling-token-v2` is the binary-recovery task; the
  frozen `rolling-token-v1` keeps its original id, files and content hash.
- **Isolation hardening** — the grader no longer puts the task root on the
  include path (a candidate could `#include "ground_truth/target.cpp"`),
  compiles and runs in scratch directories with a minimal environment and
  rlimits, and applies a candidate-source policy. `adapter.solve` is bounded
  by a wall-clock timeout, recorded as enforced/not in each row.
- **Report provenance** — host and user names are no longer recorded; a
  salted machine hash replaces them. The `v0.1.0-alpha` report is archived
  under `docs/reports/archive/` so claims keep pointing at the artifact they
  were written against.
- **First real-model pilot** — [`docs/reports/pilot-2026-11-11/`](docs/reports/pilot-2026-11-11/README.md)
  runs `deepseek-v4.1-flash` through `packed-record-v1` (baseline vs
  `aegis-level3`, N=3 each) via an out-of-tree OpenAI-compatible adapter, with
  the run's commit, dirty flag, oracle counts and adapter source hash recorded.
  Both profiles score 0/3; the pilot documents that the path works and that
  this task sits below the model's floor. It is a pilot, not a claim. The
  adapter's operational findings (SSE streaming, reasoning round-trip,
  watchdog policy) are in `docs/reference-adapter.md`; the adapter itself stays
  out of the tree.
- **Second pilot, under `binary` access** — [`docs/reports/pilot-2026-11-12-binary/`](docs/reports/pilot-2026-11-12-binary/README.md):
  `deepseek-v4-pro` on `packed-record-v1`, baseline vs `aegis-level3`, N=2
  each. Both profiles passed 2/2, so this looked like a cost comparison at a
  fixed success criterion: level 3 used ~90% more tokens (822k vs 431k mean).
  **Superseded by the N=5 run below**, which does not reproduce the pass rates;
  the report is kept as published because that is what makes the correction
  legible.
- **N=5 rerun of the same configuration** — [`docs/reports/pilot-2026-11-12-binary-n5/`](docs/reports/pilot-2026-11-12-binary-n5/README.md):
  baseline 1/5, level 3 0/5, both 2/5 submissions, and **6 of 10 runs never
  submitted within 30 steps**. Pass-rate intervals overlap; among the four runs
  that submitted, level 3 used about twice the tokens (900k vs 437k). The
  binding constraint on this task is producing a submission at all, and the
  protection did not move it. The task's binary-access calibration is now
  `comparison-ready` at 0.2 over N=5.

### Changed

- `Runner.run` accepts a `repetition_start`, so a caller that deliberately
  creates a fresh adapter for every cell can still preserve the real
  repetition index in each row. The out-of-tree pilot driver now uses it;
  without this, every cell in a multi-repetition pilot was stamped `0`.
- The control-flow transform and verifier use LLVM 23's `CondBrInst` and
  `UncondBrInst` instead of the deprecated generic `BranchInst` interface.
  Generated IR and eligibility checks are unchanged.
- Protocol and task-set docs now reflect the four public tasks and four
  published real-model pilots instead of describing the pre-pilot state.
- **Binary-recovery access modes** — `--access {oracle,binary}` decides what a
  binary-recovery workspace receives and is stamped in every row. `oracle`
  (default, behaviour unchanged) puts a counted shim in the workspace and keeps
  the probe with the broker; `binary` puts the stripped probe there, as the
  task contract promises and the threat model assumes. This matters more than
  it looks: under `oracle` access the shim behaves identically in every
  artifact profile, so a level-vs-baseline cost delta is **zero by
  construction**. Reports of `oracle` rows now say so next to the numbers, and
  the first pilot is labelled accordingly. Under `binary` access queries are
  not counted (`oracle.queries` is `null`, not `0`); a manifest that sets
  `budgets.oracle_queries` is rejected rather than silently unenforced.
- `kMaxImplementedLevel` is now 3. Levels 1–3 are implemented; the shipped
  `aegis-standard` profile remains level 1.
- A level-3 selection of `indirectbr`, `callbr`, an EH terminator or a
  coroutine **fails the build** with the reason instead of skipping.
- `tests/bench/run.sh` now takes the plugin path (CMake passes it) and runs
  binary-recovery artifact profiles end to end; it asserts that the workspace
  holds the oracle shim rather than the probe binary.
- The artifact builder's empty-input sanity check now only requires exit 0 and
  non-empty stdout. It previously looked for `hash=`, which silently failed
  the builds of tasks whose drivers print a different format.
- `scripts/pilot-report.sh` requires `LLM_API_KEY` only on the path that spends
  model budget; regenerating a report from a run's own JSONL (`REUSE_DATA`)
  needs no key. A pilot's console log is tracked as evidence
  (`!docs/reports/**/run.log`).

### Behaviour worth knowing

- Level 2/3 are still semantics-preserving and compile-time; they are **not**
  the threat model's Tier 2 or Tier 3. The live split makes the executed path
  input-dependent, but the flattening dispatcher is visible to dynamic
  tracing, and the state key derives from the shipped seed.
- The research profiles use seeds 777/778; their `.text` deltas are each
  relative to the shared baseline, not a monotonic ladder.
- Binary-recovery tasks expose the probe through a harness-owned oracle
  broker. Queries are counted and capped when `budgets.oracle_queries` is set,
  but this is accounting, not a sandbox: an adapter that finds the artifact
  cache can query the probe uncounted. A submission that embeds the probe is
  invalid but not automatically detected. Adapters are trusted not to read
  grader material; real runs need process-level isolation. See
  [`docs/benchmark-protocol.md`](docs/benchmark-protocol.md).

### Not claimed

No adversarial effectiveness claim for levels 2/3, and no model-derived claim.
The only `.text` numbers are the synthetic fixture (C-003/C-004). The pilots are
listed as pilots: `pilot-2026-11-11` shows the pipeline runs against a real
model under an access mode that cannot measure protection;
`pilot-2026-11-12-binary` and its N=5 rerun show that this task's binding
constraint is producing a submission at all, with a conditioned token cost
(~2×, n=2 per arm) and no reproducible success-rate difference;
`pilot-2026-11-12-binary-cost` removes that failure mode and gives the
unconditional ratio (level 3 = 2.12× baseline tokens; 1.91×, 2.06×, 2.12× over
three 30-step runs). None of it establishes anything about other tasks, models
or attacker classes. In particular the **absence** of a success-rate signal is
not a null result: at the measured effect size it would take roughly 100–540
runs per arm to detect one, so it is unmeasured, not absent.

## [0.1.0-alpha] — 2026-10-29

First tagged release. **Research prototype, not a hardened protector.** Read
`docs/threat-model.md` and `docs/compatibility.md` before relying on anything
here.

### Added

- **`aegis-audit`** — read-only module/function summary pass; proves the
  plugin, loading and CI path.
- **`aegis-policy`** — JSON policy → `aegis.level` function attributes plus
  `aegis.profile` / `aegis.seed` module flags. Aggregated validation errors,
  selection report on stderr, build failure on unresolved entries.
- **`aegis-decoys`** — first protection transform (Tier 1). Injects a
  dynamically-dead decoy branch guarded by a volatile load of an internal,
  never-written zero, plus 4–6 decoy functions and strings drawn
  deterministically from an in-tree corpus by the module seed.
- **`aegis-verify`** — post-optimization build gate. Fails the build when
  decoy functions, strings, the guard, a guard load, or a guarded function
  disappeared, or when the passes ran out of order.
- **Differential test matrix** — seven build profiles, deterministic corpus
  (235 cases: fixed, boundary, seeded fuzz), stdout/exit comparison against
  baseline, property and sanitizer scanning, and a report with `.text`/`.data`
  totals and p95 wall time.
- **Aegis-Bench harness** — task manifests with content hashes, an independent
  grader (hidden cases + seeded fuzz + property tests), runner with workspace
  isolation and provenance stamps, JSONL/CSV/Markdown reports, offline
  deterministic adapters. One public task, `rolling-token-v1`.
- **Docs** — threat model (C0–C4 adversary tiers), architecture, policy
  reference, build profiles, decoy mechanism, benchmark protocol, CI gates,
  compatibility matrix, claims ledger, release checklist.
- **Release validation report** — `docs/reports/harness-validation/`,
  reproducible via `scripts/release-report.sh`.

### Changed

- Pipeline order is now a documented requirement: the passes run on frontend
  IR (`clang -Xclang -disable-llvm-passes`), with `default<O2>` after
  `aegis-decoys`. Running after inlining protects dead IR and the verifier
  rejects it.

### Behaviour worth knowing

- A policy level above the implemented tier (only 1 today) **fails the
  build**, as does a selected function carrying `optnone`, `naked`, an
  exception-handling personality, or a `musttail` call. Skipping either
  silently would ship a binary the policy claims is protected.
- Bench cost columns (tokens, tool calls) are adapter self-reports; the
  harness labels them as such and cannot corroborate them.

### Not claimed

No effectiveness claim of any kind. The decoys are structurally ineffective
against an analyst with the source; no model has been run against this
release.

[0.2.0-alpha]: https://github.com/jintilm/Aegis-IR/compare/v0.1.0-alpha...v0.2.0-alpha
[0.1.0-alpha]: https://github.com/jintilm/Aegis-IR/releases/tag/v0.1.0-alpha
