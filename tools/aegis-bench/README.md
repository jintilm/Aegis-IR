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
├── oracle.py    query broker + workspace shim (counts/caps oracle calls)
├── agent.py     adapter contract (no network, no credentials in-tree)
├── grader.py    independent grader: compile + differential execution
├── runner.py    workspace isolation, artifact injection, provenance
├── report.py    JSONL / CSV / Markdown reports
├── adapters/    offline deterministic adapters (test doubles)
└── cli.py       `hash`, `check`, `run`
tests/
└── test_harness.py   offline tests; no model, no network, no keys
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
enforces workspace isolation, not process sandboxing. `adapter.solve` is
bounded by `--adapter-timeout` (default 600 s, SIGALRM on POSIX).

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
probe per profile and starts an **oracle broker** that holds it. The workspace
receives only a `probe` shim that forwards stdin to the broker, which counts
every query and enforces `budgets.oracle_queries` when set. The run row
records the probe's SHA-256, `.text` size and build log, plus the broker's
served/refused counts. The probe is built from the ground truth with the same
optimization pipeline as the profile, so a level-3 run is genuinely flattening
the code the agent reverses.

The shim is a small stdlib-Python program, so the agent environment needs
`python3` on `PATH` (the harness itself already does). On Windows the runner
also writes a `probe.cmd` launcher beside it; reported numbers come from
Linux, where `probe` is directly executable.

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

The harness measures pass/fail, case counts, wall clock and — for
binary-recovery tasks — oracle queries. The broker sees the queries because
the workspace holds a shim, not the probe. It **cannot** observe token usage
or tool calls: those come from the adapter and are recorded with
`ledger_source: "self-reported by adapter"`, and the Markdown report repeats
that caveat next to the numbers.

The broker is accounting, not a sandbox. An adapter that walks the filesystem
can find the artifact cache and execute the probe directly; nothing would
count that. Reports say so. A future adapter protocol can add harness-visible
counters for tool calls too (e.g. a sandboxed tool proxy).

The Markdown report states a Wilson 95% interval on every pass rate, aggregates
per (agent, profile), and shows cost deltas against the `baseline` profile with
an interval once both sides have at least two runs. With one run it prints
`(n<2)` rather than inventing a spread.

## Provenance

Every row carries: run id, task id and content hash, adapter name, adversary
class, profile, repetition, UTC start time, duration, full budget config, an
environment stamp (git commit, dirty flag, Python version, platform), and —
for binary-recovery tasks — the probe's SHA-256, file and `.text` sizes,
toolchain, and build log. A task edited after its hash was recorded fails
`check`, so a result cannot silently refer to a different task than the one
that was run.

## Deliberate limits

- Four public tasks today: `rolling-token-v1` (reimplementation, frozen),
  `rolling-token-v2` (binary-recovery, memorizable FNV/Adler) and two
deliberately non-standard binary-recovery tasks (`packed-record-v1`,
  `lane-shift-v1`). Four is still far too few for a claim; treat current
  numbers as harness validation only.
- No model adapters in-tree, by design.
- Oracle queries are counted and optionally capped by the broker, but the
  broker is not a sandbox; a direct probe invocation is uncounted. The
  protocol's oracle-budget curve is now implementable, not yet measured.
- A submission that embeds or wraps the probe is invalid. The obvious forms
  are rejected by the source policy (size, `exec*`, grader paths); a hidden
  blob is not automatically detectable, so review is still required.
- Windows support is incidental (used for development); CI and reported
  numbers run on Linux.
- The run report is machine-written and not peer-reviewed; it is evidence
  for the claims ledger, not a substitute for it.
