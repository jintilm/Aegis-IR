# Aegis-Bench (main product)

A deterministic protection engineering scorecard, plus an optional harness
for targeted model-cost studies. The default release path checks correctness,
`.text`, paired p95 and build-time budgets without invoking a model.

Model campaigns remain available when there is a specific cost question, but
AI-versus-AI loops are not the routine development or release loop.

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
├── campaign.py  experiment matrix, interleaving, checkpoint/resume
├── audit.py     JSONL/matrix/provenance audit
├── toolbroker.py policy-checked workspace tools, counters and call budget
├── worker.py    optional subprocess boundary + workspace-only TaskView
├── landlock.py  Linux filesystem/TCP-port worker policy
├── seccomp.py   Linux non-stream socket denial
├── report.py    JSONL / CSV / Markdown reports
├── scorecard.py deterministic correctness/size/runtime/build budgets
├── adapters/    offline deterministic adapters (test doubles)
└── cli.py       `hash`, `check`, `run`, `campaign`, `audit`, `scorecard`
tests/
├── test_harness.py   offline harness tests
├── test_campaign.py  campaign, resume and audit tests
├── test_toolbroker.py broker policy, counting and runner injection
└── test_worker.py    subprocess boundary and hidden-path exclusion
```

## Usage

```bash
cd tools/aegis-bench

# validate every task manifest and verify its content hash
python3 -m aegis_bench check --tasks-root ../../benchmarks/tasks-public

# evaluate deterministic protection budgets
python3 -m aegis_bench scorecard \
  --differential ../../build/differential-report.json \
  --budgets ../../experiments/protection-budgets.json \
  --out ../../build/scorecard

# evaluate the larger calibrated representative workload
python3 -m aegis_bench scorecard \
  --differential ../../build/representative-differential-report.json \
  --budgets ../../experiments/protection-budgets-representative.json \
  --out ../../build/scorecard-representative

# after editing a task, re-record its hash
python3 -m aegis_bench hash ../../benchmarks/tasks-public/rolling-token-v1

# run or resume the shipped offline smoke campaign
python3 -m aegis_bench campaign --config ../../experiments/offline-smoke.json
python3 -m aegis_bench audit ../../bench-out/offline-smoke \
    --experiment ../../experiments/offline-smoke.json

# smoke-run the offline negative control (baseline artifact build)
python3 -m aegis_bench run --tasks-root ../../benchmarks/tasks-public \
    --adapter stub --profile baseline --out /tmp/bench

# build a protected probe and score a known-correct answer
python3 -m aegis_bench run --tasks-root ../../benchmarks/tasks-public \
    --adapter ground-truth --profile aegis-level3 \
    --plugin ../../build/lib/AegisPass.so --out /tmp/bench-l3

# what a protection comparison needs: the probe itself in the workspace
python3 -m aegis_bench run --tasks-root ../../benchmarks/tasks-public \
    --adapter stub --profile aegis-level3 --access binary \
    --plugin ../../build/lib/AegisPass.so --out /tmp/bench-l3-binary
```

An optional model study uses a campaign manifest. The adapter still lives
**outside** this repository:

```bash
PYTHONPATH=/path/to/adapters python3 -m aegis_bench campaign \
    --config ../../experiments/protection-pilot.example.json \
    --plugin build/lib/AegisPass.so \
    --meter-upstream https://relay.example/v1
