# Tests

Current coverage:

- `policy/` — end-to-end tests for the `aegis-policy` pass (`bash
  tests/policy/run.sh <plugin>`; wired into CTest as `aegis-policy`). Cases:
  selection by mangled name, attribute/module-flag lowering, exactly-one
  annotation, unknown function, out-of-range level, malformed JSON, duplicate
  entries, declaration-only match, demangled-name fallback.
- `decoys/` — end-to-end tests for `aegis-decoys` + `aegis-verify` (`bash
  tests/decoys/run.sh <plugin>`; CTest name `aegis-decoys`). Cases: artifacts
  survive `-O2`, guard load survives, the verify gate passes and fails in the
  right situations, level-0 functions untouched, determinism, seed
  sensitivity, inlining behaviour. See [`docs/decoys.md`](../docs/decoys.md).
- `controlflow/` — end-to-end tests for `aegis-cff` at levels 2/3 (`bash
  tests/controlflow/run.sh <plugin>`; CTest name `aegis-controlflow`). Cases:
  pipelines build and verify, salt loads and volatile state slots survive
  `-O2`, output matches baseline, determinism, PHI demotion, the gate failing
  when cff is skipped / state or salt loses `volatile` / decoys are skipped,
  and level 3 rejecting `indirectbr`. See
  [`docs/controlflow.md`](../docs/controlflow.md).
- `differential/` — build-profile matrix over an offline-library fixture
  (`python3 tests/differential/run.py --plugin <plugin>`; CTest name
  `differential`). Eight profiles, deterministic corpus (fixed + boundary +
  seeded fuzz), stdout/exit-code comparison against baseline, property and
  sanitizer scanning, size (`bytes`, `.text`, `.data`) and p95-time baseline
  report. Protected profiles run the full pipeline
  `aegis-policy<...>,aegis-decoys,aegis-cff,default<O2>,aegis-verify` on
  frontend IR. See [`docs/build-profiles.md`](../docs/build-profiles.md),
  [`docs/decoys.md`](../docs/decoys.md) and
  [`docs/controlflow.md`](../docs/controlflow.md).

- `differential/suites/representative/` — larger algorithm workload with at
  least 1 MiB of work per invocation (CTest name
  `differential-representative`). It runs the baseline, standard, research and
  flattened profiles over a deterministic 75-case corpus (fixed, boundary and
  40 seeded fuzz inputs) and feeds the calibrated representative scorecard.

- `protection-scorecard*` — deterministic engineering gates. The fixture gate
  checks the small regression workload; the representative gate uses the
  calibrated larger workload. Both require zero mismatches, zero
  sanitizer/property errors, and at least three build samples in each arm.

- `bench/` — Aegis-Bench harness tests (`bash tests/bench/run.sh
  tools/aegis-bench <plugin>`; CTest name `aegis-bench`). Offline only:
  deterministic adapters, no model, no network, no credentials. Covers the
  ground truth scoring 100%, a compiling-but-wrong candidate failing, adapter
  crashes being recorded, hash-tamper rejection, workspace exclusion of grader
  material, report provenance, and binary-recovery artifact builds at levels
  0–3 (probe hash/`.text`, workspace contains only the stripped probe, the
  level-3 build log shows flattening). See
  [`tools/aegis-bench/README.md`](../tools/aegis-bench/README.md).

Planned layout (populated as transforms land):

- `unit/` — pass-level tests (lit/FileCheck for IR structure).
- integration tests beyond the fixture matrix.

Every transform PR must add differential coverage. A transform that cannot be
enabled in `aegis-debug` without changes must explain why.

Running everything (inside the pinned container):

```bash
cmake --build build -j && ctest --test-dir build --output-on-failure
```
