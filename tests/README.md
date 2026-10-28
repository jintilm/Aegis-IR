# Tests

Current coverage:

- `policy/` — end-to-end tests for the `aegis-policy` pass (`bash
  tests/policy/run.sh <plugin>`; wired into CTest as `aegis-policy`). Cases:
  selection by mangled name, attribute/module-flag lowering, exactly-one
  annotation, unknown function, out-of-range level, malformed JSON, duplicate
  entries, declaration-only match, demangled-name fallback.
- `differential/` — build-profile matrix over an offline-library fixture
  (`python3 tests/differential/run.py --plugin <plugin>`; CTest name
  `differential`). Six profiles, deterministic corpus (fixed + boundary +
  seeded fuzz), stdout/exit-code comparison against baseline, property and
  sanitizer scanning, size/time baseline report. See
  [`docs/build-profiles.md`](../docs/build-profiles.md).

Planned layout (populated as transforms land):

- `unit/` — pass-level tests (lit/FileCheck for IR structure).
- integration tests beyond the fixture matrix.

Every transform PR must add differential coverage. A transform that cannot be
enabled in `aegis-debug` without changes must explain why.

Running everything (inside the pinned container):

```bash
cmake --build build -j && ctest --test-dir build --output-on-failure
```