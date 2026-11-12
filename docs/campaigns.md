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

```json
{
  "schema_version": 1,
  "name": "packed-record-protection-pilot",
  "purpose": "pilot",
  "primary_metric": "tokens",
  "tasks_root": "../benchmarks/tasks-public",
  "tasks": ["packed-record-v1", "lane-shift-v1"],
  "agents": [
    {
      "id": "openai-deepseek-v4-pro",
      "adapter": "openai_adapter:OpenAICompatAgent",
      "expected_version": "7fc63d1279f9"
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
  "allow_oracle_comparison": false,
  "out": "../bench-out/packed-record-protection-pilot"
}
```

| Field | Rule |
|---|---|
| `schema_version` | currently `1` |
| `name` | stable campaign id used in every row |
| `purpose` | `harness-validation`, `pilot`, or `experiment` |
| `primary_metric` | `pass_rate`, `tokens`, `wall_seconds`, or `oracle_queries` |
| `tasks_root` | resolved relative to the manifest |
| `tasks` | unique task ids under `tasks_root` |
| `agents[].id` | must equal `Agent.name` |
| `agents[].adapter` | `module:Class` or a built-in adapter |
| `agents[].expected_version` | optional exact `Agent.version` check |
| `profiles` | unique artifact profile names for every binary task |
| `repetitions` | positive count |
| `repetition_start` | non-negative offset for a partial continuation |
| `access` | `oracle` or `binary`; multi-profile binary tasks require `binary` |
| `order` | `interleaved` (default), `randomized`, or `sequential` |
| `seed` | deterministic order seed |
| `require_clean` | reject a dirty worktree before the first paid cell |
| `require_meter` | reject a campaign with no model metering proxy |
| `require_broker_tools` | fail audit if any run has no harness-broker tool traffic |
| `adapter_isolation` | `in-process` or `process`; `process` is a subprocess boundary, not a filesystem/network sandbox |
| `require_sandbox` | require Linux Landlock filesystem/TCP rules plus the seccomp non-stream-socket block |

All adapters must expose a non-empty `version`. A campaign preflights every
adapter once, checks its identity and version, and then creates a fresh
instance for each cell. Counters or conversation state therefore cannot leak
between repetitions.

`require_clean=true` and `require_meter=true` are the defaults for a
publishable campaign. Set them to `false` only for an offline smoke run, and do
not cite that output as a model result.

`adapter_isolation: "process"` imports a fresh adapter inside a child process
and passes it a workspace-only `TaskView`, not the repository task root.
The parent still owns brokered tools and grading. This closes object-state and
crash coupling. With `require_sandbox: true`, Landlock additionally installs a
workspace/runtime filesystem allowlist and TCP connect rules for only the
broker/meter ports before adapter code runs. Seccomp denies UDP/raw/RDM/
SEQPACKET IP socket creation. Same-port IP targeting and full network
namespaces remain outside this boundary.

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

Campaigns orchestrate work but do not sandbox the adapter. The adapter still
runs in-process and can reach paths outside the workspace. Mediated requests
through the loopback tool broker are measured and capped, while direct file or
subprocess access bypasses it and shows `tools.requests: 0`. The worker
boundary is in [`isolation.md`](isolation.md); a protection-effect claim
requires process isolation as well as a passing audit.
