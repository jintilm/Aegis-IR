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
├── artifact.py  build a stripped probe per protection profile
├── agent.py     adapter contract (no network, no credentials in-tree)
├── grader.py    independent grader: compile + differential execution
├── runner.py    workspace isolation, artifact injection, provenance
├── report.py    JSONL / CSV / Markdown reports
├── adapters/    offline deterministic adapters (test doubles)
└── cli.py       `hash`, `check`, `run`
tests/
└── test_harness.py   24 offline tests; no model, no network, no keys
```

## Usage

```bash
cd tools/aegis-bench

# validate every task manifest and verify its content hash
python3 -m aegis_bench check --tasks-root ../../benchmarks/tasks-public

# after editing a task, re-record its hash
python3 -m aegis_bench hash ../../benchmarks/tasks-public/rolling-token-v1

# smoke-run the offline negative control (baseline artifact build)
python3 -m aegis_bench run --tasks-root ../../benchmarks/tasks-public \
    --adapter stub --profile baseline --out /tmp/bench

# build a protected probe and score a known-correct answer
python3 -m aegis_bench run --tasks-root ../../benchmarks/tasks-public \
    --adapter ground-truth --profile aegis-level3 \
    --plugin ../../build/lib/AegisPass.so --out /tmp/bench-l3
```

A real run passes an adapter that lives **outside** this repository:

```bash
python3 -m aegis_bench run --tasks-root ../../benchmarks/tasks-public \
    --adapter my_adapters.claude:C1Static --profile aegis-level2 \
    --plugin build/lib/AegisPass.so \
    --repetitions 5 --out bench-out/v0.2
```

Credentials are read by that external adapter; nothing in this tree imports a
vendor SDK, opens a socket, or reads an API key. The adapter must be run in an
environment whose filesystem view contains only the workspace; the harness
enforces workspace isolation, not process sandboxing.

Binary-recovery tasks need `clang++-23` and `opt-23` (override with
`--clang` / `--opt` or `BENCH_CLANG` / `BENCH_OPT`); profiles at level >= 1
also need the plugin (`--plugin` or `AEGIS_PLUGIN`). Built probes are cached
under `<out>/.artifacts`; pass `--artifact-cache DIR` to keep binaries out of
a report directory.

## Task layout

```
benchmarks/tasks-public/<task-id>/
├── task.json            # manifest, includes the content hash
├── task.md              # agent-visible brief
├── include/target.h     # agent-visible interface
├── examples/            # agent-visible sample I/O (must be real outputs)
├── ground_truth/        # grader-only reference implementation
└── grader/              # grader-only driver, property tests, hidden cases
    └── policies/        # artifact profiles (level 1..3), grader-only
```

`visible/` in the manifest is the *only* thing copied into the agent
workspace. The runner resolves and re-checks each path, so a symlink cannot
leak ground truth into the workspace. Tests assert this explicitly.

For `task_type: binary-recovery`, the manifest also names an artifact recipe
(`source`, `probe`, `include_dirs`, `profiles`). The runner builds a stripped
probe per profile, puts **only** that binary in the workspace, and records its
SHA-256, `.text` size and build log. The probe is built from the ground truth
with the same optimization pipeline as the profile, so a level-3 run is
genuinely flattening the code the agent reverses.

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
that caveat next to the numbers. Probe queries in binary-recovery tasks are
equally unobservable. A future adapter protocol can add harness-observable
counters (e.g. tool calls made through a sandboxed tool proxy); until then,
treat cost columns as the adapter's claim.

## Provenance

Every row carries: run id, task id and content hash, adapter name, adversary
class, profile, repetition, UTC start time, duration, full budget config, an
environment stamp (git commit, dirty flag, Python version, platform), and —
for binary-recovery tasks — the probe's SHA-256, file and `.text` sizes,
toolchain, and build log. A task edited after its hash was recorded fails
`check`, so a result cannot silently refer to a different task than the one
that was run.

## Deliberate limits

- One public task today (`rolling-token-v1`). A benchmark with one task
  measures nothing; treat current numbers as harness validation only.
- No model adapters in-tree, by design.
- The probe is an unconstrained local oracle; the protocol's query-budget
  curve is not implemented yet.
- A submission that embeds or wraps the probe is invalid but not detected
  automatically; review and cost anomalies are the current mitigation.
- Windows support is incidental (used for development); CI and reported
  numbers run on Linux.
- The run report is machine-written and not peer-reviewed; it is evidence
  for the claims ledger, not a substitute for it.
