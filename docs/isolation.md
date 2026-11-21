# Isolation and tool accounting

Status: the loopback tool broker, adapter subprocess, Linux Landlock
filesystem/TCP-port boundary, seccomp non-stream-socket block, private
network-namespace worker and disposable container-per-cell path are
implemented. A non-Linux or Landlock-disabled process is only a process
boundary. The network namespace requires `unshare` permission; container mode
requires a reachable OCI runtime and local image.

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
| Tool broker | loopback policy checks, counters, byte caps and call cap when the adapter uses it |
| Adapter process | optional fresh child process with a workspace-only TaskView and no repository task root |
| Landlock worker | Linux filesystem allowlist and TCP connect rules for broker/meter ports |
| Seccomp worker | deny UDP/raw/RDM/SEQPACKET IP socket creation |
| Network namespace | private loopback-only namespace; broker/meter reached through per-run Unix sockets |
| Container worker | non-root, read-only root, capabilities dropped, no-new-privileges, network none, PID/memory/CPU/no-file limits, workspace/transport/socket-only mounts |

These controls stop accidental leakage and several replay tricks. With the
publishable worker flags, host filesystem reads and direct host network
connects fail. The adapter can still execute subprocesses inside that boundary,
and the grader remains a separate trusted process rather than a fully
container-isolated service. Adapters are still treated as trusted code for
supply-chain and credential purposes.

## Target architecture

```text
                   control plane (trusted)
  experiment manifest -> campaign planner -> cell supervisor
                                                |
                 +------------------------------+-------------------+
                 |                                                  |
          adapter worker (untrusted)                       tool broker (trusted)
          - fresh process implemented                      - workspace-relative FS
          - container/namespace next                       - counters + limits
          - workspace mounted rw                             - run_probe
          - adapter code mounted ro                           - disassemble
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

The implemented worker is one fresh subprocess or container per cell. Process
mode optionally uses Landlock, seccomp and a private network namespace.
Container mode adds a read-only root, read-only adapter/package mounts,
non-root execution, host PID isolation, resource limits and no network:

1. Create a fresh workspace with only the declared visible files.
2. Start a disposable container with read-only adapter/package mounts.
3. Mount the workspace read-write and nothing else from the repository.
4. Mount no task root, ground truth, hidden cases, policy source, artifact
   cache or prior workspace.
5. Give the worker no host PID namespace, no host network and no inherited
   credentials beyond the per-run meter URL/token.
6. Stop and delete the worker after the result, timeout or crash.

The harness already starts one oracle broker and one meter per run. Those
become network services scoped to the worker's lifecycle.

The subprocess path uses `TaskView.path()` to hide task-root paths and keeps
the broker/meter endpoints in the child environment. On Linux with Landlock,
the worker installs a filesystem allowlist and permits TCP connects only to the
broker/meter ports. A narrow seccomp policy also denies UDP/raw/RDM/SEQPACKET
IP socket creation. The tests verify that repo reads, unapproved TCP ports, and
UDP sockets are denied. With `require_network_namespace`, the worker runs under
`unshare` in a namespace whose only interface is loopback. It cannot route to
the host; the trusted broker and meter expose Unix sockets and the worker
bridges them to loopback HTTP ports. The acceptance test starts a host
listener at a reachable container address and verifies the worker cannot
connect to it, while a brokered tool call still succeeds.

The container path has deterministic command/lifecycle tests in
`test_container.py` and an optional real local-runtime smoke at
`tests/container/run_smoke.py`. The real smoke verifies non-root, read-only
root, network none, dropped capabilities, no-new-privileges, Landlock/seccomp
and a private namespace.

## Tool broker

The implemented first stage exports a loopback broker and a client helper. The
reference adapter prefers it over direct workspace access. The broker
validates each request against the task's schema-v2 `tool_policy`:

| Tool | Broker behaviour | Counted evidence |
|---|---|---|
| `list_files` | list workspace-relative entries only | calls, entries returned |
| `read_file` | resolve inside workspace, text/size/binary checks | calls, bytes, denials |
| `run_probe` | execute the harness-private verified artifact; oracle mode calls the counted service directly | calls, input/output bytes, exit code, oracle count |
| `disassemble` | invoke a local disassembler over the same harness-private artifact, cap output | calls, bytes, lines, denial reason |
| `submit_solution` | validate names/size/policy and return source text | calls, accepted/rejected, byte count |

Before starting an adapter, the runner checks the artifact's recorded SHA-256
and size and copies the verified bytes to a private per-run directory. On
POSIX the snapshot is read-only and executable. This directory is neither
mounted into a container worker nor included in the Landlock worker's
allowlist. The broker binds execution and disassembly to that snapshot; it
never discovers executable commands from the writable workspace. Replacing
the workspace `probe` or oracle shim cannot change broker execution, and
oracle requests still pass through the oracle service's counter and budget.
In-process adapters remain trusted and are not isolated from harness memory
or filesystem state.

Artifact cache hits are checked against their metadata before reuse, including
in-memory hits. A modified probe or inconsistent cache metadata is an artifact
error. Probe stdout/stderr and disassembly output are bounded while reading;
an oversized stream fails the tool request rather than silently returning a
successful truncated execution. Runtime probes receive a minimal environment
without model credentials.

Stopping a run first cancels both brokers, interrupts incomplete socket
requests and terminates active probe/disassembly process groups. Request
handlers are drained before final counters are recorded and the private
snapshot is removed. The oracle service uses the same cancellation event for
its active subprocess, so a tool call waiting on the oracle cannot prolong
cleanup until the normal query timeout.

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

The row now distinguishes broker-measured calls (`tools.*`) from the adapter's
own ledger. `budgets.max_tool_calls` is enforced by broker refusal for mediated
calls. The remaining gap is enforcement against direct filesystem/subprocess
access: under the worker design the broker is the only available path.

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
network enforcement; the meter supplies the provider-attested number. The tool
broker follows the same rule: it is authoritative only for calls that reach it.

## Isolation acceptance tests

A release must fail if any of these controls is missing:

- worker cannot open a file above its workspace mount;
- a symlink in the workspace cannot resolve outside the mount;
- worker cannot see the task root, artifact cache, hidden cases or `/proc`
  entries for trusted processes;
- direct DNS/HTTP egress fails; only the meter origin is reachable;
- executing the cached probe directly is impossible because the cache is not
  mounted, and `run_probe` requests are attributed to the broker;
- replacing a workspace probe does not change broker execution or disassembly;
- oversized probe/disassembly streams fail within the configured byte cap;
- `submit_solution` cannot smuggle extra paths or an oversized source;
- killing the worker leaves no child process or listening proxy;
- grader input contains candidate text only and no worker filesystem handle;
- a second cell gets a new workspace, meter, oracle broker and tool counters.

## Publishability gate

A campaign can be used as a **measurement** when reports are metered and
auditable. A campaign can support a **protection-effect claim** only when
`require_sandbox: true` and `require_network_namespace: true` rows pass audit:

- token results may be cited only with the current meter caveat;
- broker tool counts describe mediated calls, while `tools.requests: 0` means
  the adapter bypassed the broker;
- oracle access is counted only because the workspace holds the shim;
- binary access does not count local executions;
- the network namespace removes host routing; the Unix-socket bridge is the
  only broker/meter path;
- no report may imply that the adapter or grader is fully host-isolated.