```

This path is research evidence, not a release requirement. Credentials are read
by the external adapter; nothing in this tree imports a vendor SDK or reads an
API key. The optional metering proxy is the only
harness-owned path to the model endpoint, and it exists only when
`--meter-upstream` is explicitly given. The tool broker is loopback-only. The
adapter must be run in an environment whose filesystem view contains only the
workspace. For real-model runs, configure process isolation plus
`require_sandbox` and `require_network_namespace`; the worker then receives a
workspace-only `TaskView`, Landlock/seccomp restrictions and a private network
namespace.
`adapter.solve` is
bounded by `--adapter-timeout` (default 600 s, SIGALRM on POSIX).
Campaigns create a fresh adapter instance for every cell, require a non-empty
adapter version, and record the manifest fingerprint and cell key in each row.
Unless `--no-tool-broker` is given, each cell exports
`AEGIS_TOOL_BROKER_URL` and `AEGIS_TOOL_BROKER_TOKEN`. Adapters use
`aegis_bench.toolbroker.call_tool` for policy-checked workspace reads, probe
execution, disassembly and submission.

Campaign manifests can set `adapter_isolation: "process"` (or `run` can pass
`--adapter-isolation process`). The adapter then executes in a fresh child with
a workspace-only `TaskView`, not the repository task root. This is a process
boundary for crash/object-state isolation. On Linux, `require_sandbox: true`
adds Landlock: runtime/workspace filesystem allowlists and TCP connects only
to the broker/meter ports. Seccomp additionally denies UDP/raw/RDM/SEQPACKET
IP sockets. `require_network_namespace: true` adds a private loopback-only
network namespace and bridges broker/meter over per-run Unix sockets.

Campaign schema v2 agent entries can carry constructor `options`. A single
`openai_adapter:OpenAICompatAgent` can therefore appear twice, with
`{"model": "deepseek-v4-pro"}` and `{"model": "deepseek-flash"}`, inside one
matrix. The harness records the options as `agent_config` and replays them in
the process worker.

Task schema v4 requires a `core` or `exploratory` tier. The public set contains
twelve tasks: six in each tier. Eleven are binary-recovery tasks and one is the
frozen reimplementation task.

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
probe per profile. What the workspace gets depends on `--access`:

- `--access oracle` (default): an **oracle broker** holds the probe and the
  workspace receives only a `probe` shim that forwards stdin to it. Every query
  is counted and `budgets.oracle_queries` is enforced when set. The run row
  records the probe's SHA-256, `.text` size and build log, plus the broker's
  served/refused counts. The agent is a black-box adversary: the shim behaves
  identically in every profile, so **no protection effect can be measured in
  this mode**.
- `--access binary`: the workspace receives the stripped probe itself, as the
  task contract promises. The agent can execute and disassemble it, which is
  the only mode in which levels 1–3 can change the cost. Queries are not
  counted (`oracle.queries` is `null`), and a manifest that sets
  `budgets.oracle_queries` is rejected rather than silently unenforced.

Either way the probe is built from the ground truth with the same optimization
pipeline as the profile, so a level-3 run is genuinely flattening the code the
agent reverses.

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
binary-recovery tasks under `oracle` access — oracle queries. The broker sees
the queries because the workspace holds a shim, not the probe. Under `binary`
access it sees nothing: the probe is local, so `oracle.queries` is `null` (not
`0`, which would claim a measurement) and the mode is stamped in every row.

Token usage is measured too, when the run has a meter: `--meter-upstream
<relay-url>` puts a loopback proxy in front of the model endpoint, exports it as
`AEGIS_METER_BASE_URL`, and records the provider's own `usage` report in the
row's `metering` block. The proxy asks for usage on the adapter's behalf
(`stream_options.include_usage`), so measurement does not depend on the
measured party remembering to report. Without a meter the figures come from the
adapter and are recorded with `ledger_source: "self-reported by adapter"`.
Tool calls are measured by the harness broker when the adapter uses its
exported endpoints. The broker applies the task's `tool_policy`, enforces
`budgets.max_tool_calls`, records per-tool counts/denials/bytes, and compares
its observed requests with the adapter's self-report. An adapter that bypasses
the broker has `tools.requests: 0` and remains visibly self-reported.

Both brokers and the meter are accounting, not sandboxes. An adapter that
walks the filesystem can find the artifact cache and execute the probe
directly; an adapter that calls the relay directly bypasses the meter (its row
then shows `metering.requests: 0`). Reports say so. The tool broker becomes an
enforcement boundary only after the adapter worker is mounted without direct
repository or artifact-cache access.

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

Rows also carry `record_schema_version`, `agent_config`, `task_protocol`
(schema version, tier, tool policy, input domain, experiment use, difficulty,
protectability) and a `campaign` block with campaign id, purpose, primary
metric, manifest SHA-256, cell key and order index. `aegis-bench audit` checks
duplicates, missing cells, commit/hash/version drift, agent configuration,
mixed meter provenance and campaign fingerprint consistency. See
[`docs/campaigns.md`](../../docs/campaigns.md).

The `tools` block records broker requests, allowed/denied/failed counts,
per-tool calls, denials, bytes in/out, call cap, and the adapter's own
tool-call figure. `adapter_exceeds_broker` is the detectable bypass signal.

The default adapter is in-process for debugging and offline built-ins. A
publishable real-model campaign sets process isolation, `require_sandbox` and
`require_network_namespace`; the worker then sees only the workspace and its
loopback bridges. A direct tool implementation can still bypass broker
accounting, which is why `require_broker_tools` is audited. Acceptance tests
are in [`docs/isolation.md`](../../docs/isolation.md).

## Deliberate limits

- Twelve public tasks today: one frozen reimplementation task and eleven
  binary-recovery tasks covering rolling hashes, packed records, lane mixing,
  parsers, state folds, ring buffers, grid routing, delta ledgers, S-boxes,
  bit mosaics and packet weaving. Task count is not itself evidence; cost
  numbers still require calibration and a completed model matrix.
- Calibration records default to `uncalibrated` when no model baseline exists.
  Six binary-recovery tasks remain uncalibrated for both pilot models; four
  have N=1 screening records; only `packed-record-v1` is N=5
  `comparison-ready` for both `deepseek-v4-pro` and `deepseek-flash`. N=1
  screening results are never represented as N=5 comparison evidence.
- No model adapters in-tree, by design. The contract a published result must
  satisfy is [`docs/reference-adapter.md`](../../docs/reference-adapter.md).
- Oracle queries are counted and optionally capped by the broker, but the
  broker is not a sandbox; a direct probe invocation is uncounted. The
  protocol's oracle-budget curve is now implementable, not yet measured.
- Under `binary` access the probe is in the workspace, so query counting is
  impossible and is reported as `null` rather than estimated. Counting a local
  binary needs process-level execution accounting, which the harness does not
  have.
- Under `oracle` access no protection effect exists to measure: the shim is
  identical in every artifact profile. Sections that compare levels must say
  which access mode they used.
- A submission that embeds or wraps the probe is invalid. The obvious forms
  are rejected by the source policy (size, `exec*`, grader paths); a hidden
  blob is not automatically detectable, so review is still required.
- Windows support is incidental (used for development); CI and reported
  numbers run on Linux.
- The run report is machine-written and not peer-reviewed; it is evidence
  for the claims ledger, not a substitute for it.
- No report establishes production performance or attack effectiveness. The
  deterministic workloads are engineering regression gates, and the model
  pilots are descriptive cost studies with unresolved success-rate effects.
