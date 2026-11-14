# Release checklist

Run before every tagged release. Copy into the release PR description and
record the outcome next to each line — an unchecked box with no explanation is
a blocker, and a box checked without evidence is worse.

## Build and tests

- [x] Clean-environment build succeeds (container from `docker/dev.Dockerfile`).
      Verified for the schema-v4/double-scorecard candidate in the pinned
      container; the final clean-tree report completed 8/8 CTest in 900.82 s.
- [x] All CTest suites pass: `aegis-policy`, `aegis-decoys`,
      `aegis-controlflow`, `differential`, `differential-representative`,
      `protection-scorecard`, `protection-scorecard-representative`,
      `aegis-bench` (8/8).
- [x] Binary-recovery probe builds at levels 0–3 and the level-3 build log
      shows flattening + verifier OK (`aegis-bench` integration test).
- [x] Differential matrix: zero output mismatches, zero sanitizer reports on
      all eight profiles (`differential-report.json`).
- [x] Deterministic protection scorecard passes the default-profile budgets:
      fixture correctness, `.text` <= 25%, paired relative p95 <= 25% and
      build-time median <= 25%; representative correctness, `.text` <= 30%,
      paired relative p95 <= 25% and build-time median <= 30%. Both arms
      require at least three independent clean-build samples
      (`scorecard.json`/`.md`, `scorecard-representative.json`/`.md`).
- [x] Grader isolation: candidate include path excludes the task root;
      compile/run use scratch directories, minimal environment and rlimits;
      the candidate-source policy rejects oracle replay tripwires (tests).
- [x] Task ids are immutable: `rolling-token-v1` is frozen at its original
      content hash; the binary-recovery task ships as `rolling-token-v2`.
- [x] `clang-format --dry-run -Werror` clean (CI).
- [x] Size/time numbers recorded: `.text` 5023 → 6132 bytes (+22.1%) for
      level 1, 5672 (+12.9%) for level 2 and 6642 (+32.2%) for level 3 on the
      fixture; per-profile p95 and three build medians are in
      `differential-report.json`. Budgets live in
      `experiments/protection-budgets*.json`; the protected profiles' observed
      costs are recorded in the claims ledger (C-001/C-003/C-004) rather than
      hidden.
- [x] At least one reproducible report linked from release notes:
      final clean-tree report at `docs/reports/harness-validation-final/`.
- [x] Campaign orchestration is covered end to end: the offline manifest runs,
      resumes without duplicating its cell, and passes `aegis-bench audit`
      (`tests/bench/run.sh` + `test_campaign.py`).
- [x] Task schema v4 requires `tier: core|exploratory`; v1-v3 remain readable
      and default to `exploratory`. Every run row carries `task_protocol` with
      the tier plus campaign provenance. Calibration is keyed by access mode
      and model.
- [x] Twelve public tasks are split six `core` / six `exploratory`; all eleven
      binary-recovery tasks have explicit calibration records for both pilot
      models. Six are `uncalibrated`, four have N=1 screening records, and only
      `packed-record-v1` is N=5 `comparison-ready` for both models. No N=1
      record is described as N=5 evidence.
- [x] `aegis-lint` reports eligible and ineligible selections without changing
      IR (`aegis-controlflow` + CI smoke test).
- [x] Harness-owned loopback tool broker enforces the declared tool set,
      workspace containment and call cap for mediated requests; covered by
      `test_toolbroker.py`.
- [x] Optional process-isolated adapter worker receives a workspace-only
      `TaskView`, not the repository task root; covered by `test_worker.py`.
- [x] Linux Landlock worker policy restricts filesystem access to the
      workspace/runtime allowlist and permits TCP connects only to the
      broker/meter ports; tests deny a repo read and an unapproved TCP port.
- [x] Seccomp worker policy denies UDP/raw/RDM/SEQPACKET IP socket creation;
      the UDP denial is covered by `test_worker.py`.
- [x] Full network-namespace egress isolation. The worker runs under
      `unshare` with only loopback; a host listener is unreachable, while the
      broker and meter remain available through per-run Unix-socket bridges.
      Covered by `test_worker.py`, `tests/bench/run.sh` and the network
      namespace release campaign.
- [x] Optional dual-model research support exists (schema v2 options, worker
      replay, `agent_config`), but model campaigns are not run for ordinary
      releases. No new attack matrix is required from the release checklist.
- [x] Clean-tree final validation report is required at
      `docs/reports/harness-validation-final/`, generated only after the code
      and documentation commit `921c0e2`. It records 8/8 CTest in 900.82 s,
      both differential reports, both passing scorecards, and offline,
      process and network-namespace campaign audits with 0 errors and
      0 warnings. The network-namespace row records process isolation,
      Landlock/seccomp, a private namespace, and 3 broker-measured calls.

## Claims and honesty

- [x] README claims each link to a claims-ledger entry (C-001–C-007).
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

- [x] Version bumped (`include/aegis/AegisVersion.h` = 0.3.0-alpha) and
      `CHANGELOG.md` written.
- [x] Checksums published with the release artifacts (`scripts/package.sh`
      writes `SHA256SUMS`).
- [x] Unsupported feature combinations fail loudly, never silently
      (`docs/compatibility.md`).
