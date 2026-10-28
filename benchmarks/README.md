# Benchmark fixtures and task sets

Rules (from `docs/benchmark-protocol.md`):

- **Self-authored synthetic programs only.** No third-party binaries or
  sources are accepted here, for licensing, ground-truth, and safety reasons.
- Every task carries: ground-truth source, property tests, hidden edge cases,
  domain size, and a protectability rating.
- `tasks-private/` content (reference answers, hidden cases, grader config)
  must never be committed to the public repo; it lives in external
  multi-custody storage. This directory only documents its layout.

```text
fixtures/        # tiny programs reused across tasks
tasks-public/    # development tasks (safe to ship)
tasks-private/   # layout notes only; actual content stored separately
```
