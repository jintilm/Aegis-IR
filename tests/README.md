# Tests

Planned layout (populated as transforms land):

- `unit/` — pass-level tests (lit/FileCheck for IR structure, CTest for the
  tool surface).
- `integration/` — build a fixture with and without protection, run both.
- `differential/` — behavioural equivalence: exit code, stdout/stderr,
  file outputs, API results across a fixed input corpus plus fuzzed inputs.

Every transform PR must add differential coverage. A transform that cannot be
enabled in `aegis-debug` without changes must explain why.
