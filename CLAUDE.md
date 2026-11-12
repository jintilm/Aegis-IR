# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

Two products in one repo:

1. **Aegis-Bench** (`tools/aegis-bench/`, `benchmarks/`) — the main product: a reproducible
   benchmark measuring the *cost delta* an AI agent pays to recover a binary's semantics with
   and without a protection profile. "Can the AI be defeated" is explicitly not a metric.
2. **Aegis-IR** (`lib/`, `include/`) — an LLVM New-PM obfuscation pass plugin, the subject
   under test. Also a companion deliverable.

Read `docs/threat-model.md` and `docs/claims-ledger.md` before changing any claim, number, or
README wording. Numbers without a report and a ledger entry are removed.

## Environment and commands

Linux x86-64, LLVM/Clang 23.x pinned, CMake ≥ 3.20, Ninja, C++17. The published numbers come
from the pinned container; use it rather than a host toolchain.

```bash
docker build -t aegis-ir-dev docker/
docker run --rm -it -v "$PWD:/src" -w /src aegis-ir-dev   # on Windows: MSYS_NO_PATHCONV=1

# inside the container
export LLVM_DIR=$(llvm-config-23 --cmakedir)
cmake -S . -B build -G Ninja -DLLVM_DIR=$LLVM_DIR -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
ctest --test-dir build --output-on-failure
ctest --test-dir build -R aegis-controlflow --output-on-failure   # single suite
```

Bench harness (stdlib Python only; no network, no model in tests):

```bash
cd tools/aegis-bench
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s tests -k Grader -v      # single test class/pattern
python3 -m aegis_bench check --tasks-root ../../benchmarks/tasks-public
python3 -m aegis_bench hash <task-dir>                 # re-record content hash after edits
python3 -m aegis_bench run --tasks-root ../../benchmarks/tasks-public \
    --task rolling-token-v2 --adapter ground-truth --profile baseline \
    --plugin ../../build/lib/AegisPass.so --out /tmp/bench
# protection comparisons need the binary in the workspace, not the shim:
python3 -m aegis_bench run ... --access binary

# multi-cell runs use the harness-owned campaign, then audit the raw JSONL
python3 -m aegis_bench campaign --config ../../experiments/offline-smoke.json
python3 -m aegis_bench audit ../../bench-out/offline-smoke \
    --experiment ../../experiments/offline-smoke.json
```

Reports are generated, never hand-edited:

```bash
scripts/release-report.sh harness-validation        # offline controls + full CTest
ADAPTERS_DIR=/path/to/out-of-tree/adapters LLM_API_KEY=... \
  scripts/pilot-report.sh pilot-YYYY-MM-DD          # real-model pilot (never in CI)
```

## Pass pipeline invariants

- The pipeline order is load-bearing:
  `aegis-policy<policy=FILE>,aegis-decoys[,aegis-cff],default<O2>,aegis-verify`.
- Passes must run on **frontend IR** (`clang -O2 -Xclang -disable-llvm-passes -S -emit-llvm`).
  Running after inlining protects dead IR and `aegis-verify` fails the build on purpose.
- `aegis-policy` resolves policy entries once and pins them as `aegis.level` attributes plus
  `aegis.profile` / `aegis.seed` module flags; later passes read only attributes. Unresolved
  entries fail the build.
- `aegis-verify` is fail-closed: missing decoys/guard/state artifacts, wrong pass order, or a
  level-2/3 function the transform never touched is a build error, never a warning.
- Level 3 flattening must demote **all** cross-block SSA values (`DemotePHIToStack` /
  `DemoteRegToStack`) and use a `volatile` state slot; otherwise `-O2` or the verifier recovers
  the original CFG. Level 2 keeps its live split only if the two arms differ in volatile access
  counts.
- Ineligible constructs for level 3 (`indirectbr`, `callbr`, EH, coroutines, `returns_twice`,
  convergent calls, inline asm, `optnone`/`naked`/`musttail`) fail the build with a reason.

## Aegis-Bench architecture

Data flow for one run:

```
task.json ──► ArtifactBuilder ──► stripped probe ──► oracle broker ──► workspace shim
                 (levels 0–3)                              │
adapter.solve(task, workspace) ◄──────────────────────────┘
        │ sources
        ▼
Grader (independent) ──► hidden cases + seeded fuzz + property tests ──► RunRecord
                                                                          │
                                                     JSONL / CSV / Markdown reports
```

- **Task manifests** (`benchmarks/tasks-public/<id>/task.json`) pin `visible` files, ground
  truth, property tests, hidden cases, fuzz config, budgets and a **content hash covering all
  grader inputs**. Editing any task file requires `aegis-bench hash`; the hash is part of the
  result provenance.
- **Task ids are immutable.** Any semantic change (files, interface, artifact profiles,
  visibility) is a new id (`rolling-token-v1` vs `-v2`), never an in-place edit.
- **Binary-recovery access modes decide what a result can mean.** `--access oracle` (default)
  puts a counted shim in the workspace; the probe stays with the broker. The shim is identical in
  every artifact profile, so **a level-vs-baseline delta under `oracle` access is zero by
  construction** and cannot be cited as effectiveness. `--access binary` puts the stripped probe
  in the workspace, which is what the task contract and the threat model assume; queries are then
  uncounted (`oracle.queries` is `null`, never `0`) and a manifest oracle budget is rejected.
