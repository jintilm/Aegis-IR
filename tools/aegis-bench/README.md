# Aegis-Bench (main product)

A reproducible benchmark for the *cost* of AI-assisted reverse engineering.
The measured quantity is the cost delta an agent pays (tokens, tool calls,
wall clock) to reach a fixed success criterion on a task, with and without a
protection profile. "Can the AI be defeated" is not a metric.

Protocol: [`docs/benchmark-protocol.md`](../../docs/benchmark-protocol.md).
This README documents what is implemented today.

## What exists

```text
aegis_bench/
├── schema.py    task manifests: parsing, validation, content hashing
├── agent.py     adapter contract (no network, no credentials in-tree)
├── grader.py    independent grader: compile + differential execution
├── runner.py    workspace isolation, run records, provenance
├── report.py    JSONL / CSV / Markdown reports
├── adapters/    offline deterministic adapters (test doubles)
└── cli.py       `hash`, `check`, `run`
tests/
└── test_harness.py   13 offline tests; no model, no network, no keys
```

## Usage

```bash
cd tools/aegis-bench

# validate every task manifest and verify its content hash
python3 -m aegis_bench check --tasks-root ../../benchmarks/tasks-public

# after editing a task, re-record its hash
python3 -m aegis_bench hash ../../benchmarks/tasks-public/rolling-token-v1

# smoke-run the offline negative control
python3 -m aegis_bench run --tasks-root ../../benchmarks/tasks-public \
    --adapter stub --profile baseline --out /tmp/bench
```

A real run passes an adapter that lives **outside** this repository:

```bash
python3 -m aegis_bench run --tasks-root ../../benchmarks/tasks-public \
    --adapter my_adapters.claude:C1Static --profile aegis-standard \
    --repetitions 5 --out bench-out/v0.2
```

Credentials are read by that external adapter; nothing in this tree imports a
vendor SDK, opens a socket, or reads an API key.

## Task layout

```
benchmarks/tasks-public/<task-id>/
├── task.json            # manifest, includes the content hash
├── task.md              # agent-visible brief
├── include/target.h     # agent-visible interface
├── examples/            # agent-visible sample I/O (must be real outputs)
├── ground_truth/        # grader-only reference implementation
└── grader/              # grader-only driver, property tests, hidden cases
```

`visible/` in the manifest is the *only* thing copied into the agent
workspace. The runner resolves and re-checks each path, so a symlink cannot
leak ground truth into the workspace. Tests assert this explicitly.

`hidden_cases/` accepts either raw binary files (one case each) or a
`{"cases": ["<hex>", ...]}` JSON document. Hex is used rather than base64 so
the corpus diffs cleanly in review.

## Scoring

A run is `passed` when the candidate binary agrees with the reference on
**every** case:

- every hidden case, and
- a fuzz corpus of `fuzz.cases` seeded byte strings (seed and max length come
  from the manifest, so the corpus is reproducible).

`PROPERTY FAIL` lines from the task's property tests are treated as failures
regardless of the differential result. Property tests check structural facts
that hold for any correct implementation, which is what stops a candidate
from passing by hard-coding the visible examples.

Failure stages are recorded separately (`build`, `hidden`, `fuzz`, `agent`) so
a report can distinguish "did not compile" from "wrong on edge case".

## Cost accounting, honestly

The harness measures pass/fail and case counts itself. It **cannot** observe
token usage or tool calls: those come from the adapter and are recorded with
`ledger_source: "self-reported by adapter"`, and the Markdown report repeats
that caveat next to the numbers. A future adapter protocol can add
harness-observable counters (e.g. tool calls made through a sandboxed tool
proxy); until then, treat cost columns as the adapter's claim.

## Provenance

Every row carries: run id, task id and content hash, adapter name, adversary
class, profile, repetition, UTC start time, duration, full budget config, and
an environment stamp (git commit, dirty flag, Python version, platform). A
task edited after its hash was recorded fails `check`, so a result cannot
silently refer to a different task than the one that was run.

## Deliberate limits

- One public task today (`rolling-token-v1`). A benchmark with one task
  measures nothing; treat current numbers as harness validation only.
- No model adapters in-tree, by design.
- Windows support is incidental (used for development); CI and reported
  numbers run on Linux.
- The run report is machine-written and not peer-reviewed; it is evidence
  for the claims ledger, not a substitute for it.
