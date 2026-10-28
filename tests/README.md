# Tests

Current coverage:

- `policy/` — end-to-end tests for the `aegis-policy` pass (`bash
  tests/policy/run.sh <plugin>`; wired into CTest as `aegis-policy`). Cases:
  selection by mangled name, attribute/module-flag lowering, exactly-one
  annotation, unknown function, out-of-range level, malformed JSON, duplicate
  entries, declaration-only match, demangled-name fallback.

Planned layout (populated as transforms land):

- `unit/` — pass-level tests (lit/FileCheck for IR structure).
- `integration/` — build a fixture with and without protection, run both.
- `differential/` — behavioural equivalence: exit code, stdout/stderr,
  file outputs, API results across a fixed input corpus plus fuzzed inputs.

Every transform PR must add differential coverage. A transform that cannot be
enabled in `aegis-debug` without changes must explain why.

Running everything (inside the pinned container):

```bash
cmake --build build -j && ctest --test-dir build --output-on-failure
```