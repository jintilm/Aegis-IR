# Changelog

All notable changes to this project. Format loosely follows Keep a Changelog;
versions follow SemVer once past alpha.

## [Unreleased]

### Added

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

[Unreleased]: https://github.com/jintilm/Aegis-IR/compare/v0.1.0-alpha...HEAD
[0.1.0-alpha]: https://github.com/jintilm/Aegis-IR/releases/tag/v0.1.0-alpha
