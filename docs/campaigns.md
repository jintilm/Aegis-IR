# Experiment campaigns

Status: implemented in `tools/aegis-bench`. Campaigns are the supported path
for multi-cell runs; a bespoke adapter-side loop is no longer part of the
measurement contract.

`aegis-bench run` remains useful for a single smoke cell. A campaign adds the
things that a multi-hour comparison needs:

- an immutable experiment manifest with a SHA-256 fingerprint;
- one fresh adapter instance per cell;
- unique `(task, profile, agent, repetition)` identity;
- interleaved profile order inside each repetition;
- atomic report writes after every completed cell;
- a non-blocking exclusive lock so two processes cannot write one output;
- resume that skips only cells already present in the raw JSONL;
- an independent `audit` command for duplicates, missing cells, mixed
  metering, stale task hashes and dirty-tree provenance.

## Manifest

The following illustrates the matrix shape. For the reference adapter,
replace each `expected_version` and the entire `options` object using the
[complete manifest generator](reference-adapter.md); the placeholders below
are intentionally not runnable. Model-only options no longer pin all effective
parameters and are rejected by preflight.

```json
{
  "schema_version": 2,
  "name": "packed-record-protection-pilot",
  "purpose": "pilot",
  "primary_metric": "tokens",
  "tasks_root": "../benchmarks/tasks-public",
  "tasks": ["packed-record-v1", "lane-shift-v1"],
  "agents": [
    {
      "id": "openai-deepseek-v4-pro",
      "adapter": "openai_adapter:OpenAICompatAgent",
      "expected_version": "replace-with-source-hash",
      "options": {"model": "deepseek-v4-pro", "config_sha256": "replace-entire-options-object"}
    },
    {
      "id": "openai-deepseek-flash",
      "adapter": "openai_adapter:OpenAICompatAgent",
      "expected_version": "replace-with-source-hash",
      "options": {"model": "deepseek-flash", "config_sha256": "replace-entire-options-object"}
    }
  ],
  "profiles": [
    "baseline",
    "aegis-level1",
    "aegis-level2",
    "aegis-level3"
  ],
  "repetitions": 5,
  "repetition_start": 0,
  "access": "binary",
  "order": "interleaved",
  "seed": 20261112,
  "require_clean": true,
  "require_meter": true,
  "require_broker_tools": true,
  "adapter_isolation": "process",
  "require_sandbox": true,
  "require_network_namespace": true,
  "allow_oracle_comparison": false,
  "out": "../bench-out/packed-record-protection-pilot"
}
```

| Field | Rule |
|---|---|
| `schema_version` | `1` remains readable; new manifests use `2` |
| `name` | stable campaign id used in every row |
| `purpose` | `harness-validation`, `pilot`, or `experiment` |
| `primary_metric` | `pass_rate`, `tokens`, `wall_seconds`, or `oracle_queries` |
| `tasks_root` | resolved relative to the manifest |
| `tasks` | unique task ids under `tasks_root` |
| `agents[].id` | must equal the configured `Agent.name` |
| `agents[].adapter` | `module:Class` or a built-in adapter |
| `agents[].expected_version` | optional exact `Agent.version` check |
| `agents[].options` | constructor options, replayed inside the worker; adapters exposing `effective_options()` require the complete returned object, including its configuration fingerprint |
| `profiles` | unique artifact profile names for every binary task |
| `repetitions` | positive count |
| `repetition_start` | non-negative offset for a partial continuation |
| `access` | `oracle` or `binary`; multi-profile binary tasks require `binary` |
| `order` | `interleaved` (default), `randomized`, or `sequential` |
| `seed` | deterministic order seed |
| `require_clean` | reject a dirty worktree before the first paid cell |
| `require_meter` | reject a campaign with no model metering proxy |
| `require_broker_tools` | fail audit if any run has no harness-broker tool traffic |
| `adapter_isolation` | `in-process`, `process`, or `container`; process adds a child boundary, container adds the full OCI boundary recorded in the row |
| `require_sandbox` | require process-mode Landlock/seccomp or the audited container boundary |
| `require_network_namespace` | require a private process network namespace or `--network=none` container; broker/meter use Unix sockets |

All adapters must expose a non-empty `version`. A campaign preflights every
configured agent once, checks its identity, version and options, and then
creates a fresh instance for each cell. Two agents may share one adapter class
when their `options` select different model ids. Counters or conversation
state therefore cannot leak between repetitions.

`require_clean=true` and `require_meter=true` are the defaults for a
publishable campaign. Set them to `false` only for an offline smoke run, and do
not cite that output as a model result.

`adapter_isolation: "process"` imports a fresh adapter inside a child process
and passes it a workspace-only `TaskView`, not the repository task root.
The parent still owns brokered tools and grading. This closes object-state and
crash coupling. With `require_sandbox: true`, Landlock additionally installs a
workspace/runtime filesystem allowlist and TCP connect rules for only the
broker/meter ports before adapter code runs. Seccomp denies UDP/raw/RDM/
SEQPACKET IP socket creation. With `require_network_namespace`, the worker
also enters a private Linux network namespace containing only loopback. The
trusted broker and meter stay in the host namespace and expose Unix sockets;
the worker bridges those to loopback HTTP ports for the adapter. A direct
connection to any host address has no route.

