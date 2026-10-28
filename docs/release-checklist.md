# Release checklist

Run before every tagged release. Copy into the release PR description.

## Build and tests

- [ ] Clean-environment build succeeds (container from `docker/dev.Dockerfile`).
- [ ] All CTest unit/integration tests pass.
- [ ] Differential tests: zero regressions on the default profile.
- [ ] `clang-format --dry-run -Werror` clean.
- [ ] Performance and size gates recorded (default profile: p95 <= +5%,
      binary size <= +10% — starting engineering targets, explained if missed).
- [ ] At least one reproducible benchmark report linked from the release notes.

## Claims and honesty

- [ ] README claims each link to a claims-ledger entry (commit, model
      versions, date, repro command).
- [ ] No claim implies protection against C2+ attackers beyond measured data.
- [ ] All known limitations in `docs/threat-model.md` are current.

## Legal and identity

- [ ] LICENSE text is the canonical Apache-2.0 plus LLVM exception.
- [ ] Third-party dependency licenses checked.
- [ ] No keys, tokens, private sources, or hidden grading answers in the repo.
- [ ] Trademark search done; GitHub org, domain, and PyPI names
      (`aegis-ir`, `aegis-bench`) secured.
- [ ] README name-disclaimer present (IR = Intermediate Representation).

## Safety

- [ ] No sandbox-switching, anti-debug-to-fail, or evasion-oriented features
      enabled by default (or at all).
- [ ] `aegis-debug` profile builds and reproduces protected programs.

## Packaging

- [ ] Version numbers bumped (`include/aegis/AegisVersion.h`).
- [ ] Release artifacts have checksums.
- [ ] Unsupported feature combinations fail loudly, never silently.