- **Binary-recovery tasks** build a probe from `artifact.source` (must equal `ground_truth`)
  through the same pipeline as the profile. The real binary stays with the harness broker
  (`aegis_bench/oracle.py`) under `oracle` access, which counts queries and enforces
  `budgets.oracle_queries`. This is accounting, not a sandbox — say so when documenting.
- **Grader isolation**: no task root on the include path, scratch cwd, minimal env, rlimits,
  output caps, candidate-source policy tripwires (`policy.py`). Errors are returned as grades
  with stages (`build`/`artifact`/`hidden`/`fuzz`/`agent`), not exceptions.
- **Cost honesty**: pass/fail, case counts, wall clock and oracle queries are measured; tool calls
  are adapter self-reports. Tokens are **measured only when the run had a meter** (`--meter-upstream`
  → provider `usage` via a per-run loopback proxy, stamped in `metering` and reflected in
  `ledger_source`); otherwise they are self-reported. Reports must keep that distinction and repeat
  the caveat next to the numbers, and must not mix metered and self-reported rows in one headline
  ratio. The meter is accounting, not a sandbox — say so.
- **Metering must not depend on adapter cooperation**: the proxy injects
  `stream_options.include_usage` itself. Do not "fix" an adapter that ignores `AEGIS_METER_BASE_URL`
  by rewriting `LLM_BASE_URL` — a run that bypasses the meter should stay visibly self-reported
  (`metering.requests == 0`), not look measured.
- **Private tasks** (`"private": true`) require `--allow-private`, are gitignored under
  `benchmarks/tasks-private/`, and produce a do-not-publish report banner.
- **Adapters live outside this repository** by design (no credentials/network in tree or CI).
  The contract a published result must satisfy is `docs/reference-adapter.md`.
- **Campaigns own the matrix.** A campaign manifest pins tasks, profiles, agent versions,
  repetitions, access, ordering seed, clean-tree and meter requirements. One fresh adapter
  instance runs each cell; rows carry a unique campaign cell key. Do not reintroduce a
  bespoke adapter-side report/checkpoint loop.
- **Resume reads the raw JSONL, not memory.** Reports are atomically replaced after every
  completed cell and an exclusive output lock prevents concurrent writers. `campaign-state.json`
  is a checkpoint; `aegis-bench audit` is the independent gate for duplicate/missing cells,
  commit/hash/version drift, mixed metering and dirty provenance.
- **Task schema v2** records `tool_policy`, `input_domain`, `experiment_use`, `difficulty` and
  `protectability` in every run row as `task_protocol`. The tool policy is declared metadata,
  not enforcement; process isolation and broker-owned tool counts remain a publishability gate.

## Reports and provenance

- Reports are machine-generated by `scripts/release-report.sh` / `scripts/pilot-report.sh` into
  `docs/reports/<name>/`; each names the commit and whether the tree was dirty. `dirty: yes`
  is not silently cleaned up.
- `docs/reports/archive/` holds frozen copies that claims point at; do not regenerate them.
- Validation reports use offline test doubles and are **not** effectiveness evidence; pilots
  with N < 5 are pilots, not claims.
- Keep `.text` deltas comparable only against the shared baseline; research profiles use
  different seeds and are not a monotonic ladder.

## Conventions that have bitten before

- Windows working copies: write scripts with `newline="\n"` (or `write_bytes`); `.gitattributes`
  pins LF for `*.sh`/`*.py`. Content hashing normalises CRLF, so hashes are checkout-stable.
- Harness Python is stdlib-only; do not add dependencies or vendor SDKs.
- `PowerShell`/`Git Bash` on Windows needs `MSYS_NO_PATHCONV=1` for `docker -v` mounts.
- CTest `aegis-bench` needs `AEGIS_PLUGIN` for level ≥ 1 artifact profiles; baseline needs only
  `clang++-23`/`opt-23`.
- When adding a run field, remember dataclass defaults must follow non-default fields and that
  `write_csv` has an explicit field list.
- A pilot's README is generated from its JSONL; when a number is wrong, fix
  `scripts/pilot-report.sh` and regenerate with `REUSE_DATA=<dir>`. The generator derives
  repetitions per cell from the rows, so never pass a `REPS` that disagrees with the data.
- Under `binary` access, wall clock can move **opposite** to tokens: the reasoning watchdog and
  restart policy interact with how readable the listing is (a flattened dispatcher can produce
  fewer runaways than straight-line code). Tokens are the cost signal; wall clock is a
  latency-contaminated second opinion, and the report must say so rather than report a
  negative delta as if protection made the agent faster.
- `scripts/pilot-report.sh` runs the campaign inside gitignored `bench-out/`, then copies rows
  into `docs/reports/`; this keeps `require_clean=true` from seeing its own output directory.
- `aegis-lint` is read-only and advisory. It uses the same eligibility predicates as the
  transforms, but only the transforms and `aegis-verify` fail a build.

## Where to read next

- `README.md` — positioning, honest expectations, current limits.
- `docs/benchmark-protocol.md` — task format, integrity rules, budgets, matrix, private set.
- `docs/reference-adapter.md` — adapter contract for real-model results.
- `docs/threat-model.md`, `docs/claims-ledger.md`, `docs/compatibility.md`, `docs/controlflow.md`.
- `tools/aegis-bench/README.md` — harness behaviour and deliberate limits.
