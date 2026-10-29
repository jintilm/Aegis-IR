# Changelog

All notable changes to this project. Format loosely follows Keep a Changelog;
versions follow SemVer once past alpha.

## [Unreleased]

Nothing yet.

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
