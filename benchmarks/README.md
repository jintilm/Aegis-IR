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
| [`rolling-token-v2`](tasks-public/rolling-token-v2/task.md) | small | recover the same standard constructions from a binary probe | binary-recovery, but memorizable; not suitable for a protection comparison |
| [`packed-record-v1`](tasks-public/packed-record-v1/task.md) | small | recover bit-field extraction, a nibble-substitution fold, and a length-dependent rule from a binary probe | comparison-ready under `binary` access after calibration |
| [`lane-shift-v1`](tasks-public/lane-shift-v1/task.md) | small | recover a deliberately non-standard lane transformation from a binary probe | binary-recovery; no published comparison pilot yet |
| [`window-parser-v1`](tasks-public/window-parser-v1/task.md) | small | recover a tagged rolling parser with truncation and early termination | binary-recovery; needs model calibration |
| [`state-fold-v1`](tasks-public/state-fold-v1/task.md) | small | recover a token-dependent 64-bit state transition and rolling digest | binary-recovery; needs model calibration |
| [`ring-drain-v1`](tasks-public/ring-drain-v1/task.md) | small | recover command-driven ring-buffer overwrite, drain and reset semantics | binary-recovery; needs model calibration |
| [`grid-route-v1`](tasks-public/grid-route-v1/task.md) | small | recover an input-derived 8x8 reachability and route encoding | binary-recovery; needs model calibration |

Eight tasks are still not a benchmark. They now cover parser, state-machine,
data-structure and graph-routing families, but published cost-delta numbers
still require model calibration and the full matrix described in the protocol.

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
3. Fill in the schema-v2 `task.json`: budgets, protectability, experiment use,
   difficulty, input domain and the declared `tool_policy`.
4. `python3 -m aegis_bench hash <task-dir>`, then `check`.
5. Confirm the ground truth scores 100% and a deliberately wrong but
   compiling candidate scores ~0% — the harness test does both for the
   existing task and should be extended when you add one.
