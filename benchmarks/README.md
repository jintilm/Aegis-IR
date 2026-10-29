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

## tasks-public

| Task | Domain | What it asks | Status |
|---|---|---|---|
| [`rolling-token-v1`](tasks-public/rolling-token-v1/task.md) | small | recover FNV-1a hash, Adler-32 checksum, and a `hash % 97` token predicate from sample I/O | harness validation only |

One task is not a benchmark. These exist so the harness has something
end-to-end to run and so the *format* is exercised; published cost-delta
numbers require the full matrix described in the protocol.

## Harness

The runner and grader live in [`tools/aegis-bench`](../tools/aegis-bench/README.md).
Validate the whole set with:

```bash
cd tools/aegis-bench
python3 -m aegis_bench check --tasks-root ../../benchmarks/tasks-public
```

Editing any task file invalidates its `content_hash`; re-record it with
`python3 -m aegis_bench hash <task-dir>` and commit the manifest change
together with the edit.

## Adding a task

1. Write the interface, brief and real sample I/O that the agent may see.
2. Write ground truth, a driver, property tests and hidden cases.
3. Fill in `task.json`, including budgets and protectability metadata.
4. `python3 -m aegis_bench hash <task-dir>`, then `check`.
5. Confirm the ground truth scores 100% and a deliberately wrong but
   compiling candidate scores ~0% — the harness test does both for the
   existing task and should be extended when you add one.
