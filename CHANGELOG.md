# Changelog

All notable changes to this project. Format loosely follows Keep a Changelog;
versions follow SemVer once past alpha.

## [Unreleased]

### Added

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
- **Harness tests** — 46 offline tests plus shell integration covering
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

### Changed

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

No adversarial effectiveness claim for levels 2/3, and no model result for the
benchmark. The only numbers are `.text` growth and output equality on the
synthetic fixture (C-003/C-004).

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
