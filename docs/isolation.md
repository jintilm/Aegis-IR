# Isolation and tool accounting

Status: design plus the schema hooks implemented today. The in-process adapter
and grader are **not** a sandbox. This document distinguishes what the current
code enforces from what a publishable campaign must add.

## What is implemented

| Boundary | Implemented behaviour |
|---|---|
| Agent workspace | only files named by `visible` are copied |
| Ground truth | stays outside the workspace; task-load and workspace tests assert it |
| Candidate sources | bare filenames only; path traversal is rejected |
| Candidate include policy | absolute/parent includes and grader paths are rejected |
| Compile/run scratch | private directory, minimal environment, timeout, rlimits, output cap |
| Oracle access | harness broker counts and optionally caps queries |
| Token traffic | optional loopback proxy measures provider `usage` |
| Campaign persistence | atomic reports, checkpoint, resume, audit |
| Task tool contract | schema v2 `tool_policy` records the declared tool set |

These controls stop accidental leakage and several replay tricks. They do not
stop a malicious adapter from walking the host filesystem, reading the
artifact cache, opening a direct socket, or executing subprocesses. Adapters
are therefore trusted code until the worker boundary below exists.

## Target architecture

```text
                   control plane (trusted)
  experiment manifest -> campaign planner -> cell supervisor
                                                |
                 +------------------------------+-------------------+
                 |                                                  |
          adapter worker (untrusted)                       tool broker (trusted)
          - fresh process/container                        - workspace-relative FS
          - workspace mounted rw                             - run_probe
          - adapter code mounted ro                           - disassemble
          - no task/grader/cache mount                        - counters + limits
          - egress only to meter proxy                        - denial log
                 |                                                  |
                 +------------------ JSON result -------------------+
                                                |
                                         grader worker (trusted)
                                         - candidate text only
                                         - no adapter process
```

The control plane owns the experiment and never executes model output. The
adapter worker sees only its workspace, an adapter bundle and the tool broker.
The grader receives candidate text and hidden grading material in a separate
process, so a compromised adapter cannot observe the grader's file view.

## Worker boundary

The minimum publishable boundary is one worker per cell:

1. Create a fresh workspace with only the declared visible files.
2. Start a disposable process or container with a read-only adapter mount.
3. Mount the workspace read-write and nothing else from the repository.
4. Mount no task root, ground truth, hidden cases, policy source, artifact
   cache or prior workspace.
5. Give the worker no host PID namespace, no host network and no inherited
   credentials beyond the per-run meter URL/token.
6. Stop and delete the worker after the result, timeout or crash.

The harness already starts one oracle broker and one meter per run. Those
become network services scoped to the worker's lifecycle.

## Tool broker

The adapter protocol stops calling tools directly and sends typed requests to
a harness-owned broker. The broker validates each request against the task's
schema-v2 `tool_policy`:

| Tool | Broker behaviour | Counted evidence |
|---|---|---|
| `list_files` | list workspace-relative entries only | calls, entries returned |
| `read_file` | resolve inside workspace, text/size/binary checks | calls, bytes, denials |
| `run_probe` | execute only the broker-held or workspace artifact | calls, input/output bytes, exit code, oracle count |
| `disassemble` | invoke a pinned tool over the artifact, cap output | calls, bytes, lines, denial reason |
| `submit_solution` | validate names/size/policy and return source text | calls, accepted/rejected, byte count |

Every broker call gets a monotonically increasing sequence number, start/end
time and status. A run row adds:

```json
{
  "tools": {
    "calls": 31,
    "calls_by_tool": {"run_probe": 12, "disassemble": 18, "submit_solution": 1},
    "denied": 2,
    "denials": [{"tool": "read_file", "reason": "escapes workspace"}],
    "bytes_read": 48120,
    "bytes_returned": 221904
  }
}
```

The row must distinguish broker-measured calls from an adapter's own ledger.
Today `ledger.tool_calls` is self-reported. Under the worker design the broker
count is authoritative and `budgets.max_tool_calls` is enforced by refusal,
not trusted after the fact.

## Network and metering

The worker may reach only the harness meter proxy. The proxy forwards the
approved model endpoint and records provider `usage`; a direct endpoint
connection must fail at the worker's network policy.

This closes the current meter gap: today an adapter can bypass the proxy while
still producing a plausible self-report. Under isolation:

- direct egress is denied by the worker's network namespace;
- the broker and meter are per-cell ports with no cross-cell reuse;
- provider retries remain inside the measured path;
- abandoned calls retain the current close-on-client-disconnect rule;
- the metered total stays a floor when no usage arrives, and is labelled as
  such rather than replaced with a character estimate.

Token metering remains accounting, not sandboxing. Isolation supplies the
network enforcement; the meter supplies the provider-attested number.

## Isolation acceptance tests

A release must fail if any of these controls is missing:

- worker cannot open a file above its workspace mount;
- a symlink in the workspace cannot resolve outside the mount;
- worker cannot see the task root, artifact cache, hidden cases or `/proc`
  entries for trusted processes;
- direct DNS/HTTP egress fails; only the meter origin is reachable;
- executing the cached probe directly is impossible because the cache is not
  mounted, and `run_probe` requests are attributed to the broker;
- oversized read/disassembly output is truncated and counted, not buffered;
- `submit_solution` cannot smuggle extra paths or an oversized source;
- killing the worker leaves no child process or listening proxy;
- grader input contains candidate text only and no worker filesystem handle;
- a second cell gets a new workspace, meter, oracle broker and tool counters.

## Publishability gate

A campaign can be used as a **measurement** when reports are metered and
auditable. A campaign can support a **protection-effect claim** only after the
worker boundary and broker tool counts are implemented and the isolation
acceptance tests run in CI. Until then:

- token results may be cited only with the current meter caveat;
- tool calls are descriptive self-reports;
- oracle access is counted only because the workspace holds the shim;
- binary access does not count local executions;
- no report may imply that the adapter or grader is sandboxed.