`adapter_isolation: "container"` runs one fresh container per cell with a
read-only root, non-root user, all capabilities dropped,
`no-new-privileges`, `--network=none`, resource limits and only the workspace,
transport, read-only adapter/package mounts and broker/meter Unix sockets.
`require_sandbox` and `require_network_namespace` accept this mode. Audit
fails a container row unless the recorded boundary says read-only root,
network none, capabilities dropped, no-new-privileges and non-root.

## Commands

Run the shipped offline smoke campaign:

```bash
cd tools/aegis-bench
python3 -m aegis_bench campaign --config ../../experiments/offline-smoke.json
python3 -m aegis_bench audit ../../bench-out/offline-smoke \
  --experiment ../../experiments/offline-smoke.json

# exercise the process worker, tool broker and Linux Landlock boundary
python3 -m aegis_bench campaign --config ../../experiments/process-smoke.json
python3 -m aegis_bench audit ../../bench-out/process-smoke \
  --experiment ../../experiments/process-smoke.json

# requires SYS_ADMIN/NET_ADMIN or unprivileged user namespaces
python3 -m aegis_bench campaign --config ../../experiments/netns-smoke.json
python3 -m aegis_bench audit ../../bench-out/netns-smoke \
  --experiment ../../experiments/netns-smoke.json
```

Run a real pilot:

```bash
cd tools/aegis-bench
PYTHONPATH=/path/to/adapters \
python3 -m aegis_bench campaign \
  --config ../../experiments/protection-pilot.example.json \
  --plugin ../../build/lib/AegisPass.so \
  --meter-upstream https://relay.example/v1
```

The out-of-tree `aegis-adapters/run_pilot.py` is now only a thin wrapper around
this command: it generates a manifest, pins the adapter name/version, and
delegates execution, reports, resume and audit to the harness. Adapter code
must not implement a second matrix/report loop.

Re-running the same command resumes. A completed campaign performs preflight
and audit-compatible reconstruction but spends no extra model calls:

```bash
python3 -m aegis_bench campaign --config ../../experiments/offline-smoke.json
```

The output directory contains:

```text
campaign.json          # immutable snapshot of the parsed manifest
campaign-state.json    # atomic checkpoint written after every cell
.campaign.lock         # process-lifetime writer lock; never edit
aegis-bench.jsonl      # raw rows, the source of truth for resume
aegis-bench.csv
aegis-bench.md
```

If `campaign.json` or a row's manifest fingerprint differs from the current
manifest, resume is refused. Use a new output directory; the harness does not
silently mix two experiments.

## Ordering

`interleaved` builds one full task x profile x agent matrix for each
repetition, shuffles within that block, then runs the next repetition. This
keeps every arm in the same broad time window and therefore exposes all arms
to similar relay drift.

`randomized` shuffles all cells. `sequential` keeps manifest order. The chosen
order, seed and global cell index are recorded in each row, so an auditor can
reconstruct what ran when.

## Failure and resume

A row is written after the adapter call and grading return. Reports are
replaced atomically; a process killed during a write leaves the previous
complete JSONL in place. On restart the campaign:

1. verifies the manifest snapshot;
2. loads every raw row and reconstructs its run record;
3. rejects duplicate, unknown or foreign campaign cells;
4. skips cells whose key is already present;
5. continues with the next planned cell.

A completed row is not automatically retried. This is deliberate: retrying an
infrastructure failure without recording the first paid attempt would hide
cost and selection effects. `aegis-bench audit` marks infrastructure failures;
rerunning a contaminated cell means starting a new campaign with the correct
configuration.

## Audit

`aegis-bench audit` accepts a report directory or a JSONL file. With
`--experiment`, it checks the exact planned matrix; without one, it still
checks file-level invariants.

The audit fails on:

- invalid JSON or a missing row shape;
- duplicate `run_id` or cell identity;
- rows from different commits;
- mixed metered and self-reported token provenance;
- a campaign with missing or unexpected cells;
- campaign id or manifest fingerprint mismatch;
- stale task content hashes;
- a required meter that is absent;
- binary-access rows claiming a measured oracle-query count;
- malformed artifact provenance.

It warns on:

- a dirty worktree;
- missing adapter versions or mixed versions for one adapter id;
- adapter tool counts that exceed broker-observed calls;
- partial provider usage or abandoned calls;
- adapter traffic that may have bypassed the meter;
- repetition gaps in a standalone file;
- infrastructure-looking failures;
- any recorded row-level error.

Use `--strict` in CI or before publication to turn warnings into failure.
`--json` emits the same result for automation.

## Current boundary

`adapter_isolation: "process"` remains the portable Linux boundary.
`adapter_isolation: "container"` is the stronger option when a local OCI
runtime and image are available. Both use Unix-socket broker/meter transport
and keep mediated calls counted. Tool choices that bypass the broker still
appear as `tools.requests: 0`. See [`isolation.md`](isolation.md) for the
acceptance tests and remaining trust boundary.
