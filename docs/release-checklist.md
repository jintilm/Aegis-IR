# Release checklist

Run before every tagged release. Copy into the release PR description and
record the outcome next to each line — an unchecked box with no explanation is
a blocker, and a box checked without evidence is worse.

## Build and tests

- [x] Clean-environment build succeeds (container from `docker/dev.Dockerfile`).
      Verified for `v0.2.0-alpha` in the pinned container (`5/5` CTest,
      291.55 s).
- [x] All CTest suites pass: `aegis-policy`, `aegis-decoys`,
      `aegis-controlflow`, `differential`, `aegis-bench`.
- [x] Binary-recovery probe builds at levels 0–3 and the level-3 build log
      shows flattening + verifier OK (`aegis-bench` integration test).
- [x] Differential matrix: zero output mismatches, zero sanitizer reports on
      all eight profiles (`differential-report.json`).
- [x] Grader isolation: candidate include path excludes the task root;
      compile/run use scratch directories, minimal environment and rlimits;
      the candidate-source policy rejects oracle replay tripwires (tests).
- [x] Task ids are immutable: `rolling-token-v1` is frozen at its original
      content hash; the binary-recovery task ships as `rolling-token-v2`.
- [x] `clang-format --dry-run -Werror` clean (CI).
- [x] Size/time numbers recorded: `.text` 5023 → 6132 bytes (+22.1%) for
      level 1, 5672 (+12.9%) for level 2 and 6642 (+32.2%) for level 3 on the
      fixture; p95 per-profile in `differential-report.json`. The +10% / +5%
      figures in `docs/build-profiles.md` are engineering targets, not gates —
      the protected profiles exceed the size target and say so in the claims
      ledger (C-001/C-003/C-004) rather than hiding it.
- [x] At least one reproducible report linked from release notes:
      `docs/reports/harness-validation/`.
- [x] Campaign orchestration is covered end to end: the offline manifest runs,
      resumes without duplicating its cell, and passes `aegis-bench audit`
      (`tests/bench/run.sh` + `test_campaign.py`).
- [x] Task schema v2 is accepted, v1 remains readable as legacy, and every run
      row carries `task_protocol` plus campaign provenance.
- [x] `aegis-lint` reports eligible and ineligible selections without changing
      IR (`aegis-controlflow` + CI smoke test).
- [x] Harness-owned loopback tool broker enforces the declared tool set,
      workspace containment and call cap for mediated requests; covered by
      `test_toolbroker.py`.
- [x] Optional process-isolated adapter worker receives a workspace-only
      `TaskView`, not the repository task root; covered by `test_worker.py`.
- [ ] Filesystem/network isolation around the adapter worker. The broker
      remains bypassable until the worker cannot directly read the repository
      or open arbitrary network connections.
- [x] Clean-tree `v0.2.0-alpha` validation report generated from commit
      `4782ea7`: `docs/reports/harness-validation-v0.2.0-alpha/`. The rows
      record `commit_dirty: no`; campaign audit reports 0 errors and 0
      warnings.

## Claims and honesty

- [x] README claims each link to a claims-ledger entry (C-001–C-005).
- [x] No claim implies protection against C2+ attackers beyond measured data —
      in fact no effectiveness claim of any kind is made.
- [x] Known limitations in `docs/threat-model.md`, `docs/decoys.md` and
      `docs/controlflow.md` are current.
- [x] Unsupported selections fail the build (levels outside `0..3`, `optnone`,
      `naked`, EH personality, `musttail`, and level-3 `indirectbr`/`callbr`/
      coroutine/EH terminators) and are tested.

## Legal and identity

- [x] LICENSE is the canonical Apache-2.0 plus LLVM exception.
- [x] Third-party dependencies: LLVM/Clang (Apache-2.0 WITH LLVM-exception),
      Python stdlib, CMake/Ninja (build only). No vendored code.
- [x] No keys, tokens, private sources, or hidden grading answers in the repo
      (CI hygiene gate + manual scan).
- [x] Reports contain no host or user names; provenance uses a salted machine
      hash.
- [ ] Trademark search; GitHub org, domain, and package names secured.
      **Outstanding** — tracked as release follow-up, not a code blocker.
- [x] README name disclaimer present (IR = Intermediate Representation).

## Safety

- [x] No sandbox-switching, anti-debug-to-fail, or evasion-oriented features
      enabled by default — or implemented at all.
- [x] `aegis-debug` profile documented as the supported debugging path.

## Packaging

- [x] Version bumped (`include/aegis/AegisVersion.h` = 0.2.0-alpha) and
      `CHANGELOG.md` written.
- [x] Checksums published with the release artifacts (`scripts/package.sh`
      writes `SHA256SUMS`).
- [x] Unsupported feature combinations fail loudly, never silently
      (`docs/compatibility.md`).
